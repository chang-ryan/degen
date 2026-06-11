"""Free SEC EDGAR filing fetcher — primary-source documents, no API key.

Adapted from a friend's earnings-analysis agent (external/Earnings Agent Slim).
Resolves a ticker to its CIK, downloads recent 10-K / 10-Q / 8-K primary
documents, strips HTML to text, and best-effort carves out the sections the
thesis workflow cares about (revenue recognition, critical accounting policies,
business description, latest earnings 8-K). Public SEC endpoints only:

    https://www.sec.gov/files/company_tickers.json      (ticker -> CIK)
    https://data.sec.gov/submissions/CIK##########.json (filing history)
    https://www.sec.gov/Archives/edgar/data/...         (filing documents)

Why this exists here: the rest of the toolkit lives on price/vol data. Around
an earnings catalyst (CRM Sep 2, etc.) the *validation* questions are in the
filings — did rev-rec change ahead of a beat, what does the 8-K actually say —
and this pulls those primary sources locally where the debrief can read them.

SEC fair-access policy requires a User-Agent identifying the caller; override
the default via SEC_USER_AGENT or --user-agent.

Outputs land in `data/filings/{TICKER}/` (gitignored):
    latest_10K.txt, latest_10K_rev_rec.txt, latest_10K_critical_acct.txt,
    latest_10K_business.txt, latest_10Q.txt, latest_10Q_rev_rec.txt,
    latest_earnings_8K.txt, recent_8Ks/<date>_<accession>.txt, manifest.json

`uv run python -m degen.edgar --ticker CRM`
`uv run python -m degen.edgar --ticker CRM --forms 10-Q,8-K --count 4`
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

DEFAULT_USER_AGENT = "degen toolkit ryanhchang@gmail.com"
FILINGS_DIR = Path("data/filings")

SECTION_PATTERNS = {
    "rev_rec": re.compile(
        r"(?i)(?:revenue\s+recognition|recognition\s+of\s+revenue|disaggregation\s+of\s+revenue)"
    ),
    "critical_acct": re.compile(r"(?i)critical\s+accounting\s+(?:policies|estimates)"),
    "business": re.compile(r"(?i)(?:item\s*1\b.*business|business\s+overview|our\s+business)"),
}


# ---------- HTTP ----------


def _user_agent(override: str | None = None) -> str:
    return override or os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT


def _http_get(url: str, user_agent: str, *, retries: int = 3, pause: float = 0.4) -> bytes:
    """GET with the SEC-required User-Agent; retries transient errors.

    SEC rate-limits at ~10 req/s — the pause keeps single-user use well under.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                time.sleep(pause)
                return raw
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}\n  {last_err}")


# ---------- HTML -> text ----------


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t\xa0]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:  # malformed markup — crude tag strip beats nothing
        return re.sub(r"<[^>]+>", " ", html)
    return p.text()


def extract_section(text: str, pattern: re.Pattern[str], window: int = 8000) -> str | None:
    """Return a window of text starting at the first pattern match, or None."""
    m = pattern.search(text)
    if not m:
        return None
    return text[m.start() : m.start() + window]


# ---------- EDGAR lookups ----------


def resolve_cik(ticker: str, user_agent: str) -> tuple[str, str]:
    """Return (zero-padded 10-digit CIK, company title) for a ticker."""
    data = json.loads(_http_get(SEC_TICKERS_URL, user_agent).decode("utf-8"))
    tu = ticker.upper()
    for row in data.values():
        if str(row.get("ticker", "")).upper() == tu:
            return f"{int(row['cik_str']):010d}", row.get("title", "")
    raise ValueError(f"Ticker {ticker!r} not found in SEC company_tickers.json")


def get_submissions(cik10: str, user_agent: str) -> dict:
    return json.loads(_http_get(SEC_SUBMISSIONS_URL.format(cik10=cik10), user_agent).decode())


def recent_filings(submissions: dict, form: str, count: int) -> list[dict]:
    """Up to `count` most-recent filings of a form type (exact match, no /A)."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [""] * len(forms))
    out: list[dict] = []
    for i, f in enumerate(forms):
        if f == form:
            out.append(
                {
                    "form": f,
                    "accession": accs[i],
                    "primary_document": docs[i],
                    "filing_date": dates[i],
                    "items": items[i] if i < len(items) else "",
                }
            )
            if len(out) >= count:
                break
    return out


def filing_doc_url(cik10: str, accession: str, primary_doc: str) -> str:
    return f"{SEC_ARCHIVE_BASE}/{int(cik10)}/{accession.replace('-', '')}/{primary_doc}"


def filing_exhibits(
    cik10: str,
    accession: str,
    user_agent: str,
    pattern: re.Pattern[str] = re.compile(r"(?i)ex(?:hibit)?[-_.]?99"),
) -> list[str]:
    """Document names in a filing's directory matching `pattern` (default: 99-series).

    The submissions feed only names the primary document; press releases live in
    exhibits (an earnings 8-K is a stub pointing at Exhibit 99.1). The directory
    listing comes from the archive's index.json.
    """
    acc_nodash = accession.replace("-", "")
    url = f"{SEC_ARCHIVE_BASE}/{int(cik10)}/{acc_nodash}/index.json"
    idx = json.loads(_http_get(url, user_agent).decode("utf-8", errors="replace"))
    names = [item.get("name", "") for item in idx.get("directory", {}).get("item", [])]
    return [
        n
        for n in names
        if pattern.search(n) and n.lower().endswith((".htm", ".html", ".txt"))
    ]


def fetch_filing_text(cik10: str, filing: dict, user_agent: str) -> str:
    url = filing_doc_url(cik10, filing["accession"], filing["primary_document"])
    raw = _http_get(url, user_agent).decode("utf-8", errors="replace")
    if filing["primary_document"].lower().endswith((".htm", ".html")):
        return html_to_text(raw)
    return raw


# ---------- orchestration ----------


def fetch_ticker(
    ticker: str,
    forms: list[str],
    count: int,
    user_agent: str,
    out_dir: Path | None = None,
) -> dict:
    out_dir = out_dir or (FILINGS_DIR / ticker.upper())
    out_dir.mkdir(parents=True, exist_ok=True)

    cik10, title = resolve_cik(ticker, user_agent)
    subs = get_submissions(cik10, user_agent)

    manifest: dict = {
        "ticker": ticker.upper(),
        "company": title,
        "cik": cik10,
        "fetched_at": datetime.now(UTC).isoformat(),
        "out_dir": str(out_dir),
        "files": [],
    }

    def _save(name: str, content: str, meta: dict) -> None:
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        manifest["files"].append({"name": name, "bytes": len(content), **meta})

    for form in forms:
        filings = recent_filings(subs, form, count if form == "8-K" else 1)
        if not filings:
            manifest["files"].append({"form": form, "status": "none_found"})
            continue

        if form == "10-K":
            f = filings[0]
            text = fetch_filing_text(cik10, f, user_agent)
            _save("latest_10K.txt", text, {"form": form, "filing_date": f["filing_date"]})
            for key, fname in (
                ("rev_rec", "latest_10K_rev_rec.txt"),
                ("critical_acct", "latest_10K_critical_acct.txt"),
                ("business", "latest_10K_business.txt"),
            ):
                sec = extract_section(text, SECTION_PATTERNS[key])
                if sec:
                    _save(
                        fname,
                        sec,
                        {"form": form, "section": key, "filing_date": f["filing_date"]},
                    )

        elif form == "10-Q":
            f = filings[0]
            text = fetch_filing_text(cik10, f, user_agent)
            _save("latest_10Q.txt", text, {"form": form, "filing_date": f["filing_date"]})
            sec = extract_section(text, SECTION_PATTERNS["rev_rec"])
            if sec:
                _save(
                    "latest_10Q_rev_rec.txt",
                    sec,
                    {"form": form, "section": "rev_rec", "filing_date": f["filing_date"]},
                )

        elif form == "8-K":
            earnings_saved = False
            for f in filings:
                text = fetch_filing_text(cik10, f, user_agent)
                acc = f["accession"].replace("-", "")
                fname = f"recent_8Ks/{f['filing_date']}_{acc}.txt"
                _save(
                    fname,
                    text,
                    {"form": form, "filing_date": f["filing_date"], "items": f.get("items", "")},
                )
                # 99-series exhibits carry the substance (press release etc.);
                # the primary document is usually just the stub pointing at them.
                exhibits: list[tuple[str, str]] = []
                try:
                    for ex_name in filing_exhibits(cik10, f["accession"], user_agent):
                        ex_url = filing_doc_url(cik10, f["accession"], ex_name)
                        ex_raw = _http_get(ex_url, user_agent).decode("utf-8", errors="replace")
                        ex_text = (
                            html_to_text(ex_raw)
                            if ex_name.lower().endswith((".htm", ".html"))
                            else ex_raw
                        )
                        ex_fname = f"recent_8Ks/{f['filing_date']}_{acc}_{ex_name}.txt"
                        _save(
                            ex_fname,
                            ex_text,
                            {
                                "form": form,
                                "filing_date": f["filing_date"],
                                "exhibit": ex_name,
                            },
                        )
                        exhibits.append((ex_name, ex_text))
                except Exception:  # missing index.json shouldn't sink the whole fetch
                    pass
                # First 8-K that looks like an earnings release (Item 2.02).
                is_earnings = "2.02" in f.get("items", "") or re.search(
                    r"(?i)results of operations|earnings", text[:4000]
                )
                if not earnings_saved and is_earnings:
                    _save(
                        "latest_earnings_8K.txt",
                        text,
                        {"form": form, "filing_date": f["filing_date"], "tag": "earnings"},
                    )
                    if exhibits:
                        _save(
                            "latest_earnings_8K_ex99.txt",
                            exhibits[0][1],
                            {
                                "form": form,
                                "filing_date": f["filing_date"],
                                "exhibit": exhibits[0][0],
                                "tag": "earnings-press-release",
                            },
                        )
                    earnings_saved = True
        else:
            f = filings[0]
            text = fetch_filing_text(cik10, f, user_agent)
            _save(
                f"latest_{form.replace('/', '_')}.txt",
                text,
                {"form": form, "filing_date": f["filing_date"]},
            )

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["status"] = "complete"
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Free SEC EDGAR filing fetcher")
    ap.add_argument("--ticker", required=True)
    ap.add_argument(
        "--forms",
        default="10-K,10-Q,8-K",
        help="Comma-separated form types to fetch (default: 10-K,10-Q,8-K)",
    )
    ap.add_argument(
        "--count",
        type=int,
        default=6,
        help="How many recent filings to pull for multi-filing forms like 8-K",
    )
    ap.add_argument(
        "--user-agent",
        default=None,
        help="SEC contact string override (or set SEC_USER_AGENT)",
    )
    ap.add_argument("--out-dir", default=None, help="Override output directory")
    args = ap.parse_args()

    forms = [f.strip() for f in args.forms.split(",") if f.strip()]
    out_dir = Path(args.out_dir) if args.out_dir else None
    try:
        ua = _user_agent(args.user_agent)
        manifest = fetch_ticker(args.ticker, forms, args.count, ua, out_dir)
    except (ValueError, RuntimeError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
