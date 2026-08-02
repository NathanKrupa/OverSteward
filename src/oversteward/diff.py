# ABOUTME: Pure comparison of a gather snapshot against registry expectations (H2-4).
# ABOUTME: Emits structured findings (severity drift/missing/info). No filesystem access, no writes.

from __future__ import annotations

from typing import Any

from oversteward.dev_family import (
    ABSENT,
    ABSENT_REFERENCED,
    DRIFTED,
    RepoFamilyStatus,
    deployed_relpath,
)

Finding = dict[str, Any]

# How each canonical-family status reads in the drift report. `present-identical`
# is absent from the map: parity is not a finding.
FAMILY_MESSAGES = {
    DRIFTED: ("drift", "{path} differs from canonical shared/scripts/dev/{member}"),
    ABSENT_REFERENCED: ("missing", "{path} absent, yet CLAUDE.md tells agents to use it"),
    ABSENT: ("info", "{path} not deployed"),
}


def _finding(severity: str, surface: str, message: str, context: str | None = None) -> Finding:
    return {"severity": severity, "surface": surface, "context": context, "message": message}


def _diff_managed_block(ctx: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    cid = ctx["id"]
    claude_md = ctx["claude_md"]
    if not claude_md["exists"]:
        return [_finding("missing", "managed-block", "CLAUDE.md does not exist", cid)]
    if ctx.get("skip_sow"):
        return []
    managed = claude_md["managed"]
    if not managed["present"]:
        findings.append(
            _finding("missing", "managed-block", "no [oversteward:managed] block", cid)
        )
    elif ctx.get("soul") and not ctx.get("soul_in_local"):
        expected = f"souls/{ctx['soul']}.md"
        if expected not in (managed["text"] or ""):
            findings.append(
                _finding(
                    "drift",
                    "soul",
                    f"managed block does not reference {expected}",
                    cid,
                )
            )
    return findings


def _diff_security_gate(ctx: dict[str, Any]) -> list[Finding]:
    """Tier-1 secret-scan gate baseline.

    ``secret_scan.py`` itself is a canonical family member, checked against origin
    by the ``canonical-family`` surface. ``.gitleaksignore`` is a per-repo baseline
    whose *contents* legitimately differ, so only its presence is checked.
    """
    if ctx.get("gitleaksignore_present"):
        return []
    return [_finding("missing", "security-gate", ".gitleaksignore baseline absent", ctx["id"])]


def _diff_canonical_family(rows: list[RepoFamilyStatus]) -> list[Finding]:
    """Turn per-repo ``shared/scripts/dev/`` family statuses into findings."""
    findings: list[Finding] = []
    for row in rows:
        cid = row.context_id
        if not row.available:
            findings.append(
                _finding(
                    "info",
                    "canonical-family",
                    f"origin/{row.branch} unreadable — family not checked",
                    cid,
                )
            )
            continue
        for member, status in sorted(row.members.items()):
            entry = FAMILY_MESSAGES.get(status)
            if entry is None:
                continue
            severity, template = entry
            message = template.format(path=deployed_relpath(member), member=member)
            findings.append(_finding(severity, "canonical-family", message, cid))
    return findings


def _diff_deploy_target(
    name: str, target: dict[str, str] | None, canonical: dict[str, str]
) -> list[Finding]:
    surface = f"shared-deploy:{name}"
    if target is None:
        return [_finding("missing", surface, "deploy target directory not found")]
    findings: list[Finding] = []
    missing = sorted(set(canonical) - set(target))
    if missing:
        findings.append(
            _finding("missing", surface, f"{len(missing)} file(s) not deployed: {', '.join(missing)}")
        )
    mismatched = sorted(rel for rel in canonical.keys() & target.keys() if canonical[rel] != target[rel])
    if mismatched:
        findings.append(
            _finding("drift", surface, f"{len(mismatched)} file(s) differ: {', '.join(mismatched)}")
        )
    extra = sorted(set(target) - set(canonical))
    if extra:
        findings.append(
            _finding("info", surface, f"{len(extra)} file(s) only on target: {', '.join(extra)}")
        )
    return findings


def _diff_settings(contexts: list[dict[str, Any]]) -> list[Finding]:
    reachable = [c for c in contexts if c.get("reachable")]
    if not reachable:
        return []
    have = sorted(c["id"] for c in reachable if c.get("settings_sha256"))
    lack = sorted(c["id"] for c in reachable if not c.get("settings_sha256"))
    return [
        _finding(
            "info",
            "settings",
            f".claude/settings.json present: {', '.join(have) or 'none'}; "
            f"absent: {', '.join(lack) or 'none'} (no canonical policy yet — H2-1 phase 2)",
        )
    ]


def _diff_freshness(freshness: dict[str, str] | None) -> list[Finding]:
    if not freshness:
        return []
    session = freshness.get("session_state_date")
    merge = freshness.get("last_merge_date")
    if session and merge and session < merge:
        return [
            _finding(
                "drift",
                "tracking",
                f"SESSION_STATE.md ({session}) predates last merge to master ({merge})",
            )
        ]
    return []


def diff_state(
    snapshot: dict[str, Any],
    freshness: dict[str, str] | None = None,
    family_rows: list[RepoFamilyStatus] | None = None,
) -> list[Finding]:
    """Compare a gather snapshot against expectations; return structured findings."""
    findings: list[Finding] = []
    for ctx in snapshot.get("contexts", []):
        if not ctx.get("reachable"):
            findings.append(
                _finding("info", "reachability", "no local_path — not checked", ctx["id"])
            )
            continue
        findings.extend(_diff_managed_block(ctx))
        findings.extend(_diff_security_gate(ctx))
    findings.extend(_diff_canonical_family(family_rows or []))
    canonical = snapshot.get("canonical_shared", {})
    for name, target in snapshot.get("deploy_targets", {}).items():
        findings.extend(_diff_deploy_target(name, target, canonical))
    findings.extend(_diff_settings(snapshot.get("contexts", [])))
    findings.extend(_diff_freshness(freshness))
    return findings
