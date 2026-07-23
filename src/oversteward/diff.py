# ABOUTME: Pure comparison of a gather snapshot against registry expectations (H2-4).
# ABOUTME: Emits structured findings (severity drift/missing/info). No filesystem access, no writes.

from __future__ import annotations

from typing import Any

Finding = dict[str, Any]


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


def _diff_worktree_discipline(ctx: dict[str, Any], canonical_dev: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    checks = (
        ("hook_sha256", "guard_main_worktree.py", ".claude/hooks/guard_main_worktree.py"),
        ("new_session_sha256", "new-session.sh", "scripts/dev/new-session.sh"),
        ("with_test_env_sha256", "with_test_env.py", "scripts/dev/with_test_env.py"),
    )
    for key, canonical_name, deployed_path in checks:
        expected = canonical_dev.get(canonical_name)
        if expected is None:
            continue
        actual = ctx.get(key)
        if actual is None:
            findings.append(
                _finding("missing", "worktree-discipline", f"{deployed_path} absent", ctx["id"])
            )
        elif actual != expected:
            findings.append(
                _finding(
                    "drift",
                    "worktree-discipline",
                    f"{deployed_path} differs from canonical shared/scripts/dev/",
                    ctx["id"],
                )
            )
    return findings


def _diff_security_gate(ctx: dict[str, Any], canonical_dev: dict[str, Any]) -> list[Finding]:
    """Tier-1 secret-scan gate parity: canonical byte-copy + a baseline file.

    ``secret_scan.py`` is a byte-copy canonical family member (like
    ``with_test_env.py``); ``.gitleaksignore`` is a per-repo baseline whose
    *contents* legitimately differ, so only its presence is checked.
    """
    findings: list[Finding] = []
    cid = ctx["id"]
    expected = canonical_dev.get("secret_scan.py")
    if expected is not None:
        actual = ctx.get("secret_scan_sha256")
        if actual is None:
            findings.append(
                _finding("missing", "security-gate", "scripts/dev/secret_scan.py absent", cid)
            )
        elif actual != expected:
            findings.append(
                _finding(
                    "drift",
                    "security-gate",
                    "scripts/dev/secret_scan.py differs from canonical shared/scripts/dev/",
                    cid,
                )
            )
    if not ctx.get("gitleaksignore_present"):
        findings.append(
            _finding("missing", "security-gate", ".gitleaksignore baseline absent", cid)
        )
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
    snapshot: dict[str, Any], freshness: dict[str, str] | None = None
) -> list[Finding]:
    """Compare a gather snapshot against expectations; return structured findings."""
    findings: list[Finding] = []
    canonical_dev = snapshot.get("canonical_dev", {})
    for ctx in snapshot.get("contexts", []):
        if not ctx.get("reachable"):
            findings.append(
                _finding("info", "reachability", "no local_path — not checked", ctx["id"])
            )
            continue
        findings.extend(_diff_managed_block(ctx))
        findings.extend(_diff_worktree_discipline(ctx, canonical_dev))
        findings.extend(_diff_security_gate(ctx, canonical_dev))
    canonical = snapshot.get("canonical_shared", {})
    for name, target in snapshot.get("deploy_targets", {}).items():
        findings.extend(_diff_deploy_target(name, target, canonical))
    findings.extend(_diff_settings(snapshot.get("contexts", [])))
    findings.extend(_diff_freshness(freshness))
    return findings
