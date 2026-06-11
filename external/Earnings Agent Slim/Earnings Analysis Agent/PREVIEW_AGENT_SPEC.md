# Earnings Preview Agent — Generalized Workflow Spec

**Purpose:** Generalized spec for producing earnings previews on ANY ticker. Defines the workflow, required/optional inputs, output template, and standalone-vs-symbiotic modes, using only free/manual data sources.

**Status:** Canonical template. Use `XYZ` as the generic worked example throughout.

---

## 1. Operating Modes

The agent runs in one of two modes. Default is **symbiotic** — agent does the work, you supply the view + any external data you have.

### Standalone Mode

Agent generates a preview entirely from auto-pullable / free data. No user input required. Output is marked clearly with placeholder sections ("user input pending") for items that genuinely need a human view.

When to use: triage / first-pass on a name, sector overview, low-conviction sizing decisions, or when you're not ready to supply a view.

Limitations:
- No variant — uses consensus as the only baseline
- No pre-earnings decision (BUY/SELL/HOLD/TRIM) — left blank or set to HOLD as default
- No earnings preview score — left blank
- No narrative thesis going into the print
- No proprietary external data (options skew, positioning, niche surveys)

### Symbiotic Mode (Default)

Agent does all the auto-pullable work, then prompts you for inputs at defined gates. Output integrates your view + agent's independent triangulation + consensus.

When to use: any real position-management decision.

---

## 2. Workflow

```
TRIGGER: "prep earnings for [TICKER]" or "/preview [TICKER]"
   ↓
[1] AUTO-DISCOVER
   - **Local file freshness check FIRST.** Before any synthesis JSON is reused, fingerprint every file in `Reference Files/{TICKER}/` by `(filename, mtime, size_bytes)` and compare against `Reference Files/{TICKER}/.fingerprint_manifest.json` from the prior cycle. Any file with newer mtime or different size marks the corresponding synthesis JSON as STALE; re-extract the stale synthesis(es) before drafting. The re-extraction should produce a diff document at `synthesis/{key}_diff_{prior_date}_to_{current_date}.md` highlighting material changes. Update the fingerprint manifest at the end of the cycle. This freshness check is a HARD GATE on every preview cycle — a stale cached synthesis can produce a structurally wrong narrative (e.g. "variant +58% above cons" when the current model says "+20%").
   - **Pull primary-source filings** via the free SEC EDGAR fetcher: `python scripts/edgar_fetch.py --ticker {TICKER}` writes 10-K/10-Q/8-K extracts to `workspace/{TICKER}/filings/`.
   - **Optional local position data:** if `workspace/{TICKER}/position.json` is present, read it for position direction (long/short), shares, $-invested, %-weight. If absent, mark position size as "not provided" — do NOT fabricate a placeholder.
   - **Optional local research notes:** if `workspace/{TICKER}/research_notes/` exists, read every note end-to-end before drafting; accumulated thesis lives here.
   - Check `workspace/{TICKER}/` for existing local data
   - Check Reference Files folder for ticker-named PDFs / model
   - Inventory what's present vs what's missing
   ↓
[1.5] DEEP READ — Reference Files + Story Dossier (MANDATORY, GATES DRAFTING)
   - **Reference Files folder structure (standardized; runner expects this):**

     ```
     /Reference Files/{TICKER}/
       /sell_side_notes/        — broker research PDFs (filename: YYYYMMDD_BrokerName_TICKER_topic.pdf)
       /press_releases/         — material partnership / strategic PRs
       /ir_decks/               — IR presentations
       /models/                 — your model + any sell-side models (xlsx + PDF)
       /transcripts/            — earnings call transcripts (text or PDF)
       notes.docx               — your accumulated notes (or notes.txt / notes.pdf)
     ```

     Missing subdirs are not failures (some tickers won't have all categories) but the runner
     should inventory and surface what's present vs missing.

   - **Sell-side synthesizer pattern — LLM dispatch via Task tool:**

     The runner dispatches general-purpose `Task` agents (one per PDF, in parallel) to extract
     structured JSON from each broker note.

     Pattern per PDF:
     ```
     Task(
       subject = "Extract sell-side note from {file}",
       agent_type = "general-purpose",
       prompt = """
         Read {pdf_path}. Extract structured JSON with these fields:
         - broker, date, analyst, rating, price_target
         - bear_thesis_components: list of distinct bear bullets
         - bull_thesis_components: list of distinct bull bullets
         - key_data_points: list of {metric, value, source}
         - q1_estimate, q2_estimate, fy_estimate (if cited)
         - notable_arguments: views not in cons
         Save to: synthesis/{broker}_{YYYYMMDD}.json
       """
     )
     ```

     The orchestrator dispatches all PDFs in parallel (single message, multiple Task tool calls),
     waits for completion, then aggregates JSON files into `sell_side_synthesis.md`.
   - **Force-read EVERY file** in `/Earnings Analysis Agent/Reference Files/{TICKER}/` end-to-end.
     This is non-negotiable — the agent MUST NOT proceed to drafting without completing this step.
     Includes: your notes (.docx), sell-side models, IR decks, partnership press releases,
     your model + sheets (Revenue, Model, Scenario Analysis), prior previews/recaps.
   - Force-read every file in `workspace/{TICKER}/` (config.yaml, key_metrics.yaml,
     existing data files, prior outputs, alt_data drops, positioning screens).
   - Pull primary-source documents the agent doesn't already have:
     a. **Latest 10-Q + 10-K** via the EDGAR fetcher — read revenue recognition footnote in full
        (gross vs net treatment of partnerships; pass-through dynamics; reseller arrangements).
     b. **Most recent earnings call transcript** if accessible — extract management commentary on
        the bear/bull thesis components, partnership economics, capacity ramp, regulatory.
     c. **Recent partnership / strategic announcement press releases** — confirm timing and
        accounting treatment of any major partnership.
   - Produce a **STORY DOSSIER** (`workspace/{TICKER}/STORY_DOSSIER.md`)
     synthesizing everything read. Required sections:
     1. **The story in one paragraph** — what does this company do, what's the current narrative
     2. **Bear thesis components** (numbered list of distinct mechanisms)
     3. **Bull thesis components** (numbered list — recent rally drivers, long-term targets,
        platform investments, optionality)
     4. **Recent rally / sell-off drivers** (what moved the stock since the last print and why)
     5. **Specific accounting / partnership nuances** (rev recognition treatment per partnership;
        gross vs net; pass-through dynamics and TIMING of when each kicks in)
     6. **Open questions to resolve before drafting** (questions for you OR things to
        verify in primary docs)
   - **The dossier gates drafting.** If the agent draft contradicts the dossier, the dossier
     wins and the draft must be revised.
   ↓
[2] REQUEST INPUTS (symbiotic mode only)
   - Display the input checklist (see §3)
   - ALWAYS surface the input checklist up front and WAIT
     for your data + view (short-interest detail, options implied move + skew,
     latest research/desk, decision/size/score/PT). Never auto-fill these and flag them
     as estimates, even on 'end-to-end' runs.
   - Mark each item as [REQUIRED] / [RECOMMENDED] / [OPTIONAL]
   - Pre-draft questions for you:
     a. What's the rally / sell-off narrative driving recent stock action?
     b. What are the bear thesis components (3-5)?
     c. What are the bull thesis components (3-5)?
     d. Any partnership accounting nuances (gross vs net, pass-through, timing)?
     e. Any recent press releases or filings the agent should know about?
   - Wait for you to drop or confirm "skip this one"
   ↓
[3] PULL AUTO-DATA (free sources)
   - Print date + AMC/BMO from the company IR site / latest 8-K
   - Consensus (rev, EPS, EBITDA, GM, OM, segment metrics where available) entered manually
     into `workspace/{TICKER}/consensus.csv` for current Q + Q+1 + current FY at minimum
   - Historical surprise (last 8 Q EPS + actual rev) and price reactions from filings / IR history
   - Daily prices for ticker + comp set (90 days minimum) via the stock-reaction helper
   - **For sector-specific KPIs not in standard aggregates (e.g. healthcare insurers' quarterly
     MLR / SG&A ratio / membership): pull the last 4Q 10-Qs explicitly** via the EDGAR fetcher.
   - Compute correlations, beta vs sector ETF, realized vol
   - Compute cons EPS dispersion (CV, # ests, revision skew) from the consensus CSV
   - Confirm peer earnings dates for sequencing analysis (from peer IR calendars)
   - **Build data manifest JSON** (data/data_manifest.json) listing every
     pulled metric, source, value, and pulled_at timestamp. This feeds
     the audit gates downstream.
   ↓
[3a] AUDIT GATE 1 — Pre-Draft Data Verification (HALTS workflow if fails)
   - Run audit_agent.py against the data manifest only (no markdown yet).
   - Verify: are all required metrics present? Are any sources stale?
   - Verify comp set: for each peer ticker, confirm primary business segment
     mix is recorded in manifest (block segment-misclassification errors).
   - If gate fails: return to step [3] and pull missing data before drafting.
   ↓
[4] BUILD CONTEXT
   - Compile alt data summary table (sell-side surveys + macro + comp readthroughs)
   - Compile thesis context from thesis_current.md if present
   - Compile last management commentary (most recent earnings call quotes / guide)
   - For each peer comp, anchor commentary to the verified business mix.
   ↓
[4b] COMP READTHROUGH (peers that have already reported)
   - From config.yaml comp_set, identify which comps have ALREADY printed this
     cycle (earnings dates / recap notes in the ticker folder).
   - Synthesize each reported comp's readthrough: demand/comp trend, margin
     (freight/promo/tariff), high-end-consumer health, share shifts, guide actions,
     stock reaction.
   - Weave into the Overview AND a couple of Data Monitoring rows, balanced (where it
     supports vs cuts against the thesis), with a price-point caveat.
   - Always check comps that have reported and incorporate.
   ↓
[5] PROMPT FOR VIEW (symbiotic mode only)
   - Pre-earnings decision (BUY/SELL/HOLD/TRIM) + price triggers
   - Recommended position size
   - Earnings preview score (1-5 composite)
   - Pre-print thesis (free-form)
   - Bull case / base case / risk framing
   ↓
[6] DRAFT PREVIEW (in chunks, not monolithic)
   - Build the preview SECTION-BY-SECTION, running audit_agent.py after EACH
     major section (Takeaways → Overview → KPI tables → Buy/Sell-side bar →
     Appendix). Numbers shape the narrative — if the numbers are wrong early,
     the narrative built around them will be wrong, and fixing at the end
     means refactoring the whole thing.
   - Use canonical template (see §4)
   - Triangulate your view vs cons vs agent's independent read
   - Surface disagreements, do not bury them
   - Use your voice/style if known (read prior previews as style ref)
   ↓
[6a] AUDIT GATE 2 — Mid-Draft Numerical Verification (HALTS if fails)
   - After drafting Takeaways + Overview + KPI tables (the numerical core),
     run audit_agent.py against partial draft.
   - Required pass criteria: zero "modeled X%" / "back-solved" / "probably"
     / "likely" patterns where actual data is available from filings.
   - Required: every $ figure / % / bps citation matches a manifest entry
     OR is a derived calculation (y/y growth) traceable to manifest entries.
   - Required: comp/peer characterizations match manifest's recorded business mix.
   - If gate fails: PULL MISSING DATA from filings; do NOT proceed to narrative
     sections (Buy-side bar, Appendices) until numerical core is clean.
   ↓
[7] FINAL AUDIT PASS — Pre-Render (HALTS if fails)
   - Run audit_agent.py against complete draft.
   - Every figure has a source + date traceable to manifest
   - Score logic shown
   - Flag any contradictions between research notes and the draft
   - Verify no broken refs / stale "TBD" markers in cells where data exists
   - Verify no remaining "modeled" / "estimated" / "back-solved" claims
     where pull-able data was available
   - If audit returns suspicious flags: address each before render.
   ↓
[8] DELIVER
   - Markdown source to `workspace/{TICKER}/outputs/`
   - PDF rendered via pandoc → weasyprint (with `--from markdown-tex_math_dollars`)
   - Audit report committed alongside as {filename}_audit_report.md
   - Summary in chat with key changes since prior version
   - Provide computer:// link for PDF
```

---

## 3. Input Checklist

The agent should prompt you at workflow step [2] with this checklist. Items marked [REQUIRED] block the workflow if absent. Items [RECOMMENDED] degrade the analysis quality if absent. Items [OPTIONAL] add color but aren't load-bearing.

### Your view and decision

| Input | Tier | Purpose |
|---|---|---|
| Pre-earnings decision (BUY/SELL/HOLD/TRIM) + price triggers | [REQUIRED] | Drives the decision table at top of preview |
| Recommended position size | [REQUIRED] | Drives the decision table |
| Earnings preview score (1-5 composite) | [REQUIRED] | Anchor for the agent's triangulation |
| Pre-print thoughts / thesis (free-form) | [RECOMMENDED] | Shapes the narrative; without it agent uses cons + thesis_current.md |
| Bull case / base case scenario framing | [RECOMMENDED] | Shapes the scenario table |
| Risk / down-print scenario | [RECOMMENDED] | Shapes the scenario table |

### Your model

| Input | Tier | Purpose |
|---|---|---|
| Your variant estimates (file or screenshot) | [RECOMMENDED] | Drives the "Your Variant vs Consensus" KPI tables. Without it, table shows cons only. |
| Per-period quarterly variant: rev, GM%, EBIT, EBIT margin, EPS, units | [RECOMMENDED] | Same |
| FY+0 + FY+1 variant numbers | [RECOMMENDED] | Drives the bull-case multi-year math |

### External data (you supply if available)

| Input | Tier | Purpose | Source |
|---|---|---|---|
| Short interest detail | [RECOMMENDED] | Squeeze risk + positioning analysis | Free SI sources / exchange data |
| Implied move / historical reaction | [RECOMMENDED] | Implied move and historical reaction asymmetry | Options chain / free data |
| Vol surface — vol table + skew chart | [OPTIONAL but high value] | Options surface analysis (Appendix A.1) | Free options data |
| Sell-side research PDFs (drop into Reference Files) | [OPTIONAL] | Alt data summary table | Your research feeds |
| Positioning notes | [OPTIONAL] | Positioning context | Your own notes |
| Desk / sales commentary (paste) | [OPTIONAL] | Buy-side bar | Your inbox |
| Whisper number (if any) | [OPTIONAL] | Buy-side bar | Whisper services or desk reads |
| Macro alt data | [OPTIONAL] | Macro tailwind/headwind context | Public macro data |
| Borrow rate + utilization | [OPTIONAL] | Refines squeeze risk read | Free borrow data |

### Per-ticker config (one-time setup, then maintained)

Stored at `workspace/{TICKER}/config.yaml`:

```yaml
ticker: TICKER
sector_etf: XLV   # or XLF, XLK, etc. — for beta computation
comp_set:
  - {ticker: COMP1, role: direct_competitor}
  - {ticker: COMP2, role: adjacent}
  - {ticker: COMP3, role: distributor_or_supplier}
key_metrics:        # what gets in the KPI tables
  - units_shipped
  - segment1_rev
  - segment2_rev
  - total_rev
  - non_gaap_gm
  - adj_ebit
  - adj_ebit_margin
  - non_gaap_eps
alt_data_sources:    # what's commonly available for this name
  - {name: "Industry survey data", typical_provider: "sell-side surveys"}
  - {name: "Web traffic", typical_provider: "public web-traffic data"}
  - {name: "Macro consumer", typical_provider: "tax refunds / consumer confidence"}
positioning_inputs:   # what the agent should ask for / not ask for
  whisper_culture: false   # some names have a whisper; most don't
  desk_emails_typical: false   # only for crowded names
signature_style: "user"   # references prior previews for tone match
```

This config is read at step [3] to know which comps to pull, what metrics to populate, what positioning inputs to ask for.

### Auto-pulled / free (no action required)

- Print date, consensus (manual CSV), surprise history, prices, segment data
- SEC filings (10-K/10-Q/8-K) via the EDGAR fetcher
- Local: thesis_current.md, Reference Files, prior outputs, position.json, research_notes/

---

## 4. Canonical Output Template

**Production-ready invariant.** Every preview deliverable runs through `production_ready_check.py` and `scripts/style_linter.py` before render. The build halts on any of:

- First-person commentary about the drafting process ("Going in I'm leaning…", "I'm at risk of…", "my earlier framing").
- Bias Pre-Commitment block (pre-commitment is an internal pre-flight artifact in `synthesis/`, not in the deliverable).
- Name-placeholders that escaped fill (`[pending]`, `[user — pending]`).
- Scaffolding placeholders (`[PENDING]`, `<!-- LLM_FILL -->`, `Sub-agent X fills`).
- Any named-author action label — the preview's recommendation row is "Pre Earnings Decision" (no name attached).
- Internal version references ("V3 said X", "the prior draft", "earlier framing"). Delivered filename is `{TICKER}_{PERIOD}_PREVIEW.{md,pdf}` — no V1/V2/V3 in circulation copies.
- Stage / process footers ("End of Stage 1…", "Audit metadata", "Template Usage Notes — REMOVE BEFORE RENDERING").
- "PRESTAGED" references in delivered filenames or body.
- Performative jargon ("risk symmetry: asymmetric right vs left").

Decision-table rows that ARE permitted in the preview (these are preview-only fields and must NOT be reproduced in the post-print digest): `Pre Earnings Decision`, `Recommended Position Size`, `Earnings Preview Score`. The `{user}` placeholder in the template below is the signature-style identifier from `config.yaml`, not a "fill-me-in" marker — it gets substituted at build time and the value should be your view (not the string "user").

The output structure is locked to this format. Sections in order:

```
# {Company} — {Quarter}
{Print info line: date, time, last close, implied move}
{Position info line: $ value, shares, % weight}

| Pre Earnings Decision | {user} |
| Recommended Position Size | {user} |
| Earnings Preview Score | {user} |

### Takeaways
- 6-8 bite-sized bullets (one to two sentences each)
- Cover: setup direction, expected reaction + decision, OM/key metric framing,
  alt data summary, bull case, activist or other one-liners, risk
- Last bullet should reference the day-of binary clearly
- Tactical lens lives in OVERVIEW (not Takeaways)

### Overview — Why we are bullish/bearish into this earnings print?
- Opening prose paragraph: setup framing
- Bullet headers: short 5-6 word punchy takeaways
- Bullets cover: print achievability, bull case, base case, OM/margin commentary,
  comp/sequencing setup, macro tailwind, positioning + tactical lens (last)

### What metric(s) are most important for the print
- Bullet list of what to watch first
- Lead with the highest-leverage metric (e.g. unit volumes as "turbo trigger")

### How your variant compares to consensus
- 3 KPI tables: current Q (print), Q+1, current FY
- Columns: Metric | {Co} Guide | Your Variant | y/y | Cons | y/y | Δ vs Cons
- **MANDATORY: Each $ row pairs with implied y/y growth for the variant AND Cons.**
  Without y/y context, the absolute numbers can't be gut-checked against guide.
  Compute from prior-year-quarter actual (pull from historical filings).
- Rows: units, segment revs, total rev, GM%, EBIT, EBIT margin, EPS (no EBITDA by preference)
- Capex row only on FY table
- Each table header line includes prior-year actuals for context
  (e.g., "Q1 (Q1 prior-year actual: segment1 $797mm / segment2 $182mm / total $980mm)")
- **MANDATORY: Closing "Gut check on the numbers" paragraph that explicitly:**
  - Cross-references each metric's implied y/y growth against the guide range
  - Cross-references against alt data signals (volume growth from surveys/PMS data)
  - Flags any inconsistencies (e.g., "Cons segment +4.8% y/y is at LOW end of mgmt's MSD% guide; alt data points higher")
  - Decomposes volume vs ASP gaps where revenue-growth and volume-growth diverge
  - Surfaces self-aware caveats (e.g., "GM probably too conservative")
  - States where the variant's alpha actually concentrates (current Q vs Q+1 vs FY+1)

### Buy-side / sell-side bar
- Opening prose paragraph: positioning + revisions context
- Day-of framing sentence (volume / revenue / whatever the trigger is)
- Scenario probability table

### Data Monitoring
- Alt data summary table — color-coded direction column (Positive/Neutral/Negative,
  green/black/red text via CSS classes)
- Forward listening list

### Milestones
- Bullets

### Historical earnings beats/misses/stock reactions
- Last 4-Q table
- Closing commentary on calibration

### What options market is pricing in
- Implied move + range

---

## Appendix A — Quantamental Viewpoint

### A.1 Options Surface — What It Means for the Stock
- Lead with plain-English bottom line
- Asymmetry / collar interpretation
- 4-5 implications for the position
- Supporting reference tables (term structure, skew snapshot, skew evolution)

### A.2 Pair Trade Matrix
- Single matrix with 3-4 pair candidates
- Cells include: setup skew, correlation/idio split, β-neutral sizing, verdict

### A.3 Earnings Sequencing
- Comp set print dates
- Sequencing implications (sympathy / unwind)

### A.4 Squeeze Risk
- SI table (shares, % float, DTC, range, period change)
- Read paragraph
```

---

## 5. Style Guidance

**Writing shape (enforced in `scripts/style_linter.py`):**
- **Takeaways are the distilled thesis and MUST be shorter than the Overview** — the
  Overview is the substance/meat. Lint **S-04** hard-blocks when Takeaways ≥ Overview.
- Weave qualitative + quantitative together; every takeaway is a meaningful point, not filler.
- **No filler / word-salad** — cut generic valuation lines (e.g. "street at/below spot,
  fairly-to-richly valued into a high-variance, high-beta print"); state the
  "no differentiated view vs consensus" point ONCE. Lint **L-15**.
- **No internal process/system language** — no model-housekeeping or connector references;
  frame valuation as a market observation. Lint **L-14**.
- **Comp readthrough:** when comps have already reported, incorporate the readthrough in
  the Overview and Data Monitoring (workflow step [4b]).

- **Voice:** Match your prior previews. Direct, no fluff, abbreviations OK (HSD/MSD/LSD/LDD%, q/q, y/y, OM%, EBIT, FX, etc.).
- **Length:** Body should fit ~5-6 pages PDF; appendix ~2-3 pages. Total target 7-9 pages.
- **No broker name spam:** Don't list every sell-side estimate by firm. Aggregate to "consensus tilts toward modest beat" type framing.
- **No price targets in alt data table:** Focus on volume trends, demand signals, mgmt tone.
- **No emojis in tables:** Use CSS-class colored text (Positive=green, Neutral=black, Negative=red).
- **Bold sparingly:** Use bold for key numbers and headers; don't bold whole sentences.
- **Tables before prose:** Wherever a table can replace prose, use the table.
- **Self-aware caveats welcome:** If your variant is conservative on a metric, say so explicitly with the rationale.

---

## 6. Quality / Audit Checklist

Before delivering, verify:

- [ ] **STORY DOSSIER built and read before drafting** (per workflow step [1.5]). All Reference Files + latest 10-Q rev recognition footnote + most recent earnings call transcript covered. Dossier sections (story, bear components, bull components, rally drivers, accounting nuances, open questions) all populated. The draft does NOT contradict the dossier on any factual or framework claim. Research-notes content folded into bear/bull thesis components and accumulated context.
- [ ] Position size in the Decision Table reflects `position.json` data (if provided) — NOT a `[pending]` placeholder. If no position.json, mark "not provided".
- [ ] All figures cited have a source + date
- [ ] No "TBD" markers in cells where data is actually available
- [ ] No references to "data you need to provide" in the body (only in input checklist)
- [ ] No mentions of educational material pending or other meta-commentary
- [ ] Score logic shown (D, C, composite)
- [ ] Triangulation surfaces disagreements explicitly, doesn't bury them
- [ ] Decision table at top is filled (or marked as user input pending if standalone)
- [ ] PDF renders clean (no broken table layouts, no orphan section headers, no overflow)
- [ ] Color classes render (Positive=green, Negative=red, Neutral=black) — emojis don't render in PDF
- [ ] Page count target met (7-9 pages)
- [ ] **GUT-CHECK PASSED: Every revenue/volume row in the KPI tables has an implied y/y growth number, and the Gut Check paragraph explicitly reconciles the implied growth against (a) management guide range, (b) alt-data signals, (c) volume-vs-ASP decomposition. If any number doesn't pass the gut check, flag it explicitly rather than presenting it as definitive.**
- [ ] **PANDOC RENDERED CORRECTLY: Use `--from markdown-tex_math_dollars` flag on every pandoc call. Without it, unescaped `$` characters in tables trigger TeX math mode and entire rows between paired `$` signs get swallowed. Verify after rendering: count rows in each rendered table; compare against markdown source; if mismatch, the dollar-sign math bug is the cause.** The runner enforces strict per-table comparison via `scripts/render_verify.py` — every row mismatch BLOCKs and identifies the offending table by header text.

**Automated audit gate IDs** — each item below is enforced deterministically in `Audit Agent/audit_agent.py` and contributes severity=fail items to the `block_on_fail_severity` gate when violated:

| Gate ID | What it catches | Implemented in |
|---|---|---|
| F-01..F-04 | Quote and citation verification (verbatim, paraphrase, scare-quote distinction) | `score_facts` |
| N-01..N-07 | Figure verification (value-in-source, value-in-data, derived arithmetic, unit match, cross-section consistency) | `score_figures` |
| S-01..S-04 | Source attribution (anonymous source deducts, citation marker presence, management-only over-reliance) | `score_sources` |
| L-01..L-02 | Logic — cross-section number contradictions, directional inconsistencies | `score_logic_v02` |
| P-01..P-04 | Speculation — forward-period assertions without uncertainty markers, superlatives, probability-without-basis | `score_speculation_v02` |
| **D-00-MANIFEST-PRESENT** | data_manifest.json exists at expected path | `score_data_manifest` |
| **D-01-FRESH** | No required-metric entry exceeds the freshness threshold (default 24h) | `score_data_manifest` |
| **D-02-MANIFEST-COVERAGE** | Every metric in `config.yaml.key_metrics` has at least one manifest entry for the focus period | `score_data_manifest` |
| **D-03-FISCAL** | Preview header / manifest / config fiscal-period assertions agree (after canonical-form normalization) | `score_fiscal_period_consistency` |
| **D-04-COMPMIX** | No peer ticker appears in the same sentence as a disallowed-for-its-role term | `score_compmix_consistency` |
| **D-05-YOY** | Multiple `($-value, y/y%)` pairs in a single KPI table row imply prior-year actuals that agree within 1% | `score_yoy_arithmetic` |

The gates are additive. They do not alter the 100-point base score; each violation contributes a severity=fail item that hard-blocks delivery via `block_on_fail_severity=True` (the runner default).

**Standard rendering pipeline:**

```bash
pandoc input.md -o output.html --standalone --css style.css --from markdown-tex_math_dollars
python3 -c "from weasyprint import HTML, CSS; HTML('output.html').write_pdf('output.pdf', stylesheets=[CSS('style.css')])"
```

---

## 7. Optional External Data Inputs

Where you have external data, you supply it; otherwise the agent stubs the section. Each manual input has a clear "what shape of data we need" definition:

| Data | How supplied | Shape needed |
|---|---|---|
| Short interest | Paste / file | shares short, % float, DTC |
| Implied move / historical reaction | Paste / file | implied move %, last-N-quarter reactions |
| Vol surface | Screenshots / file | term structure + skew |
| Sell-side research PDFs | Drop in Reference Files | broker note PDFs |
| Positioning notes | Paste | free-form |
| Whisper numbers | Paste | metric + value |
| Borrow rates | Paste | rate + utilization |

If an optional input is absent, the corresponding section degrades gracefully and is flagged "not provided".

---

## 8. Deployment / Repeatability

To deploy this preview workflow on a new ticker:

1. Create folder: `workspace/{TICKER}/`
2. Drop or generate `config.yaml` (per §3 template)
3. Optionally drop initial seed data in `Reference Files/` (model, prior research, prior previews)
4. Trigger: `prep earnings for {TICKER}`
5. Agent runs the workflow, prompts for inputs in symbiotic mode

For a ticker without any history, standalone mode works as a first-pass triage. Symbiotic mode upgrades the output as your inputs land.

---

## 9. XYZ as Worked Example

Use a generic ticker `XYZ` as the prototype. Reference the worked markdown for the canonical structure: `workspace/XYZ/outputs/{PERIOD}_PREVIEW.md`.

Key decisions that should generalize:
- Per-period KPI tables (current Q, Q+1, FY) — not one combined table
- Company Guide column BEFORE the variant column
- No EBITDA row (by preference)
- Direction column color-coded text (no emojis)
- Tactical lens consolidated as one bullet in Overview, not in Takeaways
- Appendix ordered by importance (Options first), not by alphabetical or numerical
- Bite-sized takeaway bullets, not multi-sentence paragraphs
- 5-6 word punchy bullet headers in Overview

---

## 10. Infrastructure

This section documents the deterministic infrastructure that backs the canonical workflow above. It supplements §2 (workflow) and §6 (audit checklist).

### 10.1 Path resolution

`Earnings Analysis Agent/scripts/_paths.py` is the single source of truth for repo-anchored paths. All consumers (`preview_runner`, `sell_side_synthesizer`, `primary_source_puller`, `data_manifest`) import from here. The module asserts the resolved repo root contains `Earnings Analysis Agent/PREVIEW_AGENT_SPEC.md`; if not, it raises `RepoRootResolutionError` at import time (loud failure rather than silent path drift).

### 10.2 Data manifest

Every preview run maintains a provenance manifest at:

```
workspace/{TICKER}/data/data_manifest.json
```

Schema lives at `Earnings Analysis Agent/schemas/data_manifest.schema.json`. Required top-level fields: `manifest_version`, `ticker`, `fiscal_period_in_focus`, `created_at`, `updated_at`, `entries`. Each entry records a single data pull from a source (IR site, SEC filings, manual consensus) with `source_id`, `tool_name`, `ticker`, `period`, `metric`, `value`, `unit`, `pulled_at`, optional `source_url`, optional `notes`.

The manifest is initialized once the canonical fiscal period is resolvable (from the IR print date or config — see §10.3). The contract: every metric pulled must produce one append to the manifest using `data_manifest.append_entry(manifest_path, entry)`. Schema validation runs on every load and append; a malformed entry raises `ValueError` and the on-disk manifest is not touched.

### 10.3 Fiscal-period derivation

The canonical fiscal period for a run is resolved by `PreviewRunner._resolve_fiscal_period()`, which combines two sources:

1. **Print-date record** at `data/calendar_event.json` (preferred, authoritative on print dates; populated from the company IR site / 8-K). Expected shape:
   ```json
   {
     "ticker": "XYZ",
     "fetched_at": "...",
     "next_print": {
       "calendar_quarter": 1, "calendar_year": 2026,
       "fiscal_quarter": 1, "fiscal_year": 2026,
       "date": "2026-05-08", "time_of_day": "AMC"
     }
   }
   ```
2. **`config.yaml`** `fiscal_period_in_focus` / `fiscal_period` / `quarter` fields (fallback). Legacy forms (`1Q26`, `1Q2026`, `2026/1F`) are normalized to canonical calendar-quarter notation `C{q}Q{yy}` via `scripts/fiscal_period.normalize_fiscal_period`.

Resolution precedence: both-agree → that value, both-disagree → the print-date record wins (and discrepancy is recorded; D-03-FISCAL hard-blocks via the audit), record-only → record, config-only → config, neither → None (filename degrades to `UNKNOWN_PREVIEW.md`; downstream gates BLOCK).

The canonical period drives the output filename: `outputs/{C_PERIOD}_PREVIEW.md` (and `.pdf`).

### 10.4 Provenance file

Every CLI invocation of `preview_runner.py` writes a provenance record at:

```
workspace/{TICKER}/outputs/_provenance_{run_id}.json
```

Schema (informal): `schema_version`, `run_id`, `ticker`, `mode`, `started_at`, `ended_at`, `env` (python/jsonschema/pyyaml/platform versions), `stages` (per-stage outcomes with timestamps), `artifacts` (per-artifact size/mtime/sha256), `audit_score`, `gate`, `fail_severity_count`, `manifest_path`, `manifest_sha256`. The record is best-effort: failures inside provenance helpers never propagate; they accumulate in `_record_errors`.

Useful for: retrospective audit and diff-vs-prior-run comparisons.

### 10.5 Subprocess failure logs

Every subprocess call from `preview_runner` (lint, audit, cons-context, pandoc, weasyprint, sell-side plan, primary-source plan) routes through `PreviewRunner._run_subprocess()`. On non-zero return or timeout, the full command + stdout + stderr are written to:

```
workspace/{TICKER}/outputs/_subprocess_failures/{stage}_{run_id}.log
```

`block_reason` cites the log path so you can diagnose without re-running. Per-stage timeouts: lint 30s, audit 120s, cons-context 30s, pandoc 120s, weasyprint 300s.

### 10.6 Render verification

`scripts/render_verify.py` performs strict per-table row-count comparison between source markdown and rendered HTML. Every table is identified by header text; any mismatch in table count or per-table row count BLOCKs the render stage with the offending table named. Replaces an earlier 5-row tolerance heuristic, which could pass a draft missing real rows when the pandoc `tex_math_dollars` bug only swallowed a few cells.

### 10.7 Sell-side note schema validation

Per-broker JSON extractions saved to `synthesis/{broker}_{date}.json` are validated against `schemas/sell_side_note.schema.json` at aggregate time. Malformed entries (parse error, top-level non-object, missing required `broker`/`date`) become `validation_failures` in the synthesis output. Notes that pass schema but contain no thesis content are flagged as `thin_extractions` — included in ratings/PT aggregation but surfaced separately so you see the extraction coverage gap.

### 10.8 Test suite

`Earnings Analysis Agent/tests/` holds pytest tests covering every module above. Run with:

```bash
cd "Earnings Analysis Agent" && python3 -m pytest tests/
```

Tests are written to be deterministic — every time-sensitive helper accepts an injected `now` parameter so wall-clock state doesn't affect test results.
