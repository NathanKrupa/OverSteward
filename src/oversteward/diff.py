# ABOUTME: Pure comparison of a gather snapshot against registry expectations (H2-4).
# ABOUTME: Emits findings (drift/missing/info/unreadable) and the report. No filesystem access.

from __future__ import annotations

from typing import Any

from oversteward.dev_family import (
    ABSENT,
    ABSENT_REFERENCED,
    DRIFTED,
    RepoFamilyStatus,
    deployed_relpath,
)
from oversteward.hook_registration import (
    HOOKS_DIR,
    PRESENT_UNREGISTERED,
    REGISTERED_ABSENT,
    RepoHooks,
)

Finding = dict[str, Any]

HOOK_SURFACE = "hook-registration"

#: Problem severities: they print under DRIFT and exit 1.
PROBLEM_SEVERITIES = ("missing", "drift")
#: Could-not-read severity: prints under COULD NOT READ and exits 2, outranking 1.
UNREADABLE = "unreadable"

#: How a managed block loads a file under canonical `shared/references/`.
REFERENCE_IMPORT = "@~/.claude/shared/references/{path}"

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
    if managed["present"]:
        findings.extend(_diff_references(cid, ctx.get("references_always_on") or [], managed["text"]))
    return findings


def _diff_references(cid: str, declared: list[str], block: str | None) -> list[Finding]:
    """Each declared reference must be an import line of its own inside the managed block.

    Leading indentation is not stripped: indented four spaces, the line is a
    Markdown code block, which Claude Code does not import.
    """
    lines = {line.rstrip() for line in (block or "").splitlines()}
    return [
        _finding("drift", "reference", f"managed block lacks the line `{expected}`", cid)
        for expected in (REFERENCE_IMPORT.format(path=path) for path in declared)
        if expected not in lines
    ]


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


def _hook_findings(row: RepoHooks) -> list[Finding]:
    """One repo's hook findings: each absent registration, each unregistered script."""
    cid, ref = row.context_id, f"origin/{row.branch}"
    statuses = row.statuses()
    findings = [
        _finding(
            "missing",
            HOOK_SURFACE,
            f"{HOOKS_DIR}/{reg.script} is registered by {reg.source} ({reg.event}) and is not a "
            f"file at {ref}: the interpreter exits 2 on it, refusing every matching tool call",
            cid,
        )
        for reg in row.registrations
        if statuses.get(reg.script) == REGISTERED_ABSENT
    ]
    findings.extend(
        _finding("drift", HOOK_SURFACE, f"{HOOKS_DIR}/{script} at {ref}: nothing registers it", cid)
        for script, status in statuses.items()
        if status == PRESENT_UNREGISTERED
    )
    findings.extend(_finding("info", HOOK_SURFACE, line, cid) for line in row.unshaped)
    return findings


def _diff_hook_registration(rows: list[RepoHooks]) -> list[Finding]:
    """Hook findings per repo, a could-not-read per unread repo, and the count checked."""
    findings: list[Finding] = []
    read = [row for row in rows if row.unreadable is None]
    for row in rows:
        if row.unreadable is not None:
            findings.append(_finding(UNREADABLE, HOOK_SURFACE, row.unreadable, row.context_id))
        else:
            findings.extend(_hook_findings(row))
    findings.append(
        _finding(
            "info",
            HOOK_SURFACE,
            f"checked {len(read)} contexts: {sum(len(r.present) for r in read)} scripts present, "
            f"{sum(len(r.registrations) for r in read)} registrations; "
            f"{len(rows) - len(read)} contexts not read",
        )
    )
    if not read:
        findings.append(_finding(UNREADABLE, HOOK_SURFACE, "no context's hooks were read"))
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


def _diff_reachability(ctx: dict[str, Any]) -> Finding:
    """Why a context wasn't checked — and whether that is a choice or a defect.

    An unconfigured context is a repo nobody asked us to read. A configured path
    that isn't on disk is a broken instrument: the sweeps drop the repo silently
    and every surface reports lockstep it never measured (OS#357 — a
    capitalisation typo hid fiscus from the canonical-family audit for weeks).
    """
    if ctx.get("unreachable_reason") == "missing-on-disk":
        return _finding(
            "drift",
            "reachability",
            f"local_path {ctx.get('local_path')} is not on disk — every sweep skipped this repo",
            ctx["id"],
        )
    return _finding("info", "reachability", "no local_path — not checked", ctx["id"])


def diff_state(
    snapshot: dict[str, Any],
    freshness: dict[str, str] | None = None,
    family_rows: list[RepoFamilyStatus] | None = None,
    hook_rows: list[RepoHooks] | None = None,
) -> list[Finding]:
    """Compare a gather snapshot against expectations; return structured findings.

    ``hook_rows`` of None means the hook audit did not run; an empty list means it
    ran and read nothing, which is a could-not-read finding.
    """
    findings: list[Finding] = []
    for ctx in snapshot.get("contexts", []):
        if not ctx.get("reachable"):
            findings.append(_diff_reachability(ctx))
            continue
        findings.extend(_diff_managed_block(ctx))
        findings.extend(_diff_security_gate(ctx))
    findings.extend(_diff_canonical_family(family_rows or []))
    if hook_rows is not None:
        findings.extend(_diff_hook_registration(hook_rows))
    canonical = snapshot.get("canonical_shared", {})
    for name, target in snapshot.get("deploy_targets", {}).items():
        findings.extend(_diff_deploy_target(name, target, canonical))
    findings.extend(_diff_settings(snapshot.get("contexts", [])))
    findings.extend(_diff_freshness(freshness))
    return findings


def exit_code(findings: list[Finding]) -> int:
    """2 when anything could not be read, else 1 on any problem, else 0. 2 outranks 1."""
    if any(f["severity"] == UNREADABLE for f in findings):
        return 2
    return 1 if any(f["severity"] in PROBLEM_SEVERITIES for f in findings) else 0


def format_report(findings: list[Finding]) -> list[str]:
    """The text report: could-not-read first, then drift, then info.

    "In lockstep" prints only when nothing is a problem and nothing went unread.
    """
    unread = [f for f in findings if f["severity"] == UNREADABLE]
    problems = [f for f in findings if f["severity"] in PROBLEM_SEVERITIES]
    infos = [f for f in findings if f["severity"] == "info"]
    lines: list[str] = []
    if not problems and not unread:
        lines.append("In lockstep — no drift detected.")
    for group, title in ((unread, "COULD NOT READ"), (problems, "DRIFT"), (infos, "INFO")):
        if not group:
            continue
        lines.append(f"\n## {title}")
        for f in sorted(group, key=lambda f: (f["surface"], f["context"] or "")):
            where = f" [{f['context']}]" if f["context"] else ""
            lines.append(f"- {f['severity']:7s} {f['surface']}{where}: {f['message']}")
    return lines
