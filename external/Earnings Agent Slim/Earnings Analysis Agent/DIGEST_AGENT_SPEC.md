# Earnings Digest Agent — Generalized Workflow Spec

**Purpose:** Generalized spec for producing rapid post-print earnings digests on ANY ticker, paired with a transcript-integrated update. Use a generic ticker `XYZ` as the worked baseline. Defines two stages — Stage 1 (post-print, pre-call) and Stage 2 (transcript-integrated, post-call).

**Status:** Canonical template. Supersedes the legacy `post-earnings-output.md`. Maintains the architectural slot but expands Stage 2's spec from "≤500 words 1-pager" to "full post-print analysis".

**Relationship to 4-stage-architecture.md:** This document defines Stages 2 (Rapid Digest) and 3 (Recap 1) of the four-stage flow. The user-facing language is "Stage 1 of the digest" (= architecture Stage 2) and "Stage 2 of the digest" (= architecture Stage 3).

---

## 1. Operating Modes

The digest agent runs in one of two stages, sequentially, with the same ticker.

### Digest Stage 1 — Post-Print, Pre-Call

Trigger: you type `digest [TICKER] print` after seeing the headline cross. Manual trigger only — there is no polling loop for intraday filing timestamps.

Goal: a full post-print analysis (~5-8 page PDF) covering beat/miss vs expectations, narrative read, guide deltas, implied estimate moves, questions to listen for on the call, and tactical lens. Auto-loads the most recent preview output as the spine for the comparison.

Latency target: ~10-15 minutes from trigger to PDF delivered. Faster than the preview build because the baseline is pre-loaded; slower than a 1-pager because the analysis is full-depth.

### Digest Stage 2 — Transcript-Integrated, Post-Call

Trigger: you drop the earnings call transcript into `workspace/{TICKER}/transcripts/` (filename pattern `{TICKER}_{period}_transcript.txt`) and type `digest [TICKER] transcript` (or `recap [TICKER] call` per the 4-stage trigger).

Goal: a separate document (`digest_v2_transcript.{md,pdf}`) that calls out **deltas** vs Stage 1 — what the Q&A added, what management dodged, narrative shifts in prepared remarks vs the press release, updated tactical view. Stage 1's document is preserved unmodified as the algorithmic / pre-call read.

Latency target: 20-30 minutes from transcript drop to PDF.

---

## 2. Workflow — Stage 1 (Post-Print)

```
TRIGGER: "digest [TICKER] print"
   ↓
[1] LOAD BASELINE
   - **MANDATORY: locate the most recent preview output** at
     workspace/{TICKER}/outputs/
   - Parse the latest preview markdown. Extract the 3 KPI tables
     (current Q, Q+1, current FY): metric / guide / variant /
     y/y / cons / y/y / Δ vs cons.
   - Load the latest stage1_prep_*.json if present (structured baseline).
   - Load consensus.csv (cons numbers, as_of date).
   - Load key_metrics.yaml (metric definitions).
   - Load positioning.json if present (SI, implied move, surprise→price correlation,
     historical reaction asymmetry — all OPTIONAL; stub if absent).
   - Load /guidance/ folder (most recent guide, prior 6Q guides for context).
   - Build digest_baseline.json — single source of truth for what was
     expected going into the print.
   - **HALT if the baseline cannot be assembled.** A digest with no baseline
     is just a press release summary, not a beat/miss analysis.
   ↓
[2] PULL POST-PRINT MATERIALS
   - **SEC EDGAR (free):**
     a. Run `python scripts/edgar_fetch.py --ticker {TICKER}` to pull the latest 8-K.
     b. Filter to the earnings 8-K (Item 2.02 — Results of Operations and Financial Condition).
     c. Extract Exhibit 99.1 (press release text), Exhibit 99.2 (slide deck
        text if filed — many companies do not), Exhibit 99.3 (prepared
        remarks if filed).
   - **IR website fallback (for tickers that file deck only on IR site):**
     a. Fetch the company's IR press releases page or earnings page
        (the `ir_deck_url` field in config.yaml).
     b. Look for the latest deck PDF. Download via WebFetch.
   - **Save raw materials** to
     workspace/{TICKER}/print_materials/{period}/
     - press_release.txt (verbatim)
     - earnings_deck.pdf (if available)
     - prepared_remarks.txt (if available)
     - source_manifest.json (URL, fetch timestamp, file size, hash)
   ↓
[3] EXTRACT NUMERICAL ACTUALS
   - Parse the press release + deck for headline numbers:
     - Total revenue (Q + segment splits)
     - Gross margin (GAAP + non-GAAP if disclosed)
     - Operating margin / EBIT (GAAP + non-GAAP)
     - EPS (diluted, GAAP + non-GAAP)
     - Unit KPIs per key_metrics.yaml (cases, scanners, members, etc.)
     - Cash flow / FCF if disclosed
     - Share count
   - Parse guidance:
     - Next Q guide (range or point) — rev, EPS, GM, OM if disclosed
     - FY guide (range or point) — same
     - Compare to prior guide (from /guidance/ folder)
   - **Every extracted number records a citation:** raw quote + character
     offset within press_release.txt. Used by the audit gate.
   - Output: actuals.json — keyed by metric, with value, period, citation,
     unit, gaap_or_non_gaap flag.
   ↓
[3a] AUDIT GATE 1 — Post-Extraction (HALTS if fails)
   - Verify every key_metrics.yaml metric is present in actuals.json
     OR explicitly flagged "not disclosed in press release" with reason.
   - Verify each extracted number has a non-empty citation.
   - Verify gaap_or_non_gaap is set for every margin / earnings number.
   - Cross-check obvious arithmetic: rev × GM = GP (within rounding);
     GP - opex = OI; etc. Flag inconsistencies.
   - If gate fails: return to [3] and re-extract before computing deltas.
   ↓
[4] COMPUTE BEAT/MISS + GUIDE DELTAS
   - For each metric in expectations stack:
     - Δ_actual_vs_cons = (actual - cons) / cons
     - Δ_actual_vs_variant = (actual - variant) / variant
     - Δ_actual_vs_guide_low / vs_guide_high (if guide was a range)
     - Classification: beat / in-line / miss
       - In-line band: ±0.5% on rev, ±50bps on margin, ±2% on EPS — scaled
         per metric. Defined in key_metrics.yaml under in_line_threshold.
   - For each guide line:
     - Δ_guide_vs_prior_guide
     - Δ_guide_vs_prior_cons
     - Direction: raised / reaffirmed / lowered
     - Magnitude: bps / % / $
   - **Implied estimate move** (directional only, no draft numbers):
     - For each forward period (Q+1, FY): given actual + new guide,
       which way does cons need to move and roughly how much?
     - Output: 1-2 sentences per period.
   - Output: scorecard.json — feeds the markdown template.
   ↓
[4a] AUDIT GATE 2 — Mid-Draft (HALTS if fails)
   - After scorecard.json is built but before narrative drafted:
     - Every cons number used in the delta computation matches an entry
       in digest_baseline.json (no fabricated cons figures).
     - Every guide_vs_prior_guide computation has a prior-guide source
       cited in /guidance/ folder.
     - In-line / beat / miss classifications match the threshold rules
       in key_metrics.yaml.
   - If gate fails: fix the numerical core BEFORE drafting narrative.
   ↓
[5] DRAFT DIGEST (section by section, audit between sections)
   - Use canonical template (see §4).
   - Match your prior preview voice — pull style cues from the
     baseline preview's prose.
   - Triangulate actuals vs cons vs your variant vs guide; surface
     disagreements; don't bury them.
   - Tactical lens lives both up-top (action: HOLD/ADD/TRIM/EXIT
     + sizing) and in the appendix (full quantamental view).
   - Where the print contradicts the preview's variant, call it out by
     name: "Variant called for X, print delivered Y, gap is Z."
   ↓
[6] FINAL AUDIT — Pre-Render (HALTS if fails)
   - Run audit_agent.py against complete draft (digest mode).
   - Every figure in the body has a citation traceable to actuals.json
     or digest_baseline.json.
   - No fabricated cons or variant numbers.
   - Implied estimate move statements are directional, not numerical
     (flag direction + magnitude only, do not draft new variant estimates).
   - Pandoc render-time check: --from markdown-tex_math_dollars flag
     used (avoid the $ math bug that swallows table rows).
   ↓
[7] DELIVER
   - Markdown source to workspace/{TICKER}/outputs/
     filename: digest_v1_print_{period}_{YYYYMMDD}.md
   - PDF rendered via pandoc → weasyprint
     filename: digest_v1_print_{period}_{YYYYMMDD}.pdf
   - Audit report alongside as digest_v1_print_{period}_{YYYYMMDD}_audit.json
   - Provide computer:// link for PDF
   - **Emit chat-only run-on TLDR** alongside the PDF link. Format: 60-100 words,
     semicolon-separated hits, data-rich (specific numbers > framing words).
     NOT embedded in the PDF. Renderer prints a soft reminder; drafting agent
     generates and delivers.
```

---

## 3. Workflow — Stage 2 (Transcript-Integrated)

```
TRIGGER: "digest [TICKER] transcript" (after transcript file dropped)
   ↓
[1] LOAD STAGE 1 + TRANSCRIPT
   - Load digest_v1_print_*.md and digest_v1_print_*.json (the Stage 1 read).
   - Load transcript file from /transcripts/{period}_transcript.txt
   - Parse transcript into prepared remarks vs Q&A sections.
   - Identify each Q&A exchange: questioner / questioner_firm /
     management_responder / question_text / answer_text.
   ↓
[2] EXTRACT INCREMENTAL DISCLOSURES
   - For each metric in expectations stack:
     - Did management quantify anything in prepared remarks not in the PR?
     - Did Q&A reveal additional color (sub-segment KPIs, regional
       breakdowns, mix shifts, ASP commentary)?
   - For each guide line:
     - Did management add color on the assumptions behind the guide?
     - Did they walk back any guidance commentary from the press release?
   - For each watch list item from the preview:
     - Was it addressed? In prepared remarks or only in Q&A response?
     - If addressed, what direction (confirms / threatens / neutral)?
     - If NOT addressed, log as conspicuous omission.
   - For each Q&A exchange:
     - Tag question type (volume / margin / guide / capital allocation /
       competitive / strategic / model)
     - Tag answer quality (substantive / hedged / dodged / refused)
     - Flag exchanges where management was conspicuously brief or
       redirected.
   ↓
[3] LANGUAGE CHANGE DETECTION
   - Compare prepared remarks to last 2 transcripts (from /transcripts/).
   - Topics CHANGED: shifted in tone or substance.
   - Topics NEW: introduced this quarter.
   - Topics ABSENT: discussed last quarter, not this quarter.
   - Tag each language change with a one-line interpretation.
   ↓
[4] COMPUTE STAGE 1 DELTAS
   - For each section of digest_v1:
     - Did Q&A confirm, modify, or contradict the Stage 1 read?
     - If contradicted, what's the new view?
   - For the action recommendation (HOLD/ADD/TRIM/EXIT):
     - Did anything in the call change the recommendation?
     - If yes: state the new action and the trigger.
   ↓
[4a] AUDIT GATE — Mid-Draft (HALTS if fails)
   - Every Q&A excerpt cited has a matching transcript line + speaker
     attribution.
   - Every "language changed" claim has a prior-quarter quote for
     comparison.
   - Every "absent topic" claim is verified against actual transcript
     text (not just prepared remarks).
   ↓
[5] DRAFT STAGE 2 DIGEST
   - Use Stage 2 template (see §4 — same as Stage 1 plus delta sections).
   - Lead with what changed vs Stage 1, not a re-statement of Stage 1.
   - Q&A highlights table: top 5 exchanges that mattered.
   - Updated tactical lens: any new asymmetry visible from the call.
   ↓
[6] FINAL AUDIT — Pre-Render
   - Same audit_agent.py pass as Stage 1.
   - Plus: Stage 2 explicitly references Stage 1 deltas, doesn't restate.
   ↓
[7] DELIVER
   - filename: digest_v2_transcript_{period}_{YYYYMMDD}.{md,pdf}
   - Audit report alongside
   - **Emit chat-only run-on TLDR** alongside the PDF link. Stage 2 TLDR should be
     call-delta-oriented: thesis state delta vs Stage 1, key call disclosure that
     shifted the math, updated landing zone, action posture, conviction tier, next
     conviction test. NOT embedded in the PDF.
```

---

## 4. Canonical Output Template

### Formatting rules (REQUIRED)

1. **Decision header table:** use the HTML `<table class="decision-table">` syntax from `digest_skeleton_adaptive.md`, NOT markdown table syntax. The CSS `.decision-table` class gives full width with bold left column. Markdown tables get auto-narrowed by the legacy `table:first-of-type { width: 60% }` rule.
2. **Decision-table cells must be ONE LINE.** Long-form rationale (multi-sentence "why") goes in Synthesis paragraphs, NOT in table cells. Verbose cells force tall narrow columns and push subsequent content to next page.
3. **Pandoc invocation:** always pass `--from markdown-tex_math_dollars` (avoids the $-math bug). Title metadata extracted from markdown H1 (handled by `render_digest.py` automatically).
4. **`page-break-inside: auto` on tables** (current CSS). Tables can span page breaks; do NOT mark important tables as `avoid` unless they're <10 rows AND fit on a single page comfortably.
5. **Post-render audit:** `render_digest.py` automatically runs `_post_render_audit()` after weasyprint, flagging pages with <40% of avg character density (likely empty page) or >1 sparse page. Address warnings before delivering.
6. **Versioned filenames default:** `_v1.pdf`, `_v2.pdf`, `_v3.pdf` ... auto-incremented. Avoids `PermissionError` if a previous PDF is open.


### 4.0 Adaptive Content Driver: `salient_kpis` Schema (REQUIRED, added 2026-04-30)

**Why this section exists:** The digest TEMPLATE (sections, ordering, tables, color classes) is universal. The CONTENT (which KPIs populate the scorecard, which paragraphs comprise the Synthesis, which questions live in the Watch-List ABSENT block) is **company-specific** and MUST adapt per ticker. Without an adaptation mechanism, every digest defaults to whichever ticker was used as the most recent template (e.g., one company's volumes/ASP/units language being misapplied to a different company's instrument-placements / consumables / OM context). That is a structural error.

**Mechanism:** Each ticker's preview AND `config.yaml` declares a `salient_kpis` block. The digest agent reads this block and binds it to specific sections of the template. The template stays universal; the bindings make it ticker-specific.

#### `salient_kpis` schema

Declared in `config.yaml` as the default; overridden by the cycle-specific preview if a current preview narrows or shifts the focus.

```yaml
salient_kpis:
  # 3-6 entries, in priority order (first = most decision-relevant)
  - name: <snake_case_metric_id>            # binds to scorecard row + synthesis para
    label: "<Display Label>"                 # human-readable, used in tables
    why: "<one sentence: why this matters for THIS company's thesis>"
    direction: higher_better | lower_better | neutral
    source_tier: <where to pull from at print time>
      # e.g. "deck_or_pr_table_3" | "deck_only" | "pr_only" | "transcript_only" | "10q_only"
    composition_relevance: "<what makes a beat in this metric REAL vs. cosmetic>"
      # e.g. "Cases beat must show breadth across cohorts AND channels"
      # e.g. "OM beat must decompose to GM + opex, not below-the-line tax/FX"
    
day_of_binary:
  primary: "<the SINGLE metric the tape will trade off of>"
    # MUST come from preview's 'What metrics matter' / analyst confirmation
    # Do NOT default to rev/EPS unless preview explicitly says so
  composition_test: "<what makes the day-of binary outcome REAL>"
    # e.g. "rev beat must be organic product, not M&A or service-driven"

conditional_sections:
  include_cash_flow_walk: true | false
    # true if: preview flagged cash quality as a watch item, OR
    #          actual cash conversion is anomalous (low/weird), OR
    #          major balance-sheet event happened (acquisition close, refinancing, large buyback)
    # false if: cash conversion is clean, no balance-sheet event
  include_pair_view_extended: true | false
    # true if: a specific pair trade is part of the working thesis
    # false if: long-only or no active pair leg
  include_squeeze_detail: true | false
    # true if: SI > 8% float OR DTC > 7 OR squeeze score > 50
    # false if: low SI / low squeeze metrics

absent_from_pr_template_questions:
  # Pulled from preview's "What we will be listening for" intersected with
  # what the PR did NOT address. Becomes the ABSENT block of Watch-List Recon.
  - "<Specific call question 1>"
  - "<Specific call question 2>"
```

#### How the schema binds to the template

| Template section | What it gets from `salient_kpis` |
|---|---|
| Synthesis (multi-paragraph) | Story para always present. Then ONE paragraph per top 3-4 salient_kpis (in priority order). NOT a generic "Volumes / ASP / Margin / Capital" set — the paragraphs are NAMED by the salient_kpis. |
| Day-of-binary line | Anchored to `day_of_binary.primary` + `day_of_binary.composition_test`. |
| Guide Delta table | Rows = each guidance metric the company actually issues. NOT preset to rev/OM/EPS — if mgmt issues guide on volumes/cases/MLR/comps, those rows appear too. |
| Beat/Miss Scorecard | Rows = each `salient_kpis` entry, in priority order. Standard rows (Total Revenue, Non-GAAP OM, Non-GAAP EPS) appear if they're salient OR if they're foundational; otherwise the salient_kpis list IS the scorecard. |
| Cash Flow Walk | Included only if `conditional_sections.include_cash_flow_walk == true`. |
| Watch-List ABSENT block | Items = `absent_from_pr_template_questions`. Each becomes a numbered call question. |
| Tactical Lens | Sizing math (universal). Idio alpha + pair view only if active. Squeeze detail only if `include_squeeze_detail == true`. |
| Appendix A Reactions | Always present (last 5 prints + this print). |
| Appendix B Visibility Cues | Always present (PR-specific language analysis). |

#### Worked examples

**Volume-driven hardware/consumer name** (demand-driven, OM rebuild story):
```yaml
salient_kpis:
  - {name: units_shipped, label: "Units Shipped (K)", why: "Volume is the day-of binary; the tape trades off unit count first", direction: higher_better, source_tier: pr_table, composition_relevance: "Units beat needs breadth: cohort + channel + region"}
  - {name: asp, label: "ASP", why: "ASP trajectory tied to TC-01 / TC-02 thesis claims", direction: higher_better, source_tier: deck_or_10q, composition_relevance: "ASP improvement must be driven by mix or geography, not one-time accruals"}
  - {name: nongaap_om, label: "Non-GAAP Operating Margin", why: "Multi-year OM rebuild; +100bps language is the FY guide anchor", direction: higher_better, source_tier: deck_or_pr_table_3, composition_relevance: "OM beat decomposes to GM + opex; below-the-line tax/FX wins are quality-flagged"}
  - {name: international_growth, label: "International Volume Growth", why: "Variant thesis requires ≥4 DD quarters over 8q horizon", direction: higher_better, source_tier: pr_supplemental, composition_relevance: "Each region (EMEA/APAC/LATAM) contribution"}
day_of_binary:
  primary: "Units Shipped"
  composition_test: "Volume beat must show cohort + channel + regional breadth, not single-region one-off"
conditional_sections:
  include_cash_flow_walk: true   # legal settlement + restructuring tail = cash quality watch
  include_pair_view_extended: true  # active pair vs a direct competitor
  include_squeeze_detail: false   # SI ~5.5% / DTC ~4 = low
```

**Instrument + consumables name** (placements story, OM, M&A overlay):
```yaml
salient_kpis:
  - {name: nongaap_operating_margin, label: "Non-GAAP Operating Margin", why: "Multi-year cost-out thesis; 2H ramp confidence is the OM-line binary", direction: higher_better, source_tier: deck_or_pr_table_3, composition_relevance: "OM beat must decompose to GM + opex, not below-the-line tax adjustment"}
  - {name: row_organic_growth, label: "ROW Organic Revenue Growth", why: "Composition test: beat must be organic, not M&A/FX", direction: higher_better, source_tier: pr_table_1, composition_relevance: "Organic ex-China is the cleanest read on demand"}
  - {name: instrument_placements, label: "Instrument Placements (qtr)", why: "Install base growth → consumables ramp; cadence guide", direction: higher_better, source_tier: deck_or_call, composition_relevance: "Mix of clinical vs research placements"}
  - {name: consumables_revenue, label: "Consumables Rev", why: "Recurring revenue line; platform transition near complete", direction: higher_better, source_tier: deck_only, composition_relevance: "Clinical vs research split"}
day_of_binary:
  primary: "Next-Q/FY guide on core product rev"
  composition_test: "Beat must be organic product revenue, NOT M&A or service-driven"
conditional_sections:
  include_cash_flow_walk: true   # recent acquisition close = balance-sheet event
  include_pair_view_extended: true  # active pair vs a competitor on technology displacement
  include_squeeze_detail: false   # squeeze metrics low
absent_from_pr_template_questions:
  - "Next-Q specific guide bands"
  - "Consumables clinical vs research split"
  - "Instrument Q1 placement count + clinical/research mix"
  - "China revenue Q1 actual + update"
  - "2H OM bridge components"
  - "Buyback execution pace"
  - "Strategic investment loss explanation"
  - "Acquisition integration milestones + synergy plan"
  - "Competitive read on new entrant"
```

**Subscriber-driven DTC name** (GLP-1 sensitivity):
```yaml
salient_kpis:
  - {name: subscribers_total, label: "Total Subscribers (K)", why: "Subscriber count is the demand truth; revenue follows", direction: higher_better, source_tier: pr_table, composition_relevance: "Net adds breakdown: GLP-1 vs core; subscription vs one-time"}
  - {name: aov_per_subscriber, label: "AOV per Subscriber", why: "ARPU x sub count = rev decomposition", direction: higher_better, source_tier: pr_table, composition_relevance: "AOV mix shift toward GLP-1 vs core treatments"}
  - {name: adj_ebitda_margin, label: "Adj EBITDA Margin", why: "Marketing leverage thesis; mgmt issues margin guide", direction: higher_better, source_tier: pr_table, composition_relevance: "Margin expansion must be from marketing % rev decline, not opex defer"}
  - {name: marketing_pct_revenue, label: "Marketing % of Revenue", why: "Direct read on customer acquisition efficiency", direction: lower_better, source_tier: 10q, composition_relevance: "Mktg leverage = real if subs grow; unsustainable if subs flat"}
day_of_binary:
  primary: "Subscriber net adds (or ARPU if subs in line)"
  composition_test: "Sub growth quality: subscription vs one-time; GLP-1 retention rate"
conditional_sections:
  include_cash_flow_walk: false   # clean cash conversion typically
  include_pair_view_extended: false  # long-only, no active pair
  include_squeeze_detail: true   # historical SI elevation makes squeeze relevant
```

**Health insurer name** (MLR-driven):
```yaml
salient_kpis:
  - {name: medical_loss_ratio, label: "Medical Loss Ratio (MLR)", why: "MLR IS the profitability metric for insurers; everything else is downstream", direction: lower_better, source_tier: pr_table, composition_relevance: "MLR beat must hold across membership cohorts; reserve adjustments are quality flags"}
  - {name: effectuated_members, label: "Effectuated Members", why: "Membership trajectory drives premium; net of churn is the truth", direction: higher_better, source_tier: pr_table, composition_relevance: "Effectuated vs gross enrolled; churn rate"}
  - {name: total_premium_revenue, label: "Premium Revenue", why: "Member × PMPM; foundational top line", direction: higher_better, source_tier: pr_table, composition_relevance: "PMPM mix vs member mix decomposition"}
  - {name: adj_ebitda_margin, label: "Adj EBITDA Margin", why: "Profitability inflection is the multi-year story", direction: higher_better, source_tier: pr_table, composition_relevance: "Operating leverage on premium growth, not investment income"}
day_of_binary:
  primary: "MLR (medical loss ratio)"
  composition_test: "MLR beat must NOT be reserve-release-driven; must reflect underlying utilization"
conditional_sections:
  include_cash_flow_walk: false   # insurers cash conversion noisy by design; not the day-of issue
  include_pair_view_extended: false
  include_squeeze_detail: false
```

#### Audit gate — salient_kpis conformance (added to baseline_audit.py spec, deferred build)

```
For each salient_kpi in preview/config:
  ASSERT: appears as a row in Beat/Miss Scorecard
  ASSERT: appears as a paragraph anchor in Synthesis (top 3-4 only)
  ASSERT: appears in Watch-List ADDRESSED or PARTIAL or ABSENT
  
For day_of_binary.primary:
  ASSERT: appears as the FIRST sentence or first half of Synthesis paragraph 1
  ASSERT: composition_test language appears verbatim in the Beat Composition discussion

For conditional_sections.include_cash_flow_walk == true:
  ASSERT: Cash Flow Walk section is present
For conditional_sections.include_cash_flow_walk == false:
  ASSERT: Cash Flow Walk section is NOT present (saves real estate)

For each item in absent_from_pr_template_questions:
  ASSERT: appears as a numbered question in Watch-List ABSENT block
```

#### Pre-flight rule (memory-enforced)

Before drafting any digest, the agent MUST:
1. Read the latest preview's "What metrics are most important" + "What we will be listening for" sections
2. Read `config.yaml`'s `salient_kpis` block
3. If preview overrides config, preview wins (it's cycle-specific)
4. Scaffold the digest from the resolved `salient_kpis` BEFORE writing any content
5. Verify scaffold has the right number of synthesis paragraphs, scorecard rows, watch-list questions

This pre-flight is mandatory before drafting any digest.

---

### Stage 1 — Post-Print Digest

**Section ordering (locked):** stocks move on the guide, so the guide-driven verdict goes first. Scorecard and supporting detail follow.

**Decision header (HTML `<table class="decision-table">`):** four rows, each ONE line. Long rationale lives in Synthesis, not in cells.

```
# {Company} — {Quarter} Print Digest
{Print metadata: report time, last close, since-prior-print return, implied move}

| Recommended Action | {HOLD / ADD / TRIM / EXIT + 1-line rationale} |
| Headline Read | {1-line: "Beat on rev/cases, miss on GM, guide raised"} |
| Day-of-Trade Triggers | {1-line: what the tape is likely to do at the open} |
| Preferred Structure | {1-line: short call spread / put spread / outright + tenor + strikes} |
```

**Header rows that are PROHIBITED in the digest output (production_ready_check halts the build if present):**
- "Pre-Print Decision (from preview)" — preview-output field, not appropriate for post-print circulation
- "Earnings Preview Score" — preview-output field
- "Recommended Position Size (from preview)" — preview-output field; if the digest carries a size delta, name the size directly without referring to the preview
- Any named-author label — use "Recommended Action"

The pre-print decision, preview score, and recommended size live in the preview output deliverable and in `digest_baseline.json` as internal scaffolding. They are not reproduced in the circulation digest.

### Bias Pre-Commitment — INTERNAL PRE-FLIGHT ARTIFACT (not in deliverable)

Bias pre-commitment is a useful PRE-DRAFT discipline but it is INTERNAL SCAFFOLDING. It must NOT appear in the rendered digest. Write the pre-commitment to `synthesis/bias_pre_commitment_{period}.md` (or directly into `digest_baseline.json` under a `bias_pre_commitment` key) before extracting actuals. Reference it during drafting; do not echo it into the deliverable.

The deterministic `production_ready_check.py` gate halts the render if any of these strings reach final markdown:
- "Bias Pre-Commitment" (as a section header)
- "Going in I'm leaning…" / "I'm at risk of (confirmation / anchoring / recency) bias"
- "Pre-commit horizon" / "post-hoc rewrites of this section are forbidden"
- "Post-extraction audit of pre-commitment"

**Why this is now internal-only:** pre-commitment is a meta-process discipline, valuable for the agent drafting the doc but distracting in the circulation deliverable. The desk reads the conclusion, not the process journal.

### Evidence Classification Tags (REQUIRED)

Every consequential claim in Stage 1 + Stage 2 carries one of three inline tags:
- `[STATED]` — directly in the press release / 10-Q / transcript / other primary source
- `[INFERRED]` — derived from primary source data through calculation or pattern recognition (the math is shown via Calculation Persistence)
- `[SPECULATIVE]` — requires additional data to confirm (e.g., "if mgmt attributes X to non-recurring catalysts, durability premium reduces" is speculative until the call)

Tags are inline at the end of the relevant clause/sentence, in italics (e.g., *[INFERRED]*). Apply selectively to consequential claims, not exhaustively to every sentence.

### Calculation Persistence (REQUIRED)

For every consequential number (the 3-5 numbers driving the take), show:
- **Inputs** (with sources)
- **Formula**
- **Result**

Inline within the prose where the number first appears, OR in a footnote reference. The discipline catches errors that consistency-checks miss because it forces you to walk the math. Principle: for every consequential number in the output, show inputs (with sources), formula, and result.

### Synthesis — Day-of-Trade Verdict

Single paragraph (3-5 sentences) + day-of-binary line + uncertainty list. Required components:

**(a) Day-of-binary line** — first sentence or first half of the paragraph MUST name the SPECIFIC trigger metric that drives the day-of price reaction for THIS ticker. The day-of binary is NOT always the same as what's analytically interesting. Anchor to the preview's "What metrics are most important for the print" section. Examples:
- Volume-driven hardware/consumer: **volumes** (units shipped, key cohort) — the tape trades off this number first. NOT margin / NOT EPS.
- High-multiple SaaS: **NRR + RPO** + guide direction
- Health insurer / MCO: **MLR**
- Consumer discretionary: **comp store sales**
- Semis: **next-Q rev guide**

If the day-of binary is unclear from the preview, FLAG it explicitly rather than guess. Do NOT default to "rev/EPS" if the preview identified something different.

**(b) Synthesis — multi-paragraph, narrative-led.** Format = 3-4 short paragraphs, each with a substantive analytical thread about the BUSINESS (not the trade mechanics). Required threads (per ticker, names will vary):
- **Volumes / unit KPIs**: cohort breakdown, channel mix, regional / segment splits, momentum vs prior quarters
- **Pricing / ASP**: directional framing, geographic mix, product mix, multi-quarter trajectory
- **End-market context / industry recovery**: relevant alt-data signals, macro tailwinds/headwinds, sell-side survey data — what does the broader environment say about the print's durability?
- **Margin / OM trajectory**: explicit bridge math for back-half loading, named cost actions / efficiency drivers
- **Capital allocation + capex**: buyback pace, dividend, capex framework + what it funds (e.g., 3D fab capability, AI investment)
- **Competition + strategic context**: named competitors, share dynamics, activist engagement, M&A noise
- **Day-of binary outcome**: woven into the volumes paragraph (or wherever the day-of trigger lives)

**Anti-patterns — DO NOT use:**
- "Risk symmetry: upside asymmetric to the right; downside asymmetric to the left" — performative, doesn't add info
- "Asymmetric right" / "asymmetric left" framings without specific quantification
- "Skew" without concrete dollar/% anchoring
- Generic "raise-to-fix-walk-down vs pull-forward-upside" — only use if you can quantify what specifically is being fixed or pulled forward
- Sizing pointers ("ADD on weakness; HOLD into call") — those belong in the Trade Construction + Positioning section / Recommended Action box, NOT in Synthesis

**Voice check:** plain prose. The Synthesis should READ like an analyst's note to a PM, not like hedge-fund jargon TLDR. If a sentence feels punchy, ask: am I saying something specific or packaging?

**(c) "What could be wrong pending call" — uncertainty list** (REQUIRED, not optional):
- 2-3 bullets. Each bullet identifies a SPECIFIC aspect of the Stage 1 take that could be wrong AND names the type of management commentary that would resolve it.
- Format: "[area of uncertainty] — Watch on the call: [specific commentary] could shift the verdict to [direction]."
- Examples: "Adult volume durability — Watch on the call: if mgmt attributes the +8% to non-recurring catalysts (tax refunds, Smile Direct exit benefit), the durability premium reduces."
- This is intellectually honest framing. Stage 1 is the preliminary take; the uncertainty list explicitly tells the reader where Stage 1 may need Stage 2 refinement.

This paragraph + binary line + uncertainty list ARE the punchline. They are the first thing the analyst reads after the decision table. Everything below is supporting evidence.

**Cross-check enforcement (aggregate audit):** the synthesis claims (beat-ability direction, risk symmetry, sizing pointer) MUST be supported by the Beat-Ability + Back-Half Loading section. If they contradict, the audit halts and a focused reconciliation pass is triggered.

### TL;DR — DEPRECATED 2026-04-29

The TL;DR section was dropped after consolidation review identified it duplicates the Synthesis paragraph above. Synthesis (paragraph + uncertainty list) IS the punchline; a separate TL;DR adds redundant content. **Stage 1 docs do NOT include a TL;DR section.**

### Guide Section — Consolidated (positioned high; stocks move on the guide)

This section is the heart of the Stage 1 doc. Three sub-blocks in this fixed order:
1. Guide Delta table
2. Implied Estimate Moves (3-5 bullets — what cons needs to do)
3. Beat-ability + Back-Half Loading (the analytical detail behind the synthesis)

#### Guide Delta

| Period | Metric | Prior Guide | New Guide | Δ vs Prior | Δ vs Cons | Read |
|---|---|---|---|---|---|---|
| Q+1 rev | | | | | | (e.g., "Brackets cons. Mid-band $X. Implied beat scenario above $Y.") |
| Q+1 non-GAAP OM | | | | | | (e.g., "Above cons by ~50bps" / "Below cons by 30bps" / "In line with cons.") |
| Q+1 non-GAAP EPS | | | | | | |
| Current FY rev | | | | | | |
| Current FY non-GAAP OM | | | | | | |
| Current FY non-GAAP EPS | | | | | | |
| Capex (FY) | | | | | | |

**Read column requirements:**
- **Cons-anchored language:** EVERY row's Read cell must state where the new guide sits relative to consensus. Use one of: "Brackets cons" / "Above cons by X%" / "Below cons by X%" / "In line with cons" — followed by a brief implication. Do NOT just say "raised" or "reaffirmed" without anchoring to the cons reference. Capex rows are exempt (cons rarely tracks capex tightly).
- **Color-coding (REQUIRED):** wrap each Read cell in the appropriate CSS class:
    - <span class="guide-up">guide-up (green)</span> — when new guide is ABOVE cons (or above the prior guide in a way that pulls forward upside)
    - <span class="guide-down">guide-down (red)</span> — when new guide is BELOW cons (a cut or implicit guide-down)
    - <span class="guide-flat">guide-flat (grey)</span> — when new guide BRACKETS cons or is IN LINE with cons (no cons revision pressure either direction)
- For rows where the cons reference doesn't exist (e.g., capex), use guide-flat as the default styling.

#### Implied Estimate Moves

3-5 bullets, one per forward period (Q+1, FY+0, FY+1 if material):
- Direction: which way does cons need to move?
- Magnitude: roughly how much (in %, $, or bps)?
- Reason: tied to specific guide line items above
- Where the variant has alpha left vs cons after this print

Direction + magnitude only — no draft revised numbers. Positioned BEFORE the Beat-ability deep-dive because the "what cons needs to do" framing is high-leverage and you'll reach for it first.

#### Achievability

**Required analytical lens** in every digest. Answers:

**Achievability of the new Q guide:**
- Implied y/y growth at low / mid / high of the new Q guide range
- Cushion vs alt data signals from the preview (e.g., alt data points to +X%; guide implies +Y%; gap indicates beat-ability)
- Comp difficulty for the guided Q (easy / hard / neutral)
- Pattern recognition: how does this name historically beat its own guide?

**Achievability of the FY guide:**
- Implied 1H / 2H split given new Q guide + FY guide
- 2H exit-rate required to land FY at midpoint
- Comp difficulty by remaining quarter (which prior Q was the "trough" or "guide-cut" quarter — those become easy comps)
- Multi-line view: rev / volume / GM / OM separately. OM bridge often reveals the most.

**Back-half loading detection:**
- Compute the implied 2H growth rate or 2H OM given the 1Q + FY math
- Compare 2H implied to 2H comp setup (where was 2H last year — easy or hard comp?)
- Flag when 2H needs MEANINGFUL acceleration (>200bps OM step-up, or >300bps rev re-acceleration) — that's "stretch" loading, not "natural" loading
- Distinguish "back-half loaded by design" vs "by aspiration"

**Visibility cues from mgmt language** — MOVED to Appendix B (detail-heavy; not load-bearing for the day-of decision). Includes range tightness, range-vs-point estimate analysis, confidence-word frequency, macro hedge language tracking.

In Stage 1 (preliminary): based on PR data alone.
In Stage 2 (post-call): refined with management Q&A color, OM bridge details, any walk-back of confidence language.

---

### Beat/Miss Scorecard (Current Q)

**Positioned BELOW the Guide section** — guide is the primary stock-mover; scorecard is the supporting evidence.

**Required columns:** Metric | Actual | Cons | Δ vs Cons | Variant | Δ vs Variant | y/y | Guide | Read

**Row composition — DETERMINISTIC, capped at 10 rows.** Build the row list from config.yaml in this order:

**Bucket A — Universal foundational rows (4-5 rows, always):**
- Total Revenue ($mm)
- Adjusted Gross Margin (%) — or sector-equivalent (MLR for insurers; NII margin for banks)
- Adj EBITDA ($mm)
- Adj EBITDA Margin (%)
- Free Cash Flow ($mm)

**Bucket B — Day-of binary metric(s) (1-2 rows):**
- Per `config.yaml day_of_binary.primary`
- Plus secondary day-of binary if defined

**Bucket C — Material segment / geographic splits (0-3 rows):**
- Only if `config.yaml material_splits.enabled` is true
- List the splits explicitly named in `material_splits.rows`

**Bucket D — Top salient KPIs not already covered (0-3 rows):**
- From `config.yaml salient_kpis` in priority order
- Skip any already in Bucket A/B/C
- Cap so total scorecard rows ≤ 10

**Universal exclusions (move to dedicated sections, NOT scorecard):**
- Marketing / Ops / Tech / G&A as % rev → Adjusted Operating Expenses View
- Stock-Based Compensation → Adjusted Operating Expenses View
- Legal settlement / Acquisition / Restructuring add-backs → Cash Quality + Working Capital Flags
- GAAP Net Loss / Diluted EPS → inline in Synthesis prose, not scorecard
- Capex (unless on FY scorecard) → Cash Quality section
- Apples-to-apples / old-definition EBITDA → Cash Quality section as quality-of-earnings flag

GAAP rows excluded by default; include GAAP-only line items (e.g., GAAP NI for buyback context) only when explicitly relevant to the trade.

**Closing gut-check paragraph:** explicitly cross-reference the print's implied y/y growth against (a) management's prior guide, (b) the variant's expectation, (c) any alt-data signal used in the preview. Surface inconsistencies. Decompose volume vs ASP gap if revenue-growth and volume-growth diverge.

**Audit rule:** `baseline_audit.py` should verify (a) scorecard row count ≤ 10; (b) every Bucket A foundational row is present; (c) `day_of_binary.primary` appears in the scorecard.

### Cash Flow Walk — Reported Earnings vs. Cash (REQUIRED — Stage 1)

The cash flow check is the single most important defense against management spin on a noisy print, so every Stage 1 includes a cash flow walk reconciling reported NI to the cash balance change.

Required table format:

| Line | Period | Source / formula |
|---|---|---|
| Cash beginning | $X | PR balance disclosure [STATED] |
| Cash ending | $Y | PR balance disclosure [STATED] |
| Net cash change | $Y - $X | direct math [INFERRED] |
| GAAP NI | $NI | PR [STATED] |
| Capex (estimate or actual) | -$Z | FY guide × Q-share OR 10-Q if available |
| Buyback / dividend | -$B | PR [STATED if disclosed by quarter, else INFERRED] |
| Other (WC + restructuring cash + taxes + FX) | residual | (cash change) - NI + capex + buyback |

**Read paragraph required.** State magnitude of "other" residual as % of GAAP NI. Flag if residual is unusually large (>50% of NI) — that's a soft tell that working capital build, restructuring tail, or tax timing is consuming earnings. Note that the precise breakdown requires the 10-Q (filed weeks later); Stage 1 walk flags the gap, Stage 4 forensic review fully bridges it.

**Pre-call check:** if mgmt's narrative on the call doesn't address WC build / restructuring tail / tax explicitly when the residual is >50% of NI, flag in Stage 2 watch-list.

### Narrative Read — DEPRECATED 2026-04-29

The Narrative Read section was folded into the Synthesis paragraph at the top. Stage 1 docs do NOT include a standalone Narrative Read section. Material narrative points (capital allocation, restructuring, mix shifts, FX/macro callouts, language tone) condensed to the most decision-relevant items in the Synthesis. Full per-pillar narrative analysis lives in Stage 2's Thesis Narrative Synthesis.

### Watch-List Reconciliation + Call Questions (Consolidated 2026-04-29)

Single section with three buckets via CSS class. Each item in the ABSENT bucket gets an explicit "Call question" — the merged Watch-List + Questions-for-Call format eliminates the prior duplication where ABSENT items appeared in both sections.

| Bucket | Items | Action |
|---|---|---|
| ADDRESSED — substantive | Items mgmt addressed in PR with specifics | None — captured |
| PARTIAL — addressed but light | Items mentioned but not quantified | Flag in Stage 2 watch |
| ABSENT — call watch | Items the PR did NOT address | **Each item gets a specific question to ask on the call** |

The previous standalone "Questions to Pay Attention To On the Call" section is REMOVED — its content lives inline with the ABSENT bucket items.

### Tactical Lens — Action and Pair Read (Up-Top Summary)
- Idio alpha thesis: confirmed / broken / ambiguous
- Pair trade view: which leg moved more than expected; β-neutral sizing implication
- Squeeze: SI direction inferred from print
- Action: HOLD / ADD / TRIM / EXIT + sizing math

### Historical Earnings Reaction Calibration
- Last 4-Q table: actual print quality vs stock reaction
- Closing line on whether this print fits the calibration pattern

---

## Appendix A — Quantamental Viewpoint (Post-Print)

### A.1 Options / Implied Move vs Realized
- Implied move from preview vs actual move (or pre-market / after-hours)
- Asymmetry observed in the post-print tape

### A.2 Pair Trade Re-Rate
- Pair candidates from preview matrix
- Actual relative move post-print
- Whether the pair view is intact / broken / needs unwind

### A.3 Cons Revision Read
- Sell-side notes likely to chase / fade — directional read
- Where the largest revisions concentrate (Q+1 vs FY+1)

### A.4 Squeeze Risk Update
- SI evolution implied by the print quality
- Watch points for the next data drop
```

### Stage 2 — Transcript-Integrated Digest

```
# {Company} — {Quarter} Post-Call Digest
{Stage 1 reference: link / filename}
{Call metadata: date / time / call duration / number of analyst questions}
{Mgmt participants only — name + title (CEO, CFO, CTO, IR). DO NOT enumerate sell-side participants in the header. Sell-side analyst attribution appears in the Q&A Highlights section if at all, paired with their specific exchange. Header should be PM-readable in 5 seconds; sell-side roster bloats the header without adding decision-relevant content.}

### Thesis Narrative Synthesis

**Required at the top of Stage 2.** Pillar-by-pillar refresh of the major thesis points from the preview's Overview section. Each pillar gets a status tag and a 1-2 sentence note on what the call did to it.

Pillar status tags (use the appropriate CSS class):
- <span class="beat">STRENGTHENED</span> — call provided new positive evidence
- <span class="beat">CONFIRMED</span> — call reaffirmed prior framing
- <span class="inline">NEUTRAL</span> — call neither helped nor hurt
- <span class="miss">SOFTENED</span> — call introduced a hedge or partial walk-back
- <span class="miss">ABSENT</span> — pillar conspicuously not addressed (signal, not neutral)

Pillars to cover (drawn from the preview — names will vary by ticker):
- **Volumes** (cohort splits, channel mix, durability)
- **Pricing / ASP** (geographic mix, product mix, full-year framework)
- **Margins / OM trajectory** (FY framework, bridge components, multi-year glide path)
- **Competition** (named competitors, share dynamics, product cycle)
- **Capital allocation** (buyback pace, dividend, M&A, balance sheet)
- **Activist / Strategic** (engagement, board changes, strategic review)
- **Macro / Tariff exposure** (only when material)
- **Channel / Customer concentration** (DSO commentary, end-market commentary)

Format: short sub-headers per pillar with status tag + 1-2 sentence note. Compact prose, not bullet salad.

### TL;DR (Stage 2) — DEPRECATED 2026-04-29

The TL;DR (Stage 2) section was dropped after consolidation review identified it duplicates the Thesis Narrative Synthesis above. Pillar-by-pillar status tags in the Thesis Synthesis ARE the TL;DR. **Stage 2 docs do NOT include a TL;DR section.**

### Delta vs Stage 1
- Lead bullet: did the action recommendation change, why or why not
- Resolution status of Stage 1's "What could be wrong pending call" uncertainty list (each item: RESOLVED / UNRESOLVED / N/A + tilt direction)
- NEW data not in Stage 1 (specific items disclosed in Q&A or prepared remarks not in PR)
- (Drop pillar-status restatement — already in Thesis Synthesis)

### Updated Guide Section — Consolidated
- Updated Beat/Miss + Guide table (only metrics where Q&A added color)
- Achievability refresh (bullet form — STRENGTHENS / SOFTENS / N/A vs Stage 1)
- (Synthesis refresh paragraph DROPPED — duplicates Thesis Narrative Synthesis at top of doc)

### Surprise Decomposition (REQUIRED — Stage 2)

Replaces vague "the print was good/bad" framing with a structured 4-question block:

1. **Was the surprise driven by one line item or many?** Decompose the EPS / OM / rev surprise into contributing buckets (volume vs ASP; GM vs opex; FX vs underlying; tax / below-the-line). Use the dollar bridge from the Beat/Miss Scorecard.
2. **Is the driver sustainable or one-time?** For each contributing bucket: is it a structural improvement (mix shift, cost actions, market share gain) or a one-time benefit (FX tailwind, tax true-up, restructuring tail timing, channel pull-forward)? Tag each accordingly.
3. **Does management's explanation match the cash flow walk?** Reconcile mgmt's call narrative against the Stage 1 cash flow walk + any 10-Q data available. If mgmt says "execution + better-than-expected" but the cash flow walk shows working capital build / restructuring tail / tax timing absorbing earnings, flag the divergence.
4. **Does the surprise confirm or disconfirm any standing variant thesis claim?** Link to the preview's open thesis claims (volume durability, OM expansion, etc.).

Position this block AFTER the Updated Guide Section and BEFORE the Watch-List Reconciliation. Cross-reference findings into Watch-List ABSENT bucket (items mgmt didn't address).

### Watch-List Reconciliation (Updated)
Single section with three buckets (addressed-topic / partial-topic / absent-topic). The ABSENT bucket items are the Stage 1 items the call did NOT resolve — each gets a "next data point" pointer for tracking forward.

The standalone "Stage 1 Items the Call Did NOT Resolve" section is REMOVED — its content merges into the Watch List ABSENT bucket with the next-data-point annotation.

### Language + Management Tone Read (Consolidated)

**Single section** combining prior "Language Change Log" + "Management Tone Read." Sub-sections:

- **NEW topics introduced this quarter** (named platforms, frameworks, products)
- **Stable / repeated framings** (high-frequency anchor words and what they signal)
- **Conspicuously ABSENT topics** (expected from preview but not addressed — signal, not neutral)
- **Tone read by speaker** (CEO / CFO separately) — plain-English: defensive / open / hedged / substantive. Specific examples cited (e.g., "On X, mgmt gave a 12-word answer to a substantive question — flagged.")

### Q&A Highlights — Top Exchanges (Compact)

**Positioned AFTER the Language + Tone Read** (not before). Format is COMPACT bullet list, NOT a wide table — wide tables paginate poorly in the PDF render.

Format per exchange:
- **{Asker} / {Firm}** [substantive / hedged / dodged]: 1-2 sentence summary of what was asked + what mattered in the answer.

Top 4-5 exchanges only — anything more clutters. Pick exchanges by leverage on the variant thesis, not by length.

### Recommended Action — Action Box

**Required label = "Recommended Action".** Do not use named-author action labels in deliverables. The `production_ready_check` gate halts the render if any named-author action label is present. Format:

```
<div class="action-box">
<strong><span class="{ACTION_CLASS}">{HOLD / ADD / TRIM / EXIT}</span></strong> — {1-line rationale tied to scorecard + guide}.

<strong>Sizing framework:</strong>
<ul>
<li>{Current size}; {trigger-based instruction at price level 1}; {trigger-based instruction at price level 2}; {preferred structure detail}.</li>
</ul>

<strong>Confidence:</strong> {high / medium / low} on {area_1}; {high / medium / low} on {area_2}. Primary uncertainty: {key uncertainty}.
</div>
```

Followed by:
- Pair trade view: DELTA-ONLY (1 line if unchanged from Stage 1; otherwise specific change cited)
- Squeeze read: DELTA-ONLY
- Implied move vs realized: 1-2 sentences citing actual move vs implied
- (Restatement of Stage 1's pair/squeeze framing is REMOVED — Stage 2 captures only what changed)

<!-- "Stage 1 Items the Call Did NOT Resolve" section REMOVED — merged into Watch-List Reconciliation ABSENT bucket with next-data-point annotation -->

---

## Appendix A (same structure as Stage 1, with post-call updates)
```

---

## 5. Style Guidance

- **Voice:** institutional research note tone. Direct, no fluff, abbreviations OK (HSD/MSD/LSD/LDD%, q/q, y/y, OM%, EBIT, FX, etc.). No first-person commentary about the drafting process.
- **Production-ready output:** every digest is a circulation deliverable. The deterministic `production_ready_check.py` gate halts the render on any of the following (full rule list in `production_ready_check.py`):
  - Bias Pre-Commitment block or first-person pre-commitment language ("Going in I'm leaning…", "I'm at risk of confirmation bias…", "Pre-commit horizon…").
  - Named-author action labels — use **"Recommended Action"**.
  - Pre-print framing rows in the digest header ("Pre-Print Decision (from preview)", "Earnings Preview Score", "Recommended Position Size (from preview)").
  - Scaffolding placeholders that escaped fill ([PENDING], LLM_FILL, "Sub-agent X fills", "[user — pending]").
  - Internal version-history breadcrumbs ("from the prior preview", "the prior draft", "earlier framing").
  - Stage / process footers ("End of Stage 1…", "Audit metadata", "Template Usage Notes — REMOVE BEFORE RENDERING").
  - "PRESTAGED" naming in delivered filenames.
  - Self-referential drafting commentary ("my earlier framing", "in my initial draft").
  - Performative jargon ("risk symmetry: asymmetric right vs left").
- **Length:** Body should fit ~5-8 pages PDF; appendix ~1-2 pages.
- **No EBITDA row** in scorecard tables (by preference, same as preview).
- **Bold sparingly:** numbers and headers only; don't bold whole sentences.
- **Tables before prose:** if a table can replace prose, use the table.
- **No emojis in tables:** use CSS-class colored text (Beat=green, Miss=red, In-line=black).
- **Direction column color-coded** in delta tables: raised/up=green, reaffirmed=black, lowered/down=red.
- **Filename convention:** `{TICKER}_{PERIOD}_PRINT_DIGEST.{md,pdf}` for final circulation copy. Internal versioned scaffolds (`digest_v1_print_*`, `*_PRESTAGED.md`) stay in `digest_work/` and never circulate.

---

## 6. Quality / Audit Checklist

Before delivering, verify:

- [ ] All extracted figures cite a source (press release character offset or transcript line + speaker)
- [ ] Every cons / variant figure used in deltas matches digest_baseline.json
- [ ] Guide delta arithmetic verified (new - prior, vs cons, vs variant)
- [ ] Beat/miss classifications match key_metrics.yaml in_line_thresholds
- [ ] Implied estimate moves stated as direction + magnitude, not new numbers (unless you explicitly upgrade to "draft revised numbers")
- [ ] Watch list reconciliation covers every item from the standing watch list — no silent drops
- [ ] Recommended Action box (HOLD/ADD/TRIM/EXIT) ties to the scorecard, not free-standing speculation
- [ ] Pandoc renders with `--from markdown-tex_math_dollars`
- [ ] Color classes render in PDF (Beat=green, Miss=red, In-line=black)
- [ ] **`production_ready_check.py` PASS** — no forbidden phrases, no scaffolding placeholders, no named-author labels, no pre-print rows in digest header, no stage / process footers
- [ ] Page count target met (5-8 pages body)
- [ ] **GUT-CHECK PASSED:** every revenue / volume / EPS line in the scorecard has y/y growth shown; gut check paragraph reconciles implied growth vs prior guide vs variant vs alt data

**Standard rendering pipeline:**

```bash
# Deterministic production-readiness gate runs by default in render_digest.py.
# Override with --skip-production-check only for internal scaffolded renders.
python3 render_digest.py path/to/digest.md
```

Internally `render_digest.py` calls `production_ready_check.py` before pandoc/weasyprint; if forbidden phrases are present the build aborts with exit code 2 and a remediation list.

---

## 7. Optional External Data Inputs

Where you have external data, you supply it; otherwise the agent stubs the section:

| Data | How supplied |
|---|---|
| Earnings deck (companies that file IR-only) | WebFetch IR site (`ir_deck_url` in config.yaml) |
| Real-time stock reaction post-print | OPTIONAL — paste if you have it; otherwise stub |
| Sell-side immediate reaction notes | Drop in Reference Files |
| Implied move adjustment post-print | OPTIONAL manual input |
| Borrow rate / utilization update | OPTIONAL manual input |

---

## 8. Deployment / Repeatability

To deploy on a new ticker:

1. Verify the ticker has run through the preview agent at least once
   (digest needs the preview baseline as the spine).
2. If the company files only the press release in 8-K, update
   the ticker's config.yaml with `ir_deck_url` field pointing at the
   IR earnings page.
3. Trigger: `digest [TICKER] print` after seeing the headline.
4. After the call: drop transcript into `/transcripts/`, trigger
   `digest [TICKER] transcript`.

---

## 9. XYZ as Worked Example

Use a generic ticker `XYZ` as the prototype. The most recent `{PERIOD}_PREVIEW.md` is the
canonical baseline. The digest will:
- Load the preview KPI tables for the current-Q / next-Q / FY expectations stack
- Pull the earnings 8-K via the EDGAR fetcher (`python scripts/edgar_fetch.py --ticker XYZ`, Item 2.02)
- Fall back to the company IR site for the earnings deck PDF
- Compute scorecard against the preview baseline
- Run through 3 audit gates
- Render to digest_v1_print_{period}_{YYYYMMDD}.{md,pdf}

After you drop the call transcript:
- Load digest_v1
- Parse transcript
- Compute deltas
- Render digest_v2_transcript_{period}_{YYYYMMDD}.{md,pdf}

---

## 10. Build Status

| Component | Status |
|---|---|
| DIGEST_AGENT_SPEC.md (this file) | Drafted |
| earnings_digest_runner.py | Pending |
| digest_baseline_loader.py (parses preview MD → JSON) | Pending |
| pr_extractor.py (extracts numbers from press release text) | Pending |
| scorecard_compute.py (beat/miss + guide delta) | Pending |
| audit_agent.py digest mode | Reuse + extend existing audit_agent.py |
| digest_style.css | Done |
| Smoke test | Pending — first real print |
