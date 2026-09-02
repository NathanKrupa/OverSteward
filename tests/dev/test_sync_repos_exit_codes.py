# ABOUTME: The nightly sync must not report SUCCESS when it could not look at a checkout (OS#384).
# ABOUTME: Deliberate skips stay green; a missing checkout or an unreadable remote does not.

"""Finding 3 of OS#384.

``sync_all`` produced ``absent`` ("no local checkout") and a ``skip`` meaning
"could not determine origin default branch", and ``main`` returned 0 regardless.
Under a systemd timer that makes the unit report ``SUCCESS`` whether it synced
sixteen checkouts or found none of them — a mis-pathed registry entry would
never surface.

The deliberate skips (dirty tree, unpushed commits, off-target branch) are
*measured answers* and stay exit 0. Confusing the two would make the timer red
every time a developer had uncommitted work, which is how a monitor gets muted.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load():
    """Load the script by path, as tests/dev/test_sync_repos.py already does."""
    rel = Path("scripts") / "dev" / "sync_repos.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("sync_repos", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


sr = _load()

ACTION_ABSENT = sr.ACTION_ABSENT
ACTION_UNREADABLE = sr.ACTION_UNREADABLE
EXIT_OK = sr.EXIT_OK
EXIT_COULD_NOT_LOOK = sr.EXIT_COULD_NOT_LOOK
exit_code_for = sr.exit_code_for


def _plan(action: str, reason: str = "r"):
    return sr.SyncPlan("repo", action, reason)


class TestExitCode:
    def test_all_measured_actions_are_green(self):
        plans = [_plan(a) for a in ("current", "ff", "unshallow_ff", "reset")]
        assert exit_code_for(plans) == EXIT_OK

    @pytest.mark.parametrize(
        "reason",
        [
            "3 uncommitted change(s) — left untouched",
            "on 'feature/x', not target 'main'",
            "2 unpushed commit(s) — manual reconcile",
        ],
    )
    def test_a_deliberate_skip_is_a_measured_answer_and_stays_green(self, reason):
        assert exit_code_for([_plan("skip", reason)]) == EXIT_OK

    def test_a_missing_checkout_is_could_not_look(self):
        assert exit_code_for([_plan(ACTION_ABSENT, "no local checkout")]) == EXIT_COULD_NOT_LOOK

    def test_an_unreadable_remote_is_could_not_look(self):
        plans = [_plan(ACTION_UNREADABLE, "could not determine origin default branch")]
        assert exit_code_for(plans) == EXIT_COULD_NOT_LOOK

    def test_one_blind_repo_among_many_healthy_ones_still_reddens_the_run(self):
        plans = [_plan("current") for _ in range(15)] + [_plan(ACTION_ABSENT)]
        assert exit_code_for(plans) == EXIT_COULD_NOT_LOOK

    def test_an_empty_sweep_is_could_not_look_not_a_clean_estate(self):
        """Sixteen repos configured and none visited is the false green itself."""
        assert exit_code_for([]) == EXIT_COULD_NOT_LOOK


class TestUnreadableIsItsOwnAction:
    def test_could_not_determine_the_branch_is_not_filed_as_a_plain_skip(self):
        """String-matching a reason to classify it is how the two get confused."""
        assert ACTION_UNREADABLE != "skip"
