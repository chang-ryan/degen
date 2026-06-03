"""Portfolio heat: sum of open max-losses with correlated names netted.

Per CONSTITUTION: total heat ≤ ~8% of port; correlated names count as one bet
(net their max-losses against the cap, do not double-count diversification you
don't have in a de-gross).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    ticker: str
    max_loss: float  # dollars at risk if thesis fully breaks
    group: str  # correlation bucket, e.g. "ai-semis", "saas-phoenix", "oil"


def group_heat(positions: list[Position]) -> dict[str, float]:
    """Sum max-loss per correlation group."""
    out: dict[str, float] = {}
    for p in positions:
        out[p.group] = out.get(p.group, 0.0) + p.max_loss
    return out


def total_heat(positions: list[Position]) -> float:
    """Net heat across the book — already correlation-netted by summing groups."""
    return sum(group_heat(positions).values())


def heat_report(positions: list[Position], port_value: float, cap_pct: float = 0.08) -> str:
    groups = group_heat(positions)
    total = sum(groups.values())
    lines = [f"port: ${port_value:,.0f}   cap: {cap_pct:.0%} (${port_value * cap_pct:,.0f})"]
    for g, v in sorted(groups.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {g:<20} ${v:>10,.0f}   {v / port_value:>6.2%}")
    status = "OK" if total <= port_value * cap_pct else "BREACH"
    lines.append(f"total: ${total:,.0f}   {total / port_value:.2%}   [{status}]")
    return "\n".join(lines)
