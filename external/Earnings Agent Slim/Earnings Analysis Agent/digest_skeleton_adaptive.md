# {COMPANY_NAME} — {PERIOD} Print Digest

**Print:** {PRINT_DAY} {PRINT_DATE} {AMC_OR_BMO}, {PRINT_TIME_ET} ET release | **Call:** {CALL_TIME_ET} ET | **Last close ({LAST_CLOSE_DATE}):** ${PRE_PRINT_PRICE} | **YTD:** {YTD_RETURN_PCT}% | **Since prior print:** {SINCE_PRIOR_PRINT_RETURN_PCT}%
**Implied move:** ±{IMPLIED_MOVE}% (${IMPLIED_LOW}–${IMPLIED_HIGH}) | **5y avg abs T+1:** {AVG_ABS_REACTION}% | **Surp→px corr:** {SURP_PX_CORR_NOTE}

---

<table class="decision-table">
<tr><th>Field</th><th>Value</th></tr>
<tr><td><strong>Recommended Action</strong></td><td><strong class="{ACTION_CLASS}">{POST_PRINT_ACTION}</strong> — {ACTION_RATIONALE_ONE_LINE}</td></tr>
<tr><td><strong>Headline Read</strong></td><td><strong class="{HEADLINE_CLASS}">{HEADLINE_READ_ONE_LINE — anchored to day-of binary metric outcome}</strong></td></tr>
<tr><td><strong>Day-of-Trade Triggers</strong></td><td>{DAY_OF_TRADE_TRIGGERS_ONE_LINE — what the tape is likely to do at the open}</td></tr>
<tr><td><strong>Preferred Structure</strong></td><td>{STRUCTURE_ONE_LINE — short call spread / put spread / outright + tenor + strikes}</td></tr>
</table>

<!-- FORMATTING NOTES (INTERNAL — not rendered):
     1. Decision table cells = ONE line each. Long rationale belongs in Synthesis, not stuffed in cells.
     2. Do NOT include rows like "Pre-Print Decision", "Earnings Preview Score", "Recommended Position Size (from preview)" — those are pre-print framing pulled from internal scaffolding and should not be reproduced in the post-print deliverable.
     3. Do NOT use any named-author action label — circulation copies use "Recommended Action".
-->

---

## Synthesis — Day-of-Trade Verdict

**Story.** {STORY_PARAGRAPH — 4-6 sentences. Open with the day-of binary outcome (drawn from `day_of_binary.primary` in salient_kpis). Cover the print's overall composition (drawn from `day_of_binary.composition_test`). Note any guide action. End with capital allocation if material. *[STATED]* / *[INFERRED]* tags inline as appropriate.}

**{SALIENT_KPI_1_LABEL} ({SALIENT_KPI_1_DAY_OF_FLAG_IF_BINARY}).** {SALIENT_KPI_1_PARAGRAPH — anchor on this metric specifically. Beat/miss vs each baseline (variant / Street / Guide). Decompose the result. Tie back to the composition test from `salient_kpis[0].composition_relevance`. *[STATED]* / *[INFERRED]* as needed.}

**{SALIENT_KPI_2_LABEL} — {SALIENT_KPI_2_THESIS_TIE_IN}.** {SALIENT_KPI_2_PARAGRAPH — same structure. Tie to thesis claim if applicable.}

**{SALIENT_KPI_3_LABEL} {SALIENT_KPI_3_QUALIFIER}.** {SALIENT_KPI_3_PARAGRAPH — same structure.}

[Optional fourth salient_kpi paragraph if 4+ declared in priority order.]

**Capital allocation + capex.** {CAPITAL_ALLOCATION_PARAGRAPH — buyback pace, dividend, capex framework, balance sheet posture. Include only if material to this print's read.}

**What could be wrong pending call:**
- **{UNCERTAINTY_1}** — Watch on the call: {SPECIFIC_COMMENTARY_THAT_RESOLVES} could shift the verdict to {DIRECTION}.
- **{UNCERTAINTY_2}** — Watch on the call: {SPECIFIC_COMMENTARY_THAT_RESOLVES}.
- **{UNCERTAINTY_3}** — Watch on the call: {SPECIFIC_COMMENTARY_THAT_RESOLVES}.

---

## Guide Section

### Guide Delta

| Period | Metric | Prior Guide | New Guide | Read |
|---|---|---|---|---|
| {GUIDE_PERIOD_1} | {GUIDE_METRIC_1} | {PRIOR_GUIDE_1} | {NEW_GUIDE_1} | <span class="{GUIDE_DIRECTION_CLASS_1}">**{GUIDE_READ_1_ANCHORED_TO_CONS}**</span> |
| {GUIDE_PERIOD_2} | {GUIDE_METRIC_2} | {PRIOR_GUIDE_2} | {NEW_GUIDE_2} | <span class="{GUIDE_DIRECTION_CLASS_2}">**{GUIDE_READ_2}**</span> |
| {ROWS_FOR_EACH_GUIDED_METRIC_THE_COMPANY_ISSUED} | | | | |

### Implied Consensus Revisions

- **{PERIOD_1} cons {METRIC}:** {DIRECTION + MAGNITUDE + REASON tied to specific guide line}
- **{PERIOD_2} cons {METRIC}:** {DIRECTION + MAGNITUDE + REASON}
- **Variant alpha:** {WHERE_VARIANT_ALPHA_REMAINS_VS_CONS}
- {ADD_BULLETS_AS_NEEDED_PER_GUIDED_PERIOD}

### Achievability

**{CURRENT_Q} (in the books):** {CLEAN_BEAT_OR_NUANCE — implied y/y growth, cushion vs alt data, comp difficulty, name's historical pattern of beating own guide}

**{NEXT_Q} (forward guide):** {ACHIEVABILITY_OF_NEW_FORWARD_GUIDE — implied range, comp setup, what cushion vs cons looks like}

**{CURRENT_FY} + 2H math:** {ACHIEVABILITY_OF_FY_GUIDE — implied 1H/2H split, 2H exit-rate required, comp difficulty by remaining quarter, multi-line view (rev/volume/GM/OM separately)}

**Back-half loading verdict:**
- **Rev:** {NOT_BACK_LOADED | BACK_LOADED_BY_DESIGN | BACK_LOADED_BY_ASPIRATION — with quantification}
- **OM:** {NOT_BACK_LOADED | BACK_LOADED_BY_DESIGN | BACK_LOADED_BY_ASPIRATION — with quantification}
- {ADDITIONAL_LINES_AS_NEEDED}

---

## Beat/Miss Scorecard

| Metric | Actual | Cons | Δ vs Cons | Variant | Δ vs Variant | y/y | Guide | Read |
|---|---|---|---|---|---|---|---|---|
| {SALIENT_KPI_1_LABEL} | {ACTUAL_1} | {CONS_1} | <strong class="{DELTA_CLASS_1}">{DELTA_VS_CONS_1}</strong> | {VAR_1} | {DELTA_VS_VAR_1} | {Y_Y_1} | {GUIDE_1} | <strong class="{READ_CLASS_1}">{READ_1}</strong> |
| {SALIENT_KPI_2_LABEL} | {ACTUAL_2} | {CONS_2} | <strong class="{DELTA_CLASS_2}">{DELTA_VS_CONS_2}</strong> | {VAR_2} | {DELTA_VS_VAR_2} | {Y_Y_2} | {GUIDE_2} | <strong class="{READ_CLASS_2}">{READ_2}</strong> |
| {ROW_PER_SALIENT_KPI} | | | | | | | | |
| {STANDARD_FOUNDATIONAL_ROWS_IF_NOT_ALREADY_SALIENT — e.g. Total Revenue, Non-GAAP EPS} | | | | | | | | |

**Channel + cohort breakdown** (where relevant): {COMPANY_SPECIFIC_BREAKDOWN — e.g. cohort+channel+region splits; clinical vs research splits; subscription vs one-time mix; membership by segment.} *[STATED or INFERRED]*

**Gut-check.** {EXPLICIT_GUT_CHECK_PARAGRAPH — cross-reference print's implied y/y growth vs (a) prior guide, (b) variant, (c) alt-data signal. Surface inconsistencies. Decompose the beat: how much from rev, how much from margin, how much below-the-line. *[INFERRED]* tag if decomposition requires 10-Q.}

---

{IF conditional_sections.include_cash_flow_walk == true:}

## Cash Quality + Working Capital Flags

| Line | {PERIOD} | Source / formula |
|---|---|---|
| Cash beginning | {CASH_BEG} | PR balance disclosure *[STATED]* |
| Cash ending | {CASH_END} | PR balance disclosure *[STATED]* |
| **Net cash change** | **{NET_CASH_CHANGE}** | direct math *[INFERRED]* |
| GAAP NI | {NI} | PR *[STATED]* |
| CFO | {CFO} | PR cash flow statement *[STATED]* |
| Capex | {CAPEX} | PR *[STATED]* OR FY guide × Q-share *[INFERRED]* |
| Buyback | {BUYBACK} | PR *[STATED if disclosed]* |
| **Implied "other"** | **{OTHER}** | residual *[INFERRED]* |

**Read.** {CASH_QUALITY_VERDICT — magnitude of "other" residual as % of NI. Flag if > 50% of NI. Note 10-Q filing date for full bridge. Identify what call disclosure resolves the gap.}

{ELSE: section omitted entirely.}

---

## Watch-List Reconciliation + Call Questions

<div class="addressed-topic"><strong>ADDRESSED — substantive in PR:</strong>
{LIST_OF_ITEMS_PR_ADDRESSED — pulled from the standing "What we will be listening for" set intersected with PR content}
</div>

<div class="partial-topic"><strong>PARTIAL — addressed but light:</strong>
{LIST_OF_ITEMS_MENTIONED_BUT_NOT_QUANTIFIED}
</div>

<div class="absent-topic"><strong>ABSENT — call questions to ask ({CALL_TIME_ET} ET):</strong>

{NUMBERED_LIST_FROM_absent_from_pr_template_questions — each item gets a specific question framed for the call}
</div>

---

## Trade Construction + Positioning

<div class="action-box"><strong><span class="{ACTION_CLASS}">{POST_PRINT_ACTION}</span></strong> — {ACTION_RATIONALE_FULL — tie to historical reaction calibration if applicable}.

<strong>Sizing framework:</strong>
<ul>
<li>{SIZING_CALC_AT_KEY_PRICE_LEVELS — e.g. trim trigger, current mark, implied move band}</li>
<li>{TRIGGER_BASED_INSTRUCTION_1}</li>
<li>{TRIGGER_BASED_INSTRUCTION_2}</li>
<li>{PREFERRED_STRUCTURE_DETAIL — strikes, expiries, rationale}</li>
<li>{POST_CALL_RE_EVALUATION_GUIDANCE}</li>
</ul>

<strong>Confidence:</strong> <span class="{CONFIDENCE_CLASS_1}">{CONFIDENCE_LEVEL_1}</span> on {AREA_1}; <span class="{CONFIDENCE_CLASS_2}">{CONFIDENCE_LEVEL_2}</span> on {AREA_2}. Primary uncertainty: {KEY_UNCERTAINTY}.
</div>

**Idio alpha thesis (post-print):** {CONFIRMED | BROKEN | AMBIGUOUS — with specific reasoning tied to which thesis claims got validated/invalidated by the print}.

{IF conditional_sections.include_pair_view_extended == true:}
**Pair view:** {PAIR_TRADE_READ — which leg moved more than expected; β-neutral sizing implication; impact of this print on the pair.}
{ELSE: skip}

**Squeeze:** SI {SI_PCT}% / {DTC} DTC pre-print. {SQUEEZE_DIRECTION_INFERRED_FROM_PRINT}.

{IF conditional_sections.include_squeeze_detail == true:}
{ADDITIONAL_SQUEEZE_DETAIL — borrow rate trends, options skew, gamma positioning if relevant}
{ELSE: one-line squeeze read above is sufficient}

**Implied move:** ±{IMPLIED_MOVE}% pre-print. {SCENARIO_MAPPING — base case / bull case / bear case AH range. Anchor to historical reaction calibration.}

**Dispersion read:** {SECTOR_PEER_DISPERSION_NOTE — if relevant pair / sector peers reported recently and this print creates/reduces dispersion.}

---

## Appendix A — Historical Earnings Reaction Calibration

| Quarter | Cons EPS | Actual | % Surp | T+1 px | Notes |
|---|---|---|---|---|---|
| {Q-4} | {CONS_4} | {ACTUAL_4} | {SURP_4} | {PX_4} | {NOTES_4} |
| {Q-3} | {CONS_3} | {ACTUAL_3} | {SURP_3} | {PX_3} | {NOTES_3} |
| {Q-2} | {CONS_2} | {ACTUAL_2} | {SURP_2} | {PX_2} | {NOTES_2} |
| {Q-1} | {CONS_1} | {ACTUAL_1} | {SURP_1} | {PX_1} | {NOTES_1} |
| **{Q-this_print}** | **{CONS_THIS}** | **{ACTUAL_THIS}** | **{SURP_THIS}** | **TBD** | **{NOTES_THIS}** |

{REACTION_CALIBRATION_PARAGRAPH — does this print fit the historical pattern? Closest analog quarter? Asymmetry vs that analog? Implied AH range mapping.}

## Appendix B — Visibility Cues from PR Language

- **Guide range tightness:** {QUANTIFY_GUIDE_RANGE_WIDTH — % width signals confidence}
- **Range vs point estimates:** {WHICH_METRICS_GUIDED_AS_POINTS_VS_RANGES — points = stronger commitment}
- **CEO confidence words:** {QUOTE_CEO_LANGUAGE_AND_CHARACTERIZE}
- **CFO confidence words:** {QUOTE_CFO_LANGUAGE_AND_CHARACTERIZE}
- **Macro hedge language:** {WHAT_MACRO_FACTORS_NAMED_AS_HEDGES}
- **NEW disclosure metrics:** {ANY_NEW_KPIs_OR_METRICS_INTRODUCED}
- **Risk factor changes:** {ADDITIONS_OR_REMOVALS_FROM_STANDARD_RISK_FACTOR_LIST}

<!--
INTERNAL TEMPLATE NOTES (NEVER RENDER — production_ready_check halts the build if these reach final markdown):

1. PRE-FLIGHT (before drafting):
   - Read the standing watch-list and salient_kpis from config + most recent preview
   - Resolve conditional_sections.include_* flags
   - Build digest_baseline.json (cons/variant/guide/positioning spine)

2. SCAFFOLDING:
   - Bind every {SALIENT_KPI_N_*} placeholder to the resolved priority-order KPIs
   - One paragraph per top 3-4 KPIs in Synthesis
   - One row per KPI in Beat/Miss Scorecard

3. CONDITIONAL SECTIONS:
   - Remove sections gated to false (Cash Quality, Pair View, Squeeze Detail)

4. PRE-RENDER AUDIT (all gates must pass):
   - salient_kpi conformance (scorecard + synthesis + watch-list)
   - day_of_binary anchored in synthesis paragraph 1
   - composition_test language appears verbatim
   - conditional sections respect their flags
   - production_ready_check: no forbidden phrases (see production_ready_check.py)
   - audit_agent.py + digest_adversarial.py both PASS

5. PROHIBITED IN OUTPUT (production_ready_check will halt the build):
   - "Bias Pre-Commitment" / "Going in I'm leaning" / "I'm at risk of" / "Pre-commit horizon"
   - Any named-author action label
   - "Pre-Print Decision (from preview)" / "Earnings Preview Score" rows in digest header
   - "[user —" / "user pending" / "[PENDING — Sub-agent" / "[PENDING]" / "LLM_FILL"
   - Internal version references (V1/V2/V3/...; "from V10 preview"; "prior draft")
   - "PRESTAGED" naming in delivered filenames
   - "End of Stage 1. Stage 2 will compute..." / "Audit metadata" / "Template Usage Notes"
   - First-person commentary about the drafting process

6. DELIVERABLE FILENAME:
   - `{TICKER}_{PERIOD}_PRINT_DIGEST.{md,pdf}` (no V1/V2/V3 in delivered name)
   - Internal versioned outputs OK in `digest_work/` but not in `outputs/` final set
-->
