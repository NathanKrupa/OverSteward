# ABOUTME: Renders the estate map — the short digest every OverSteward session loads, and a per-repo slice.
# ABOUTME: Pure and deterministic, so the committed digest can be compared byte for byte with a fresh render.

from __future__ import annotations

from .model import Capability, EstateMap
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


def repo_slice(estate: EstateMap, repo: str) -> str:
    """Markdown of one repo's capabilities, the seams it is party to, and the rows they cite."""
    products = {p.id for p in estate.products if p.repo == repo}
    caps = [c for c in estate.capabilities if c.id.split(".")[0] in products or repo in c.claims]
    seams = [s for s in estate.seams if repo in s.producer or repo in s.consumer]
    cited_inv = {i for c in caps for i in c.invariants} | {i for s in seams for i in s.invariants}
    cited_lia = {item for c in caps for item in c.liabilities} | {item for s in seams for item in s.liabilities}
    lines = [f"# Estate map — {repo}", "", "## Capabilities", ""]
    for cap in caps:
        lines += _capability_block(cap)
    lines += ["## Seams", ""]
    lines += [f"- **{s.id}** {s.label}: {s.flows} ({s.cite})" for s in seams]
    lines += ["", "## Invariants", ""]
    lines += [f"- **{i.id}** ({i.status}) {i.text} ({i.cite})" for i in estate.invariants if i.id in cited_inv]
    lines += ["", "## Liabilities", ""]
    lines += [f"- **{item.id}** {item.text} ({item.tracking})" for item in estate.liabilities if item.id in cited_lia]
    return "\n".join(lines) + "\n"


def _capability_block(cap: Capability) -> list[str]:
    claims = [f"{repo}:{path}" for repo, paths in cap.claims.items() for path in paths]
    return [
        f"### `{cap.id}` · {cap.kind} · {cap.status}",
        "",
        cap.purpose.strip(),
        "",
        f"- claims: {', '.join(claims) or 'none'}",
        f"- current: {cap.current_shape.strip()}",
        f"- target: {cap.target_shape.strip()}",
        "",
    ]
