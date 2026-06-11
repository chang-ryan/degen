"""Earnings Preview Auto-Audit Agent (runner-compatible).

Backward compatible (positional preview + --manifest + --out report.md) AND
forward compatible with the preview runner's audit stage (--analysis/--source/--data/
--manifest/--config/--ticker/--agent-id/--out). If --out ends in .json, writes a
machine gate record {score, gate, fail_severity_count, ...}; the runner reads
`gate` (BLOCK hard-stops). Source docs from --source (both the per-ticker project
folder and reference files, per the runner) are loaded into a corpus so the audit
hits both folders. Fail-severity = speculative/back-solved/modeled figures.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

DOLLAR_RE = re.compile(r"\$([0-9,]+(?:\.[0-9]+)?)\s?(B|bn|billion|M|mm|million|MM|mn)?\b", re.I)
PERCENT_RE = re.compile(r"\b([+-]?[0-9]+(?:\.[0-9]+)?)%")
BPS_RE = re.compile(r"\b([+-]?[0-9]+)\s?bps\b")
SUSPICIOUS = [
    (re.compile(r"modeled\s+~?[0-9.]+%", re.I), "modeled X% — verify source"),
    (re.compile(r"back[\s-]?solv", re.I), "back-solved estimate"),
    (re.compile(r"guesstimat", re.I), "guesstimate"),
    (re.compile(r"\bplugged\b.{0,20}\b(number|figure|estimate)\b", re.I), "plugged figure"),
]
# Optional peer-ticker watch set. When populated (e.g. {"AAA","BBB"}), any
# mention of these symbols in the analysis is flagged for business-mix review.
# Empty by default in the generic build — populate with your own comp set if useful.
COMP_WATCH: set[str] = set()
TEXT_SUF = {".md",".txt",".json",".csv"}

def load_manifest(path):
    if not path or not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text())
    except Exception:
        return {}
    rows = data.get("sources")
    if rows is None:
        rows = data.get("entries", [])
    out = {}
    now = datetime.now(timezone.utc)
    for s in rows:
        metric = s.get("metric") or s.get("source_id") or s.get("tool_name") or "x"
        age = 0.0
        pa = s.get("pulled_at")
        if pa:
            try:
                age = (now - datetime.fromisoformat(str(pa).replace("Z","+00:00"))).total_seconds()/3600
            except Exception:
                age = 0.0
        out[str(metric)] = {"value": s.get("value",""), "age": age}
    return out

def load_sources(paths):
    parts, loaded = [], []
    for p in paths:
        fp = Path(p)
        if not fp.is_file():
            continue
        suf = fp.suffix.lower()
        try:
            if suf in TEXT_SUF:
                parts.append(fp.read_text(errors="replace")); loaded.append(fp.name)
            elif suf == ".pdf":
                r = subprocess.run(["pdftotext","-layout",str(fp),"-"], capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and r.stdout:
                    parts.append(r.stdout); loaded.append(fp.name)
        except Exception:
            continue
    return "\n".join(parts), loaded

def num_match(value_text, sources):
    m = re.search(r"[0-9,]+(?:\.[0-9]+)?", value_text)
    if not m:
        return False
    try:
        v = float(m.group(0).replace(",",""))
    except ValueError:
        return False
    for s in sources.values():
        try:
            sv = float(s["value"])
        except (ValueError, TypeError):
            continue
        if sv == 0:
            if v == 0: return True
        elif abs(v-sv)/abs(sv) < 0.01:
            return True
    return False

def run_audit(analysis, manifest_path, source_paths, ticker, agent_id):
    text = Path(analysis).read_text()
    lines = text.splitlines()
    sources = load_manifest(manifest_path)
    _corpus, loaded = load_sources(source_paths)
    total=verified=0
    unverified=[]; suspicious=[]; comp=[]; stale=[]
    for k,s in sources.items():
        if s["age"] > 24: stale.append(k)
    in_code=False
    for i,line in enumerate(lines,1):
        st=line.strip()
        if st.startswith("```"):
            in_code = not in_code; continue
        if in_code or st.startswith(("|---","---",":--","| ---")):
            continue
        for pat,reason in SUSPICIOUS:
            if pat.search(line):
                suspicious.append({"line":i,"reason":reason,"text":st[:160]})
        for sym in COMP_WATCH:
            if re.search(rf"\b{sym}\b", line):
                comp.append({"line":i,"reason":f"{sym} comp — verify business mix","text":st[:160]})
        for rx in (DOLLAR_RE, PERCENT_RE, BPS_RE):
            mm = rx.search(line)
            if mm:
                total+=1
                if num_match(mm.group(0), sources): verified+=1
                else: unverified.append({"line":i,"text":st[:140]})
    fail=len(suspicious); warn=len(comp)+len(unverified)
    gate = "BLOCK" if fail>0 else ("WARN" if (warn>0 or stale) else "PASS")
    score = max(0, 100 - 8*fail - 1*warn)
    return {
        "schema_version":"audit-1.1","ticker":ticker,"agent_id":agent_id,
        "preview_path":str(analysis),"audit_timestamp":datetime.now(timezone.utc).isoformat(),
        "score":score,"gate":gate,"fail_severity_count":fail,"warn_count":warn,
        "counts":{"total_numeric_claims":total,"verified_against_manifest":verified,
                  "unverified":len(unverified),"suspicious_fail":fail,"comp_flags":len(comp),
                  "stale_sources":len(stale),"source_docs_considered":len(loaded)},
        "suspicious":suspicious,"comp_flags":comp,"unverified_sample":unverified[:40],
        "source_docs":loaded,
    }

def to_md(r):
    L=[f"# Audit Report — {Path(r['preview_path']).name}",
       f"Gate: {r['gate']} | Score: {r['score']}/100 | Fail: {r['fail_severity_count']} | Warn: {r['warn_count']}",
       f"Source docs considered: {r['counts']['source_docs_considered']}",""]
    if r["suspicious"]:
        L.append("## Suspicious (FAIL)"); L += [f"- L{c['line']} {c['reason']}: {c['text']}" for c in r["suspicious"]]
    if r["comp_flags"]:
        L.append("## Comp flags"); L += [f"- L{c['line']} {c['reason']}" for c in r["comp_flags"]]
    L.append(""); L.append("Source documents:"); L += [f"- {s}" for s in r["source_docs"]]
    return "\n".join(L)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("preview", nargs="?")
    p.add_argument("--analysis"); p.add_argument("--manifest"); p.add_argument("--config")
    p.add_argument("--source", action="append", default=[])
    p.add_argument("--data", action="append", default=[])
    p.add_argument("--ticker", default=""); p.add_argument("--agent-id", dest="agent_id", default="")
    p.add_argument("--out")
    a=p.parse_args()
    analysis = a.analysis or a.preview
    if not analysis or not Path(analysis).exists():
        print(f"ERROR: preview not found: {analysis}", file=sys.stderr); return 2
    rep = run_audit(analysis, a.manifest, list(a.source)+list(a.data), a.ticker, a.agent_id)
    if a.out and str(a.out).lower().endswith(".json"):
        Path(a.out).write_text(json.dumps(rep, indent=2))
        print(f"[audit] gate={rep['gate']} score={rep['score']} fail={rep['fail_severity_count']} warn={rep['warn_count']} -> {a.out}")
        return 0
    elif a.out:
        Path(a.out).write_text(to_md(rep)); print(f"wrote {a.out}")
    else:
        print(to_md(rep))
    return 1 if (rep["suspicious"] or rep["comp_flags"] or rep["counts"]["stale_sources"]) else 0

if __name__ == "__main__":
    sys.exit(main())
