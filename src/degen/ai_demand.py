"""AI-infra demand / commoditization gauge — instruments the central thesis
question: *does the economic value match the infra investment in this timeframe?*
(See docs/theses/ai-infra-cycle-top.md.)

WHAT THIS MEASURES (free, no key) — the **price / commoditization** side, via
OpenRouter's public `/models`: the cost of capable ("frontier-class") intelligence
and how fast it's collapsing. This is the **Jevons denominator** — if intelligence
approaches free, the $700B+/yr infra build needs *volume* to more than compensate
for price, or the ROI never shows up.

WHAT IT DOES NOT MEASURE — token **volume** (the demand *numerator*). OpenRouter's
usage/rankings require auth; set `OPENROUTER_API_KEY` to wire that later, or track
`openrouter.ai/rankings` by hand. Lab ARR is deliberately NOT used as a demand
proxy — it's contaminated by VC-subsidized startup burn + circular financing.

Snapshot the `frontier_cheapest` over time (the daily brief does) to watch the
deflation trend: falling = commoditizing fast (volume must outrun it).

`uv run python -m degen.ai_demand`
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Frontier-family id hints — capable models whose price is the one that matters
# for "cost of useful intelligence." Tune as families rename; `frontier_count`
# surfaces whether the matcher is still finding them.
_FRONTIER_HINTS = (
    "claude-opus",
    "claude-sonnet",
    "gpt-5",
    "gpt-4o",
    "/o3",
    "/o4",
    "gemini-2",
    "gemini-3",
    "grok-4",
    "deepseek-r",
    "llama-4",
)


@dataclass(frozen=True, slots=True)
class AiDemand:
    model_count: int  # total models on OpenRouter (proliferation proxy)
    frontier_count: int  # how many matched the frontier hints (matcher health)
    frontier_cheapest: float | None  # cheapest frontier-class completion, $/Mtok
    frontier_median: float | None  # median frontier-class completion, $/Mtok
    commodity_floor: float | None  # cheapest completion price anywhere, $/Mtok


def _mtok(pricing: dict, key: str) -> float | None:
    try:
        v = float(pricing[key]) * 1_000_000
        return v if v > 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def ai_demand() -> AiDemand | None:
    """Pull OpenRouter /models and summarize the price landscape (the Jevons denom)."""
    try:
        req = urllib.request.Request(_MODELS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            models = json.loads(resp.read().decode())["data"]
    except Exception:
        return None

    all_comp: list[float] = []
    frontier: list[float] = []
    for m in models:
        c = _mtok(m.get("pricing", {}), "completion")
        if c is None:
            continue
        all_comp.append(c)
        if any(h in m.get("id", "") for h in _FRONTIER_HINTS):
            frontier.append(c)

    frontier.sort()
    return AiDemand(
        model_count=len(models),
        frontier_count=len(frontier),
        frontier_cheapest=frontier[0] if frontier else None,
        frontier_median=frontier[len(frontier) // 2] if frontier else None,
        commodity_floor=min(all_comp) if all_comp else None,
    )


def main() -> int:
    d = ai_demand()
    if d is None:
        print("ai_demand: unavailable (OpenRouter fetch failed)")
        return 1
    print("=== AI-infra commoditization gauge (price side / Jevons denominator) ===")
    print(f"  models on OpenRouter : {d.model_count}  (frontier-class matched: {d.frontier_count})")
    fc = f"${d.frontier_cheapest:.2f}" if d.frontier_cheapest is not None else "n/a"
    fm = f"${d.frontier_median:.2f}" if d.frontier_median is not None else "n/a"
    cf = f"${d.commodity_floor:.3f}" if d.commodity_floor is not None else "n/a"
    print(f"  frontier-class $/Mtok: cheapest {fc}   median {fm}")
    print(f"  commodity floor $/Mtok: {cf}  (cheapest capable-ish anywhere)")
    print("  read: snapshot the trend — falling = commoditizing, volume must outrun it.")
    print("  NB: PRICE side only. Token *volume* (demand) needs OPENROUTER_API_KEY / manual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
