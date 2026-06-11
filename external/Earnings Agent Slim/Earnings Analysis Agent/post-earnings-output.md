# Post-Earnings PDF Output Specification

## File Naming
`workspace/{TICKER}/outputs/post_{TICKER}_{EARNINGS_DATE}.pdf`
`workspace/{TICKER}/outputs/post_{TICKER}_{EARNINGS_DATE}.md`

## PDF Structure

| Section | Content |
|---------|---------|
| **Cover** | Ticker, earnings date, overall beat/miss/in-line classification, stock reaction summary (actual move, implied move, sector context) |
| **1. Executive Summary** | Classification by key metric, stock reaction vs. implied move, one-sentence thesis status. All three data points in one page. |
| **2. Line-Item Scorecard** | Table: metric / actual / consensus / beat-miss / magnitude (abs and %) / segment breakdown. Source cited for each actual. |
| **3. Language Change Log** | Three sections: (a) Changed — what shifted and direction, (b) New — topics introduced this quarter, (c) Absent — expected topics management did NOT address. Flag absent topics as signals, not neutral. |
| **4. Algorithmic Reaction Assessment** | Fundamental surprise composite across key metrics. Actual move vs. implied move. Sector ETF and market context. Disconnect flag. Narrative explaining what the market appears to be pricing. |
| **5. Thesis Status** | Pillar-by-pillar mapping (if `thesis_snapshot.md` available). Classification per pillar: confirming / neutral / threatening / ambiguous. Overall status: Green / Yellow / Red. |
| **6. Follow-Up Questions** | Prioritized list for management call. Each question includes rationale. Flag unanswered pre-earnings watch items specifically. |
| **7. Thesis Update Draft** | Staged language — clearly labeled as DRAFT, flagged as requiring user confirmation before push to `thesis_snapshot.md`. |
| **Appendix A** | Full actuals vs. estimates table, all metrics, with source citations (press release or transcript page) |
| **Appendix B** | Raw language extracts from current transcript. Cited by page and speaker. |
| **Appendix C** | Prior transcript comparisons for changed and absent language items. Side-by-side: current quarter vs. prior quarters. |

## HTML Generation
Same approach as pre-earnings. Agent writes HTML with embedded CSS, converts via weasyprint.

### Additional CSS for Post-Earnings
```css
.beat { color: #28a745; font-weight: bold; }
.miss { color: #dc3545; font-weight: bold; }
.inline { color: #6c757d; }
.absent-topic { background: #f8d7da; border-left: 4px solid #dc3545; padding: 8pt; margin: 4pt 0; }
.changed-topic { background: #d1ecf1; border-left: 4px solid #0dcaf0; padding: 8pt; margin: 4pt 0; }
.new-topic { background: #d4edda; border-left: 4px solid #28a745; padding: 8pt; margin: 4pt 0; }
.thesis-draft { border: 2px dashed #ffc107; padding: 12pt; margin: 12pt 0; background: #fffbea; }
.thesis-draft h3::before { content: "⚠️ DRAFT — "; color: #dc3545; }
.diff-current { background: #ffeef0; text-decoration: line-through; padding: 2pt 4pt; }
.diff-proposed { background: #e6ffec; padding: 2pt 4pt; }
```

### Rendering
```python
from weasyprint import HTML
HTML(string=html_content).write_pdf(output_path)
```

### Thesis Update Diff in PDF (Section 7)
The thesis update draft appears in the PDF as a styled diff using the `.thesis-draft` container:
- Each changed section shows CURRENT text (with `.diff-current` styling — red background, strikethrough) and PROPOSED text (`.diff-proposed` — green background)
- Each change includes a RATIONALE paragraph citing specific data points from the earnings analysis
- Sections with no changes are listed under "No Changes" with a brief note ("no earnings data contradicted this section")
- The diff is also written to a standalone file: `workspace/{TICKER}/outputs/thesis_draft_{DATE}.md` regardless of whether the user confirms the push

## Design Rules
1. Absent topics in Language Change Log must be explicitly derived from the pre-earnings watch list (auto-retrieved from most recent pre-earnings output in `outputs/`). Each watch item is matched using the keyword + proximity algorithm defined in `agent-logic.md` → Section 2b, subsection "Absent Topic Matching Logic". Styled with `.absent-topic` CSS class. If no pre-earnings output exists, this section notes "Pre-earnings watch list unavailable — absence detection skipped."
2. Section 4 (Algorithmic Reaction Assessment) requires `stock_reaction.json`. If absent, replace with: "⚠️ stock_reaction.json not provided. Algorithmic reaction assessment skipped." If present, include the `notes` field verbatim in the narrative.
3. Section 7 (Thesis Update Draft) is NEVER auto-committed. Rendered as a diff with commentary (see format above). Always stage and prompt: "Thesis update draft ready. Review diff above. Confirm push to thesis_snapshot.md? [y/n]"
4. The thesis update architecture is high-risk — the thesis document is the source of truth. The agent should only SUGGEST, never overwrite without confirmation.
5. Every extracted number in Appendix A must include source (press release or transcript) and page number.
