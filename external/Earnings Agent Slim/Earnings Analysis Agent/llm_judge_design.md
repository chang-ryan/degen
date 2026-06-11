# L3 — LLM Judge Layer Design

## Purpose

Catch logical inference errors that the deterministic L1/L2 gates cannot:
- Correct math, wrong conclusion ("+9% YoY, growth accelerating" when context shows decel)
- Unsupported inferences ("management dodged" without a question-answer mismatch)
- Subtle framing errors (anchoring to the most flattering comp)
- Missing counterfactuals (claim that doesn't address an obvious objection)

These require semantic understanding, not pattern matching.

## Architecture

A separate Claude (Haiku-tier for cost; can promote to Sonnet for high-stakes
prints) runs as a final pre-render gate. It does NOT see the underlying
research or any prior context — only the digest output + a structured
manifest of the inputs. The judge's job is to find specific claims that
don't follow from the inputs.

## Integration point

Add to `baseline_audit.run_audit()` as the final gate:

```python
gates = [
    # ... existing L1/L2 gates ...
    gate_llm_judge(md_text, manifest, model="claude-haiku-4-5"),
]
```

`gate_llm_judge` makes an API call to Claude with the prompt below. Returns
the same `{gate, rule, status, findings}` shape as other gates.

## Prompt template

```
You are an adversarial reviewer auditing an investment-research earnings
digest. Your job is to find specific claims that don't follow from the
cited evidence, NOT to assess whether the overall thesis is correct.

You will receive:
1. The full digest markdown
2. A structured manifest of the underlying numerical inputs
   (e.g., {"q1_26_rev": 44.203, "q1_25_rev": 47.831, ...})

For each claim of the form "growth is accelerating/decelerating",
"momentum is building/slowing", "execution is improving/deteriorating",
"management dodged/answered", "narrative shifted":

1. Identify the specific numerical or textual evidence the digest cites
   for the claim.
2. Determine whether the cited evidence supports the claim's direction.
3. Where possible, identify a piece of evidence in the manifest that
   CONTRADICTS the claim and is NOT addressed in the digest.

Format your output as JSON:
{
  "logical_errors": [
    {
      "claim": "<quoted from digest>",
      "section": "<section name>",
      "cited_evidence": "<what the digest cites>",
      "issue": "<specific reason the conclusion doesn't follow>",
      "contradicting_evidence": "<from manifest, if available>",
      "severity": "BLOCK | WARN | FYI"
    }
  ],
  "unaddressed_counterfactuals": [
    {
      "thesis_claim": "<from digest>",
      "obvious_objection": "<what a skeptic would ask>",
      "is_addressed": false,
      "severity": "WARN | FYI"
    }
  ]
}

Constraints:
- Do NOT flag stylistic preferences or arguable judgments — only logical
  errors and unaddressed counterfactuals.
- Cite specific quotes; do not paraphrase.
- If the digest is logically sound, return empty arrays.
- Set severity=BLOCK only when the math/logic is demonstrably wrong;
  WARN for weak inferences; FYI for missing-but-defensible context.
```

## Sample failure case (XYZ Stage 1)

If the Stage 1 digest had said:

> "Adjusting for the $8M product GTN charge brings Q1 to $52.2M, +9.1% YoY
> vs Q1'25 $47.8M. This confirms management's accelerating-growth narrative."

With manifest:
```json
{
  "q1_26_rev_normalized": 52.2,
  "q1_25_rev": 47.831,
  "fy26_guide_mid": 357.5,
  "fy25_actual": 272.3,
  "implied_fy26_growth_rate": 0.31
}
```

The judge should output:
```json
{
  "logical_errors": [{
    "claim": "This confirms management's accelerating-growth narrative",
    "cited_evidence": "$52.2M, +9.1% YoY",
    "issue": "Normalized YoY of +9.1% is well below the +31% YoY growth implied by the FY26 mid-guide ($357.5M vs $272.3M FY25). A +9.1% Q1 against an easy comp (Q1'25 destocking) does not support 'accelerating' relative to the FY trajectory.",
    "contradicting_evidence": "Implied FY26 growth rate of 31% per guide vs Q1 actual normalized rate of 9.1%",
    "severity": "BLOCK"
  }],
  "unaddressed_counterfactuals": []
}
```

## Cost / latency budget

- Haiku 4.5 input: ~$1/MTok, output: ~$5/MTok
- Typical digest ~5K tokens + manifest ~2K tokens = ~7K input
- Expected output ~1K tokens
- Cost per audit: ~$0.012
- Latency: 3-8 seconds

Acceptable for pre-render pass. NOT acceptable for in-flight retry loops.

## Failure modes

1. **False positives.** Judge flags valid claims as logically wrong. Mitigation:
   require severity=BLOCK to actually block render; WARN/FYI are advisory.
2. **False negatives.** Judge misses real logical errors. Mitigation: this is
   a defense-in-depth layer; L1/L2 catch the mechanical class, L3 catches the
   semantic class — neither is sufficient alone.
3. **Prompt injection from digest content.** Mitigation: render markdown to
   plain text before passing to judge; strip any text matching prompt-like
   patterns ("ignore all previous instructions", etc.).
4. **Judge cost runaway.** Mitigation: hard cap on input tokens (truncate at
   15K); judge only runs once per render attempt, not per gate.

## Why not run for every research output

Adversarial review is most valuable when:
- The output makes specific directional claims with consequence
- The underlying inputs are structured enough to fit in a manifest

It's least valuable for:
- Exploratory research notes (low downside; reviewing in real time)
- Pure data pulls (no claims to audit)
- Conversational responses (no formal claims structure)

Run L3 only on Stage 2 (Rapid Digest) and Stage 3 (Recap 1) outputs. Skip
for Stage 4 (Deep Recap) until proven valuable — by then you have
had multi-day review.

## What this still won't catch

- **Cherry-picked time windows** when both windows are cited but framed
  selectively. The judge needs the manifest to include "alternative comp
  periods" — i.e., what would the YoY be vs Q2'25? Q3'25? — to detect
  the strongest counter-comp.
- **Stale memory anchors.** L2's `gate_memory_freshness` is the right tool;
  L3 can't easily detect "you cited memory from 30 days ago without
  re-verifying."
- **Quote misattribution in transcripts.** Cross-source diff (when a second
  authoritative transcript source becomes available) is more reliable
  than L3 inference.

## Implementation status

This file is a design doc only. Implementation requires:
1. Anthropic API key wired into the Earnings Agent runtime
2. Manifest schema extension to include "judge-relevant" inputs
3. `gate_llm_judge` function in `baseline_audit.py`
4. Render pipeline integration (call before pandoc, block on BLOCK severity)

Estimated implementation: 4-6 hours including testing on a corrected
digest (should produce empty findings) and against a synthetic mis-inference
case (should produce a BLOCK finding).
