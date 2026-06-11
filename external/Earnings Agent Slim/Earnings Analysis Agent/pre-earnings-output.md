# Pre-Earnings PDF Output Specification

## File Naming
`workspace/{TICKER}/outputs/pre_{TICKER}_{EARNINGS_DATE}.pdf`
`workspace/{TICKER}/outputs/pre_{TICKER}_{EARNINGS_DATE}.md`

## PDF Structure

| Section | Content |
|---------|---------|
| **Cover** | Ticker, company name, earnings date, report time (BMO/AMC), run date, consensus as-of date |
| **1. Executive Summary** | 1-page: expectations narrative in 5–7 lines, top 2 debates, one-sentence thesis status (if `thesis_snapshot.md` available), top 3 watch items |
| **2. Expectations Stack** | Table: metric / consensus mean / consensus range / last guidance / implied bar assessment / staleness flag / N_estimates |
| **3. Key Debates** | 3–5 debates. For each: debate statement, bull read, bear read, thesis relevance |
| **4. What to Watch** | Language triggers by topic: (a) affirmative language triggers, (b) risk triggers, (c) omission flags. Plus: narrative watch, topic-specific watch items derived from prior transcripts |
| **5. KPI Sensitivity Table** | For each primary metric: Bear/Base/Bull values. Implied stock reaction range per scenario. What's priced in assessment. |
| **6. Positioning Context** | Whisper delta (if provided), short interest (if provided), options skew / implied move (if provided). Flag what's missing. |
| **Appendix A** | Full consensus data with source, entry timestamp, N_estimates for all metrics |
| **Appendix B** | Guidance history by metric (last 6 quarters). Track record: beat / in-line / miss count. |
| **Appendix C** | Prior transcript language excerpts supporting watch list items. Cited by quarter. |

## KPI Sensitivity Table — Scenario Value Sourcing
Bear/Base/Bull values are derived as follows (not user-provided):
1. **Base case**: Consensus mean from `consensus.csv`
2. **Bull case**: Consensus high estimate. If consensus high is within 1% of mean (tight range), use `mean * 1.03` as bull case and flag: "Consensus range tight — bull scenario uses +3% above mean as proxy."
3. **Bear case**: Consensus low estimate. If consensus low is within 1% of mean, use `mean * 0.97` and flag similarly.
4. **Stock reaction scenarios**: If `stock_reaction.json` has 4+ prior quarters of data, calculate the historical median stock move for beats vs. misses of comparable magnitude. If fewer than 4 quarters, note: "Insufficient history for reaction estimate — N={count} quarters available."
5. **"What's priced in" assessment**: Compare current stock price momentum (from `stock_reaction.json` most recent entry's pre-close vs. 30-day prior close, if available) to the consensus revision trend. If stock has moved significantly while consensus is flat, note potential disconnect.

## HTML Generation
The agent generates the PDF by first writing an HTML document, then converting via weasyprint.

### HTML Template Approach
The agent constructs a single HTML file with embedded CSS. Structure:
```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @page { size: letter; margin: 1in 0.75in; }
    body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10pt; color: #1a1a1a; line-height: 1.4; }
    h1 { font-size: 16pt; border-bottom: 2px solid #2c3e50; padding-bottom: 4pt; }
    h2 { font-size: 13pt; color: #2c3e50; margin-top: 18pt; }
    h3 { font-size: 11pt; color: #34495e; }
    table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
    th { background: #2c3e50; color: white; padding: 6pt 8pt; text-align: left; font-size: 9pt; }
    td { padding: 5pt 8pt; border-bottom: 1px solid #ddd; font-size: 9pt; }
    tr:nth-child(even) { background: #f8f9fa; }
    .warning { background: #fff3cd; border-left: 4px solid #ffc107; padding: 8pt; margin: 8pt 0; font-size: 9pt; }
    .flag-stale { color: #dc3545; font-weight: bold; }
    .flag-thin { color: #fd7e14; }
    .cover { text-align: center; padding: 40pt 0; page-break-after: always; }
    .exec-summary { page-break-after: always; }
    .appendix { page-break-before: always; }
    .citation { font-size: 8pt; color: #6c757d; }
  </style>
</head>
<body>
  <!-- Cover page -->
  <div class="cover">
    <h1>{TICKER} — Pre-Earnings Preparation</h1>
    <p>Earnings Date: {DATE} | Report Time: {BMO/AMC}</p>
    <p>Consensus As-Of: {AS_OF_DATE} | Run Date: {RUN_DATE}</p>
  </div>

  <!-- Section 1: Executive Summary -->
  <div class="exec-summary">
    <h2>1. Executive Summary</h2>
    <!-- 5-7 line narrative, top 2 debates, thesis status, top 3 watch items -->
  </div>

  <!-- Section 2: Expectations Stack -->
  <h2>2. Expectations Stack</h2>
  <table>
    <tr><th>Metric</th><th>Consensus Mean</th><th>Range (Low-High)</th><th>Last Guidance</th><th>Implied Bar</th><th>N Est.</th><th>Flags</th></tr>
    <!-- One row per metric -->
  </table>

  <!-- Sections 3-6 follow same pattern -->
  <!-- Appendices A, B, C with class="appendix" for page breaks -->
</body>
</html>
```

### Rendering
```python
from weasyprint import HTML
HTML(string=html_content).write_pdf(output_path)
```

## Design Rules
1. Executive Summary is one page — not a contents page. You should be able to action off it alone.
2. Every number in the Expectations Stack must include N_estimates and the staleness flag.
3. The "What to Watch" section must be derived from prior transcript analysis — not generic language. The agent should populate this from actual language patterns in prior 8 quarters.
4. KPI Sensitivity Table must include explicit stock reaction scenarios where prior `stock_reaction.json` data is available. Scenario values are derived from consensus range per the sourcing rules above.
5. Flag all missing inputs at top of document before Section 1 using the `.warning` CSS class.
