# ABOUTME: Tests for guard_trunk_pull — refuse a pull that would rewrite a protected branch.
# ABOUTME: Pure predicate truth table; no git, no network, no hook plumbing.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load():
    rel = Path("shared") / "scripts" / "dev" / "guard_trunk_pull.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("guard_trunk_pull", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


g = _load()


# --- pull_target: what ref is this pull aimed at? -------------------------


def test_pull_with_explicit_ref():
    assert g.pull_target("git pull origin staging") == "staging"


def test_pull_with_ff_only_flag_between():
    assert g.pull_target("git pull --ff-only origin staging") == "staging"


def test_bare_pull_has_no_explicit_ref():
    """``git pull`` follows the branch's own upstream — never the wrong ref."""
    assert g.pull_target("git pull") is None
    assert g.pull_target("git pull --ff-only") is None


def test_non_pull_commands_ignored():
    assert g.pull_target("git fetch origin staging") is None
    assert g.pull_target("git merge --ff-only origin/staging") is None


def test_quoted_mention_is_not_a_command():
    assert g.pull_target('echo "git pull origin staging"') is None


def test_pull_after_shell_separator_is_caught():
    assert g.pull_target("cd /repo && git pull origin staging") == "staging"


# --- the decision ---------------------------------------------------------
#
# The hazard is narrow: pulling a foreign ref into a PROTECTED branch rewrites
# a trunk pointer. Pulling upstream into a feature branch is an ordinary,
# correct idiom and must stay silent — a guard that cries wolf gets overridden
# reflexively, which is worse than no guard.


def test_foreign_ref_into_protected_branch_blocks():
    assert g.should_block("git pull origin staging", current_branch="main") is True


def test_foreign_ref_into_feature_branch_allowed():
    assert g.should_block("git pull origin staging", current_branch="feat/x") is False


def test_matching_ref_into_protected_branch_allowed():
    """Pulling a branch into itself is the ordinary refresh."""
    assert g.should_block("git pull origin main", current_branch="main") is False


def test_bare_pull_on_protected_branch_allowed():
    assert g.should_block("git pull --ff-only", current_branch="main") is False


def test_master_is_protected_too():
    assert g.should_block("git pull origin staging", current_branch="master") is True


def test_staging_is_protected_too():
    assert g.should_block("git pull origin main", current_branch="staging") is True


def test_detached_head_is_not_protected():
    assert g.should_block("git pull origin staging", current_branch="HEAD") is False


# --- the escape hatch -----------------------------------------------------


def test_inline_override_allows():
    assert (
        g.should_block(
            "CLAUDE_ALLOW_MAIN_GIT=1 git pull origin staging", current_branch="main"
        )
        is False
    )


def test_quoted_override_does_not_wave_through():
    """A mention inside a string is not an assignment."""
    assert (
        g.should_block(
            'echo "CLAUDE_ALLOW_MAIN_GIT=1" && git pull origin staging',
            current_branch="main",
        )
        is True
    )


# --- prose is not a command ----------------------------------------------
#
# A backtick is a command-substitution opener, so documentation *about this
# guard* sits at a command position. The tell is the refspec: git forbids the
# characters a placeholder or quoted fragment carries. Regression — the guard
# blocked the very commit message that documented it.


def test_markdown_placeholder_is_not_a_pull():
    assert g.pull_target("never `git pull <remote> <ref>` on a trunk branch") is None


def test_backticked_prose_does_not_block():
    prose = "docs: never `git pull <remote> <ref>` on a trunk branch"
    assert g.should_block(prose, current_branch="master") is False


def test_quoted_refspec_is_not_a_pull():
    assert g.pull_target("git pull origin 'staging'") is None


def test_real_pull_still_caught_after_plausibility_filter():
    assert g.pull_target("git pull --ff-only origin staging") == "staging"
    assert g.should_block("git pull origin staging", current_branch="main") is True
