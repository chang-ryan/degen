"""
edgar_fetch.py — free SEC EDGAR filing fetcher (no API key, no paid feed).

Resolves a ticker to its CIK, lists recent filings, downloads the primary
documents for 10-K / 10-Q / 8-K, strips HTML to text, and (best-effort) carves
out the sections the earnings workflow cares about (revenue-recognition
footnote, critical accounting policies, business description, latest earnings
8-K). Everything is pulled from the public SEC endpoints:

    https://www.sec.gov/files/company_tickers.json     (ticker -> CIK)
    https://data.sec.gov/submissions/CIK##########.json (filing history)
    https://www.sec.gov/Archives/edgar/data/...          (filing documents)

SEC fair-access policy requires a descriptive User-Agent that identifies the
caller. Set one via the SEC_USER_AGENT environment variable or --user-agent,
e.g. "Jane Analyst jane@example.com". A generic default is used otherwise, but
setting a real contact string is the polite (and policy-compliant) thing to do.

Outputs land in:  workspace/{TICKER}/filings/
    latest_10K.txt, latest_10K_rev_rec.txt, latest_10K_critical_acct.txt,
    latest_10K_business.txt, latest_10Q.txt, latest_10Q_rev_rec.txt,
    latest_earnings_8K.txt, recent_8Ks/<date>_<accession>.txt, manifest.json

Usage:
    python edgar_fetch.py --ticker XYZ
    python edgar_fetch.py --ticker XYZ --forms 10-K,10-Q --count 4
    python edgar_fetch.py --ticker XYZ --user-agent "Jane Analyst jane@example.com"
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from _paths import ticker_dir

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

DEFAULT_USER_AGENT = "Earnings Analysis Agent - personal use (set SEC_USER_AGENT to your contact)"

# Section extraction schedule. Mirrors the intent of the older
# primary_source_puller PULL_SCHEDULE, but runs against downloaded text.
SECTION_PATTERNS = {
    "rev_rec": re.compile(
        r"(?i)(?:revenue\s+recognition|recognition\s+of\s+revenue|disaggregation\s+of\s+revenue)"
    ),
    "critical_acct": re.compile(r"(?i)critical\s+accounting\s+(?:policies|estimates)"),
    "business": re.compile(r"(?i)(?:item\s*1\b.*business|business\s+overview|our\s+business)"),
}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────

def _user_agent(override: str | None = None) -> str:
    return override or os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT


def _http_get(url: str, user_agent: str, *, retries: int = 3, pause: float = 0.4) -> bytes:
    """GET a URL with the SEC-required User-Agent. Retries on transient errors.

    SEC rate-limits to ~10 req/s; we pause briefly between calls to stay well
    under that for single-user use.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                time.sleep(pause)
                return raw
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}\n  {last_err}")


# ─────────────────────────────────────────────────────────────────────────────
# HTML -> text
# ─────────────────────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        if data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        # collapse runs of whitespace/newlines
        raw = re.sub(r"[ \t\xa0]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        # Malformed markup — fall back to a crude tag strip.
        return re.sub(r"<[^>]+>", " ", html)
    return p.text()


def extract_section(text: str, pattern: re.Pattern, window: int = 8000) -> str | None:
    """Return a window of text starting at the first pattern match, or None."""
    m = pattern.search(text)
    if not m:
        return None
    start = m.start()
    return text[start:start + window]


# ─────────────────────────────────────────────────────────────────────────────
# EDGAR lookups
# ─────────────────────────────────────────────────────────────────────────────

def resolve_cik(ticker: str, user_agent: str) -> tuple[str, str]:
    """Return (zero-padded 10-digit CIK, company title) for a ticker."""
    data = json.loads(_http_get(SEC_TICKERS_URL, user_agent).decode("utf-8"))
    tu = ticker.upper()
    for row in data.values():
        if str(row.get("ticker", "")).upper() == tu:
            cik = int(row["cik_str"])
            return f"{cik:010d}", row.get("title", "")
    raise ValueError(f"Ticker {ticker!r} not found in SEC company_tickers.json")


def get_submissions(cik10: str, user_agent: str) -> dict:
    url = SEC_SUBMISSIONS_URL.format(cik10=cik10)
    return json.loads(_http_get(url, user_agent).decode("utf-8"))


def recent_filings(submissions: dict, form: str, count: int) -> list[dict]:
    """Return up to `count` most-recent filings of a given form type.

    Filters on exact form match (e.g. '10-K' won't match '10-K/A').
    """
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [""] * len(forms))
    out: list[dict] = []
    for i, f in enumerate(forms):
        if f == form:
            out.append({
                "form": f,
                "accession": accs[i],
                "primary_document": docs[i],
                "filing_date": dates[i],
                "items": items[i] if i < len(items) else "",
            })
            if len(out) >= count:
                break
    return out


def filing_doc_url(cik10: str, accession: str, primary_doc: str) -> str:
    cik_int = int(cik10)
    acc_nodash = accession.replace("-", "")
    return f"{SEC_ARCHIVE_BASE}/{cik_int}/{acc_nodash}/{primary_doc}"


def fetch_filing_text(cik10: str, filing: dict, user_agent: str) -> str:
    url = filing_doc_url(cik10, filing["accession"], filing["primary_document"])
    raw = _http_get(url, user_agent).decode("utf-8", errors="replace")
    if filing["primary_document"].lower().endswith((".htm", ".html")):
        return html_to_text(raw)
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ticker(ticker: str, forms: list[str], count: int, user_agent: str,
                 out_dir: Path | None = None) -> dict:
    out_dir = out_dir or (ticker_dir(ticker) / "filings")
    out_dir.mkdir(parents=True, exist_ok=True)

    cik10, title = resolve_cik(ticker, user_agent)
    subs = get_submissions(cik10, user_agent)

    manifest = {
        "ticker": ticker.upper(),
        "company": title,
        "cik": cik10,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "out_dir": str(out_dir),
        "user_agent": user_agent,
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
            for key, fname in (("rev_rec", "latest_10K_rev_rec.txt"),
                               ("critical_acct", "latest_10K_critical_acct.txt"),
                               ("business", "latest_10K_business.txt")):
                sec = extract_section(text, SECTION_PATTERNS[key])
                if sec:
                    _save(fname, sec, {"form": form, "section": key,
                                        "filing_date": f["filing_date"]})

        elif form == "10-Q":
            f = filings[0]
            text = fetch_filing_text(cik10, f, user_agent)
            _save("latest_10Q.txt", text, {"form": form, "filing_date": f["filing_date"]})
            sec = extract_section(text, SECTION_PATTERNS["rev_rec"])
            if sec:
                _save("latest_10Q_rev_rec.txt", sec,
                      {"form": form, "section": "rev_rec", "filing_date": f["filing_date"]})

        elif form == "8-K":
            earnings_saved = False
            for f in filings:
                text = fetch_filing_text(cik10, f, user_agent)
                fname = f"recent_8Ks/{f['filing_date']}_{f['accession'].replace('-', '')}.txt"
                _save(fname, text, {"form": form, "filing_date": f["filing_date"],
                                    "items": f.get("items", "")})
                # First 8-K that looks like an earnings release (Item 2.02).
                if not earnings_saved and ("2.02" in f.get("items", "")
                                           or re.search(r"(?i)results of operations|earnings", text[:4000])):
                    _save("latest_earnings_8K.txt", text,
                          {"form": form, "filing_date": f["filing_date"], "tag": "earnings"})
                    earnings_saved = True
        else:
            f = filings[0]
            text = fetch_filing_text(cik10, f, user_agent)
            _save(f"latest_{form.replace('/', '_')}.txt", text,
                  {"form": form, "filing_date": f["filing_date"]})

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["status"] = "complete"
    return manifest


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Free SEC EDGAR filing fetcher")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--forms", default="10-K,10-Q,8-K",
                    help="Comma-separated form types to fetch (default: 10-K,10-Q,8-K)")
    ap.add_argument("--count", type=int, default=6,
                    help="How many recent filings to pull for multi-filing forms like 8-K")
    ap.add_argument("--user-agent", default=None,
                    help="SEC-required contact string, e.g. 'Jane Analyst jane@example.com'")
    ap.add_argument("--out-dir", default=None, help="Override output directory")
    ap.add_argument("--json", default=None, help="Write manifest JSON to this path too")
    args = ap.parse_args()

    ua = _user_agent(args.user_agent)
    if ua == DEFAULT_USER_AGENT:
        print("[warn] Using a generic User-Agent. SEC asks callers to identify "
              "themselves — set SEC_USER_AGENT or --user-agent to your contact.",
              file=sys.stderr)

    forms = [f.strip() for f in args.forms.split(",") if f.strip()]
    out_dir = Path(args.out_dir) if args.out_dir else None
    try:
        manifest = fetch_ticker(args.ticker, forms, args.count, ua, out_dir)
    except (ValueError, RuntimeError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    text = json.dumps(manifest, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
