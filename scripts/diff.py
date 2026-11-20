# ABOUTME: CLI for governance drift comparison (H2-4) — backs the /sync-status skill.
# ABOUTME: Gathers fresh state, diffs against expectations, prints grouped report. Read-only.

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


import yaml

from oversteward.dev_family import format_family_table, gather_family_status
from oversteward.diff import diff_state, exit_code, format_report
from oversteward.gather import default_paths, gather_state
from oversteward.hook_registration import format_hook_table, gather_hook_registration

SESSION_DATE_RE = re.compile(r"^session_date:\s*(\S+)", re.MULTILINE)


def _freshness(repo_root: Path) -> dict[str, str] | None:
    session_state = repo_root / "SESSION_STATE.md"
    if not session_state.is_file():
        return None
    match = SESSION_DATE_RE.search(session_state.read_text(encoding="utf-8"))
    if match is None:
        return None
    last_merge = subprocess.run(
        ["git", "-C", str(repo_root), "log", "--merges", "-1", "--format=%cs"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {"session_state_date": match.group(1), "last_merge_date": last_merge}


def main(argv: list[str]) -> int:
    paths = default_paths()
    registry_text = (paths["repo_root"] / "registry.yaml").read_text(encoding="utf-8")
    registry = yaml.safe_load(registry_text)
    snapshot = gather_state(registry, paths["canonical_shared"], paths["deploy_targets"])
    fetch = "--no-fetch" not in argv
    family_rows = gather_family_status(registry, paths["canonical_shared"], fetch=fetch)
    hook_rows = gather_hook_registration(registry, family_rows, fetch_requested=fetch)
    findings = diff_state(
        snapshot,
        freshness=_freshness(paths["repo_root"]),
        family_rows=family_rows,
        hook_rows=hook_rows,
    )
    if "--family" in argv:
        header = "## CANONICAL FAMILY (shared/scripts/dev/ vs each repo's origin ref)"
        print("\n".join([header, *format_family_table(family_rows)]))
    if "--hooks" in argv:
        print("\n".join(format_hook_table(hook_rows, fetch_requested=fetch)))
    if "--json" in argv:
        json.dump(findings, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print("\n".join(format_report(findings)))
    return exit_code(findings)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
