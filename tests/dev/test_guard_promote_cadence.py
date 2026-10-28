# ABOUTME: Tests for guard_promote_cadence — refuse a GrantSpider staging->main promote within 6 days.
# ABOUTME: GitHub and git are reached only through injected seams; the end-to-end runs use a fake gh.

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _load():
    rel = Path("shared") / "scripts" / "dev" / "guard_promote_cadence.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("guard_promote_cadence", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod, candidate
    raise AssertionError(f"could not locate {rel}")


g, HOOK_PATH = _load()

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
GS_PROMOTE = "gh pr create --repo NathanKrupa/grantspider --base main --head staging --title t"
GS_REST = (
    "gh api repos/NathanKrupa/grantspider/pulls -f base=main -f head=staging -f title=Promote"
)
GS_ORIGIN = "git@github.com:NathanKrupa/grantspider.git"

TOO_SOON = "BLOCKED — GrantSpider was promoted to main"
COULD_NOT_LOOK = "BLOCKED — could not check when GrantSpider was last promoted"


class FakeGitHub:
    """The last-promote seam: a canned answer or a canned failure, and a call count."""

    def __init__(self, *, ago: timedelta | None = None, fails: str | None = None) -> None:
        self._ago = ago
        self._fails = fails
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self._fails is not None:
            raise g.LookupFailed(self._fails)
        if self._ago is None:
            return None
        return g.LastPromote(number=3400, merged_at=NOW - self._ago)


class FakeCheckouts:
    """The git seam: what each directory's origin and current branch are."""

    def __init__(self, checkouts: dict[str, g.Checkout] | None = None) -> None:
        self._checkouts = checkouts or {}
        self.asked: list[str] = []

    def __call__(self, path: str):
        self.asked.append(path)
        return self._checkouts.get(path, g.Checkout(origin=None, branch=None))


def run(command, *, github=None, checkouts=None, cwd="/home/natha/OverSteward", environ=None):
    github = github if github is not None else FakeGitHub(ago=timedelta(days=2))
    return g.evaluate(
        command,
        cwd,
        environ=environ or {},
        read_checkout=checkouts or FakeCheckouts(),
        last_promote=github,
        now=NOW,
    )


def assert_too_soon(code: int, message: str) -> None:
    assert code == 2
    assert TOO_SOON in message
    assert COULD_NOT_LOOK not in message
    assert "Traceback" not in message


def assert_allowed(code: int, message: str) -> None:
    assert code == 0
    assert "BLOCKED" not in message
    assert "Traceback" not in message


# --- the cadence rule ------------------------------------------------------


def test_a_promote_two_days_after_the_last_is_refused():
    code, message = run(GS_PROMOTE, github=FakeGitHub(ago=timedelta(days=2)))
    assert_too_soon(code, message)
    # Names the last promote's date, the next allowed day, and how to override.
    assert "2026-10-26 12:00 UTC (PR #3400)" in message
    assert "next promote is allowed from 2026-11-01 12:00 UTC" in message
    assert "GS_PROMOTE_HOTFIX='<why this cannot wait>'" in message


def test_a_promote_seven_days_after_the_last_is_allowed():
    github = FakeGitHub(ago=timedelta(days=7))
    assert_allowed(*run(GS_PROMOTE, github=github))
    assert github.calls == 1


def test_one_second_inside_the_six_day_window_is_refused():
    code, message = run(GS_PROMOTE, github=FakeGitHub(ago=timedelta(days=6) - timedelta(seconds=1)))
    assert_too_soon(code, message)


def test_exactly_six_days_after_the_last_is_allowed():
    assert_allowed(*run(GS_PROMOTE, github=FakeGitHub(ago=timedelta(days=6))))


def test_no_promote_ever_merged_is_allowed():
    assert_allowed(*run(GS_PROMOTE, github=FakeGitHub(ago=None)))


# --- the override ----------------------------------------------------------


def test_the_override_with_a_reason_is_allowed_and_records_the_reason():
    github = FakeGitHub(ago=timedelta(days=2))
    code, message = run(f"GS_PROMOTE_HOTFIX='prod 500 on /foundations' {GS_PROMOTE}", github=github)
    assert_allowed(code, message)
    assert "GS_PROMOTE_HOTFIX" in message
    assert "reason: prod 500 on /foundations" in message
    assert github.calls == 0


@pytest.mark.parametrize("prefix", ["GS_PROMOTE_HOTFIX=", "GS_PROMOTE_HOTFIX=''", "GS_PROMOTE_HOTFIX='   '"])
def test_the_override_with_an_empty_reason_is_refused(prefix):
    code, message = run(f"{prefix} {GS_PROMOTE}", github=FakeGitHub(ago=timedelta(days=2)))
    assert_too_soon(code, message)
    assert "an empty GS_PROMOTE_HOTFIX does not count" in message


def test_an_override_on_another_command_does_not_count():
    code, message = run(f"GS_PROMOTE_HOTFIX=why echo hi && {GS_PROMOTE}")
    assert_too_soon(code, message)


def test_the_override_in_the_hook_environment_does_not_count():
    """Only the promote's own prefix is a recorded decision; a session-wide env is not."""
    code, message = run(GS_PROMOTE, environ={"GS_PROMOTE_HOTFIX": "standing"})
    assert_too_soon(code, message)


# --- could not look ----------------------------------------------------------


def test_a_gh_failure_gives_the_could_not_look_refusal():
    code, message = run(GS_PROMOTE, github=FakeGitHub(fails="gh api exited 1: HTTP 502"))
    assert code == 2
    assert COULD_NOT_LOOK in message
    assert "gh api exited 1: HTTP 502" in message
    assert TOO_SOON not in message
    assert "Traceback" not in message


def test_the_override_also_passes_a_could_not_look():
    github = FakeGitHub(fails="no network")
    assert_allowed(*run(f"GS_PROMOTE_HOTFIX='hotfix' {GS_PROMOTE}", github=github))


def test_an_empty_override_does_not_pass_a_could_not_look():
    code, message = run(f"GS_PROMOTE_HOTFIX= {GS_PROMOTE}", github=FakeGitHub(fails="no network"))
    assert code == 2
    assert COULD_NOT_LOOK in message
    assert "an empty GS_PROMOTE_HOTFIX does not count" in message


# --- what is not a GrantSpider promote ----------------------------------------


def test_a_feature_pr_to_staging_is_allowed_without_asking_github():
    github = FakeGitHub(ago=timedelta(days=2))
    command = "gh pr create --repo NathanKrupa/grantspider --base staging --head feat/x --title t"
    assert_allowed(*run(command, github=github))
    assert github.calls == 0


def test_an_aigranthelper_promote_is_allowed_without_asking_github():
    github = FakeGitHub(ago=timedelta(days=2))
    command = "gh pr create --repo NathanKrupa/aigranthelper --base main --head staging --title t"
    assert_allowed(*run(command, github=github))
    assert github.calls == 0


def test_a_hotfix_branch_into_main_is_not_a_promote():
    command = "gh pr create --repo NathanKrupa/grantspider --base main --head hotfix/x --title t"
    assert_allowed(*run(command))


def test_omitted_base_targets_the_default_branch_and_is_not_a_promote():
    command = "gh pr create --repo NathanKrupa/grantspider --head staging --title t"
    assert_allowed(*run(command))


def test_a_quoted_mention_is_not_a_command():
    assert_allowed(*run(f'git commit -m "{GS_PROMOTE}"'))


def test_other_commands_never_reach_a_seam():
    github, checkouts = FakeGitHub(ago=timedelta(days=2)), FakeCheckouts()
    assert_allowed(*run("git status && gh pr list", github=github, checkouts=checkouts))
    assert github.calls == 0
    assert checkouts.asked == []


# --- how the target repo and branches are read ----------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create -R NathanKrupa/grantspider -B main -H staging -t t",
        "gh pr create --repo=NathanKrupa/grantspider --base=main --head=staging",
        "gh pr create --repo nathankrupa/GrantSpider --base main --head NathanKrupa:staging",
        "gh pr create --repo https://github.com/NathanKrupa/grantspider --base main --head staging",
        "gh pr new --repo NathanKrupa/grantspider --base main --head staging",
        "GH_REPO=NathanKrupa/grantspider gh pr create --base main --head staging",
        "/usr/bin/gh pr create --repo NathanKrupa/grantspider --base main --head staging",
    ],
)
def test_promote_spellings_are_refused(command):
    assert_too_soon(*run(command))


def test_gh_repo_in_the_session_environment_names_the_repo():
    command = "gh pr create --base main --head staging"
    assert_too_soon(*run(command, environ={"GH_REPO": "NathanKrupa/grantspider"}))


def test_cd_into_a_grantspider_checkout_names_the_repo():
    checkouts = FakeCheckouts({"/home/natha/grantspider": g.Checkout(GS_ORIGIN, "main")})
    command = "cd /home/natha/grantspider && gh pr create --base main --head staging --title t"
    assert_too_soon(*run(command, checkouts=checkouts))
    assert checkouts.asked == ["/home/natha/grantspider"]


def test_a_relative_cd_resolves_against_the_hook_cwd():
    checkouts = FakeCheckouts({"/home/natha/grantspider": g.Checkout(GS_ORIGIN, "main")})
    command = "cd ../grantspider && gh pr create --base main --head staging"
    assert_too_soon(*run(command, checkouts=checkouts, cwd="/home/natha/OverSteward"))


def test_the_hook_cwd_inside_a_grantspider_worktree_names_the_repo():
    worktree = "/home/natha/grantspider/.claude/worktrees/x"
    https = "https://github.com/NathanKrupa/grantspider.git"
    checkouts = FakeCheckouts({worktree: g.Checkout(https, "session/x")})
    assert_too_soon(*run("gh pr create --base main --head staging", checkouts=checkouts, cwd=worktree))


def test_a_cwd_in_another_repo_is_not_grantspider():
    checkouts = FakeCheckouts(
        {"/home/natha/aigranthelper": g.Checkout("git@github.com:NathanKrupa/aigranthelper.git", "staging")}
    )
    command = "cd /home/natha/aigranthelper && gh pr create --base main --head staging"
    assert_allowed(*run(command, checkouts=checkouts))


def test_omitted_head_reads_the_checked_out_branch():
    checkouts = FakeCheckouts({"/home/natha/grantspider": g.Checkout(GS_ORIGIN, "staging")})
    command = "cd /home/natha/grantspider && gh pr create --base main --title t"
    assert_too_soon(*run(command, checkouts=checkouts))


def test_omitted_head_on_a_feature_branch_is_allowed():
    checkouts = FakeCheckouts({"/home/natha/grantspider": g.Checkout(GS_ORIGIN, "feat/x")})
    command = "cd /home/natha/grantspider && gh pr create --base main --title t"
    assert_allowed(*run(command, checkouts=checkouts))


def test_omitted_head_with_an_unreadable_branch_is_treated_as_a_promote():
    """Fail closed: an unreadable head inside the window is refused, not waved through."""
    checkouts = FakeCheckouts({"/home/natha/grantspider": g.Checkout(GS_ORIGIN, None)})
    command = "cd /home/natha/grantspider && gh pr create --base main --title t"
    assert_too_soon(*run(command, checkouts=checkouts))


def test_a_flag_value_that_looks_like_a_flag_is_not_read_as_one():
    command = "gh pr create --repo NathanKrupa/grantspider --title --base --base staging --head staging"
    assert_allowed(*run(command))


# --- the REST form -------------------------------------------------------------


def test_the_rest_form_is_refused():
    assert_too_soon(*run(GS_REST))


@pytest.mark.parametrize(
    "command",
    [
        "gh api -X POST /repos/NathanKrupa/grantspider/pulls -f base=main -f head=staging",
        "gh api --method=POST repos/NathanKrupa/grantspider/pulls --field=base=main -Fhead=staging",
        "gh api repos/NathanKrupa/grantspider/pulls -f head=NathanKrupa:staging -f base=main",
        "gh api repos/NathanKrupa/grantspider/pulls --input body.json",
    ],
)
def test_rest_spellings_are_refused(command):
    assert_too_soon(*run(command))


def test_the_rest_form_resolves_owner_and_repo_placeholders_from_the_cwd():
    checkouts = FakeCheckouts({"/home/natha/grantspider": g.Checkout(GS_ORIGIN, "main")})
    command = "cd /home/natha/grantspider && gh api 'repos/{owner}/{repo}/pulls' -f base=main -f head=staging"
    assert_too_soon(*run(command, checkouts=checkouts))


@pytest.mark.parametrize(
    "command",
    [
        "gh api repos/NathanKrupa/grantspider/pulls",
        "gh api 'repos/NathanKrupa/grantspider/pulls?state=closed&base=main&head=NathanKrupa:staging'",
        "gh api -X GET repos/NathanKrupa/grantspider/pulls -f base=main -f head=staging",
        "gh api repos/NathanKrupa/grantspider/pulls -f base=staging -f head=feat/x",
        "gh api repos/NathanKrupa/aigranthelper/pulls -f base=main -f head=staging",
        "gh api repos/NathanKrupa/grantspider/pulls/12/merge -X PUT",
    ],
)
def test_rest_reads_and_other_targets_are_allowed(command):
    github = FakeGitHub(ago=timedelta(days=2))
    assert_allowed(*run(command, github=github))
    assert github.calls == 0


# --- reading GitHub's answer ----------------------------------------------------


def _pull(number, merged_at, *, base="main", head="staging"):
    return {"number": number, "merged_at": merged_at, "base": {"ref": base}, "head": {"ref": head}}


def test_latest_merge_takes_the_newest_merged_promote():
    payload = json.dumps(
        [
            _pull(1, "2026-10-20T00:00:00Z"),
            _pull(2, None),
            _pull(3, "2026-10-26T02:34:39Z"),
            _pull(4, "2026-10-27T00:00:00Z", head="hotfix/x"),
            _pull(5, "2026-10-27T00:00:00Z", base="staging"),
        ]
    )
    last = g.latest_merge(payload)
    assert last == g.LastPromote(number=3, merged_at=datetime(2026, 10, 26, 2, 34, 39, tzinfo=UTC))


def test_latest_merge_with_no_merged_promote_is_none():
    assert g.latest_merge(json.dumps([_pull(2, None)])) is None


@pytest.mark.parametrize("payload", ["not json", '{"message": "Bad credentials"}', '[{"number": 1}]', "[1]"])
def test_an_unreadable_answer_is_a_lookup_failure(payload):
    with pytest.raises(g.LookupFailed):
        g.latest_merge(payload)


# --- end to end: the hook as Claude Code runs it, with a fake gh on PATH -------------


def _hook(tmp_path, command, *, gh_stdout="[]", gh_exit=0):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (tmp_path / "gh.out").write_text(gh_stdout, encoding="utf-8")
    gh = fake_bin / "gh"
    gh.write_text(f'#!/bin/sh\ncat "{tmp_path / "gh.out"}"\nexit {gh_exit}\n', encoding="utf-8")
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    env.pop("GH_REPO", None)
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _merged(ago: timedelta) -> str:
    merged_at = (datetime.now(UTC) - ago).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps([_pull(3400, merged_at)])


def test_the_hook_refuses_a_recent_promote_end_to_end(tmp_path):
    result = _hook(tmp_path, GS_PROMOTE, gh_stdout=_merged(timedelta(days=2)))
    assert result.returncode == 2
    assert TOO_SOON in result.stderr
    assert "(PR #3400)" in result.stderr
    assert "Traceback" not in result.stderr


def test_the_hook_allows_a_promote_a_week_on_end_to_end(tmp_path):
    result = _hook(tmp_path, GS_PROMOTE, gh_stdout=_merged(timedelta(days=7)))
    assert result.returncode == 0
    assert result.stderr == ""


def test_the_hook_refuses_when_gh_fails_end_to_end(tmp_path):
    result = _hook(tmp_path, GS_REST, gh_stdout="", gh_exit=1)
    assert result.returncode == 2
    assert COULD_NOT_LOOK in result.stderr
    assert TOO_SOON not in result.stderr
    assert "Traceback" not in result.stderr


def test_the_hook_ignores_other_tools_and_bad_input(tmp_path):
    event = {"tool_name": "Edit", "tool_input": {"command": GS_PROMOTE}}
    for payload in (json.dumps(event), "not json"):
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)], input=payload, capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stderr == ""
