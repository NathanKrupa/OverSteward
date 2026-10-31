# ABOUTME: Renders the estate map's digest — the short summary every OverSteward session loads.
# ABOUTME: Pure and deterministic, so the committed digest can be compared byte for byte with a fresh render.

from __future__ import annotations

from .model import EstateMap
from .outcome import Finding

DIGEST_HEADER = (
    "<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. "
    "Do not edit by hand: a test compares this file with a fresh render. -->"
)


def digest(estate: EstateMap) -> str:
    lines = [
        DIGEST_HEADER,
        "",
        "# Estate map — digest",
        "",
        f"**North star.** {estate.north_star.strip()}",
        "",
        "**Products.** "
        + "; ".join(f"`{p.id}` ({p.repo}) serves {p.serves.strip()}" for p in estate.products),
        "",
        "## Capabilities (`id` · status · purpose)",
        "",
    ]
    lines += [f"- `{c.id}` · {c.status} · {c.purpose.strip()}" for c in estate.capabilities]
    lines += [
        "",
        f"Claims, current and target shape, seams ({_span(estate.seams)}), invariants "
        f"({_span(estate.invariants)}) and liabilities live in `estate-map.yaml`. "
        "Read it at scope time; `scripts/estate_map.py check` is the seventh session-start sweep.",
    ]
    return "\n".join(lines) + "\n"


def _span(rows) -> str:
    ids = [r.id for r in rows]
    return f"{ids[0]}..{ids[-1]}" if ids else "none"


def budget_findings(estate: EstateMap, text: str) -> list[Finding]:
    size = len(text.encode("utf-8"))
    budget = estate.policy.digest_budget_bytes
    if size > budget:
        return [Finding("digest-budget", "digest", f"{size} bytes exceeds the {budget}-byte budget")]
    return []
