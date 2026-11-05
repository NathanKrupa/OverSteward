# ABOUTME: Tests for guard_promote_ci_red — refuse a GS or AG staging->main promote while ci-red is open.
# ABOUTME: GitHub and git are reached only through injected seams; the end-to-end runs use a fake gh.

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _load():
    rel = Path("shared") / "scripts" / "dev" / "guard_promote_ci_red.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("guard_promote_ci_red", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod, candidate
    raise AssertionError(f"could not locate {rel}")


g, HOOK_PATH = _load()

GS = "nathankrupa/grantspider"
AG = "nathankrupa/aigranthelper"
GS_PROMOTE = "gh pr create --repo NathanKrupa/grantspider --base main --head staging --title t"
AG_PROMOTE = "gh pr create --repo NathanKrupa/aigranthelper --base main --head staging --title t"
GS_ORIGIN = "git@github.com:NathanKrupa/grantspider.git"
AG_ORIGIN = "git@github.com:NathanKrupa/aigranthelper.git"

RED = "BLOCKED — staging is red"
COULD_NOT_LOOK = "BLOCKED — could not check"
UNRECORDED = "BLOCKED — the PROMOTE_OVER_CI_RED override could not be recorded"
OVERRIDE_BODY = "PROMOTE OVERRIDE: staging→main — {}"


def red(repo: str, number: int, title: str = "ci is red on PR #1") -> g.RedIssue:
    return g.RedIssue(repo, number, title)


class FakeRedIssues:
    """The ci-red listing seam: open issues per repo, or a canned failure; records who was asked."""

    def __init__(self, issues: dict[str, list] | None = None, *, fails: str | None = None) -> None:
        self._issues = issues or {}
        self._fails = fails
        self.asked: list[str] = []

    def __call__(self, repo: str):
        self.asked.append(repo)
        if self._fails is not None:
            raise g.LookupFailed(self._fails)
        return list(self._issues.get(repo, []))


class FakeComments:
    """The comment seam: records each comment; fails on the issue numbers in ``fails_on``."""

    def __init__(self, fails_on: frozenset[int] = frozenset()) -> None:
        self._fails_on = fails_on
        self.attempted: list[tuple[str, int, str]] = []
        self.posted: list[tuple[str, int, str]] = []

    def __call__(self, issue, body: str) -> None:
        self.attempted.append((issue.repo, issue.number, body))
        if issue.number in self._fails_on:
            raise g.CommentFailed("gh issue comment exited 1: HTTP 502")
        self.posted.append((issue.repo, issue.number, body))


class FakeCheckouts:
    """The git seam: what each directory's origin and current branch are."""

    def __init__(self, checkouts: dict[str, g.Checkout] | None = None) -> None:
        self._checkouts = checkouts or {}
        self.asked: list[str] = []

    def __call__(self, path: str):
        self.asked.append(path)
        return self._checkouts.get(path, g.Checkout(origin=None, branch=None))


def run(command, *, issues=None, comments=None, checkouts=None, cwd="/home/natha/OverSteward", environ=None):
    issues = issues if issues is not None else FakeRedIssues({GS: [red(GS, 3530)]})
    return g.evaluate(
        command,
        cwd,
        environ=environ or {},
        read_checkout=checkouts or FakeCheckouts(),
        list_red_issues=issues,
        post_comment=comments if comments is not None else FakeComments(),
    )


def assert_red(code: int, message: str) -> None:
    assert code == 2
    assert RED in message
    assert COULD_NOT_LOOK not in message
    assert "Traceback" not in message


def assert_allowed(code: int, message: str) -> None:
    assert code == 0
    assert "BLOCKED" not in message
    assert "Traceback" not in message


# --- guard red: an open ci-red issue refuses the promote --------------------------


def test_one_open_ci_red_issue_refuses_the_promote_and_names_it():
    issues = FakeRedIssues({GS: [red(GS, 3530, "ci is red on PR #3529")]})
    code, message = run(GS_PROMOTE, issues=issues)
    assert_red(code, message)
    assert "nathankrupa/grantspider#3530  ci is red on PR #3529" in message
    assert "PROMOTE_OVER_CI_RED='<why production needs this now>'" in message
    assert issues.asked == [GS]


def test_every_open_issue_is_listed():
    issues = FakeRedIssues({GS: [red(GS, 3530), red(GS, 3531)]})
    code, message = run(GS_PROMOTE, issues=issues)
    assert_red(code, message)
    assert "2 open ci-red issue(s)" in message
    assert "#3530" in message and "#3531" in message


def test_no_open_ci_red_issue_allows_the_promote():
    issues = FakeRedIssues({})
    code, message = run(GS_PROMOTE, issues=issues)
    assert_allowed(code, message)
    assert message == ""
    assert issues.asked == [GS]


def test_an_issue_on_the_other_repo_does_not_refuse():
    """The lookup is the promote's own repo: an AG red does not hold a GS promote."""
    issues = FakeRedIssues({AG: [red(AG, 2600)]})
    assert_allowed(*run(GS_PROMOTE, issues=issues))
    assert issues.asked == [GS]


# --- guard look: could not look is its own refusal ------------------------------------


def test_a_failed_lookup_refuses_with_could_not_look_text():
    code, message = run(GS_PROMOTE, issues=FakeRedIssues(fails="gh api exited 1: HTTP 502"))
    assert code == 2
    assert COULD_NOT_LOOK in message
    assert "gh api exited 1: HTTP 502" in message
    assert RED not in message
    assert "Traceback" not in message


def test_the_red_and_could_not_look_texts_differ():
    _, red_text = run(GS_PROMOTE)
    _, look_text = run(GS_PROMOTE, issues=FakeRedIssues(fails="x"))
    assert RED in red_text and RED not in look_text
    assert COULD_NOT_LOOK in look_text and COULD_NOT_LOOK not in red_text


# --- guard scope: what is not a promote never reaches GitHub ----------------------------


def test_a_pr_into_staging_is_allowed_without_a_lookup():
    """With the repo and head unreadable, only the base keeps this from being a promote."""
    issues, checkouts = FakeRedIssues({GS: [red(GS, 1)], AG: [red(AG, 2)]}), FakeCheckouts()
    assert_allowed(*run("gh pr create --base staging", issues=issues, checkouts=checkouts))
    assert issues.asked == []


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --repo NathanKrupa/grantspider --base staging --head feat/x --title t",
        "gh pr create --repo NathanKrupa/grantspider --base main --head hotfix/x --title t",
        "gh pr create --repo NathanKrupa/OverSteward --base main --head staging --title t",
        "gh pr create --repo NathanKrupa/grantspider --head staging --title t",
        "gh api repos/NathanKrupa/grantspider/pulls",
        "gh api repos/NathanKrupa/aigranthelper/pulls -f base=staging -f head=feat/x",
        f'git commit -m "notes; {AG_PROMOTE}"',
        "git status && gh pr list",
    ],
)
def test_what_is_not_a_promote_is_allowed_without_a_lookup(command):
    issues = FakeRedIssues({GS: [red(GS, 1)], AG: [red(AG, 2)]})
    assert_allowed(*run(command, issues=issues))
    assert issues.asked == []


# --- guard AG: aigranthelper is watched too ------------------------------------------------


def test_an_aigranthelper_promote_is_refused():
    issues = FakeRedIssues({AG: [red(AG, 2600)]})
    code, message = run(AG_PROMOTE, issues=issues)
    assert_red(code, message)
    assert "nathankrupa/aigranthelper#2600" in message
    assert issues.asked == [AG]


def test_an_aigranthelper_promote_with_the_base_omitted_is_refused():
    """AG's default branch is main, so an omitted --base opens a promote there."""
    issues = FakeRedIssues({AG: [red(AG, 2600)]})
    assert_red(*run("gh pr create --repo NathanKrupa/aigranthelper --head staging", issues=issues))
    assert issues.asked == [AG]


def test_an_aigranthelper_checkout_on_staging_with_nothing_named_is_refused():
    checkouts = FakeCheckouts({"/home/natha/aigranthelper": g.Checkout(AG_ORIGIN, "staging")})
    issues = FakeRedIssues({AG: [red(AG, 2600)]})
    command = "cd /home/natha/aigranthelper && gh pr create --title t"
    assert_red(*run(command, issues=issues, checkouts=checkouts))
    assert issues.asked == [AG]


def test_the_rest_form_on_aigranthelper_is_refused():
    issues = FakeRedIssues({AG: [red(AG, 2600)]})
    command = "gh api repos/NathanKrupa/aigranthelper/pulls -f base=main -f head=staging"
    assert_red(*run(command, issues=issues))


# --- a repo the guard could not read asks both --------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --base main --head staging",
        "gh pr create --head staging",
        'cd "$AG" && gh pr create --base main',
    ],
)
def test_an_unread_repo_is_checked_against_every_watched_repo(command):
    issues = FakeRedIssues({AG: [red(AG, 2600)]})
    assert_red(*run(command, issues=issues))
    assert issues.asked == [AG, GS]


def test_a_gs_checkout_with_the_base_omitted_is_not_a_promote():
    checkouts = FakeCheckouts({"/home/natha/grantspider": g.Checkout(GS_ORIGIN, "staging")})
    issues = FakeRedIssues({GS: [red(GS, 1)]})
    command = "cd /home/natha/grantspider && gh pr create --title t"
    assert_allowed(*run(command, issues=issues, checkouts=checkouts))
    assert issues.asked == []


# --- guard override: allowed only once every comment has landed --------------------------


def test_the_override_comments_on_every_issue_and_allows():
    issues = FakeRedIssues({GS: [red(GS, 3530), red(GS, 3531)]})
    comments = FakeComments()
    code, message = run(f"PROMOTE_OVER_CI_RED='prod 500 on /foundations' {GS_PROMOTE}", issues=issues, comments=comments)
    assert_allowed(code, message)
    body = OVERRIDE_BODY.format("prod 500 on /foundations")
    assert comments.posted == [(GS, 3530, body), (GS, 3531, body)]
    assert "recorded on nathankrupa/grantspider#3530, nathankrupa/grantspider#3531" in message
    assert "reason: prod 500 on /foundations" in message


def test_a_failing_comment_refuses_the_override():
    comments = FakeComments(fails_on=frozenset({3530}))
    code, message = run(f"PROMOTE_OVER_CI_RED=why {GS_PROMOTE}", comments=comments)
    assert code == 2
    assert UNRECORDED in message
    assert "Comment failed on nathankrupa/grantspider#3530" in message
    assert "Already recorded on: none" in message
    assert comments.attempted == [(GS, 3530, OVERRIDE_BODY.format("why"))]
    assert "Traceback" not in message


def test_a_failure_on_the_second_comment_refuses_and_names_what_landed():
    issues = FakeRedIssues({GS: [red(GS, 3530), red(GS, 3531)]})
    comments = FakeComments(fails_on=frozenset({3531}))
    code, message = run(f"PROMOTE_OVER_CI_RED=why {GS_PROMOTE}", issues=issues, comments=comments)
    assert code == 2
    assert UNRECORDED in message
    assert "Already recorded on: nathankrupa/grantspider#3530" in message


@pytest.mark.parametrize("prefix", ["PROMOTE_OVER_CI_RED=", "PROMOTE_OVER_CI_RED=''", "PROMOTE_OVER_CI_RED='   '"])
def test_a_blank_override_is_refused_and_records_nothing(prefix):
    comments = FakeComments()
    code, message = run(f"{prefix} {GS_PROMOTE}", comments=comments)
    assert_red(code, message)
    assert "an empty PROMOTE_OVER_CI_RED does not count" in message
    assert comments.attempted == []


def test_the_override_in_the_session_environment_does_not_count():
    comments = FakeComments()
    assert_red(*run(GS_PROMOTE, environ={"PROMOTE_OVER_CI_RED": "standing"}, comments=comments))
    assert comments.attempted == []


def test_an_override_on_another_command_does_not_count():
    comments = FakeComments()
    assert_red(*run(f"PROMOTE_OVER_CI_RED=why echo hi && {GS_PROMOTE}", comments=comments))
    assert comments.attempted == []


def test_an_override_with_nothing_red_records_nothing():
    comments = FakeComments()
    code, message = run(f"PROMOTE_OVER_CI_RED=why {GS_PROMOTE}", issues=FakeRedIssues({}), comments=comments)
    assert_allowed(code, message)
    assert message == ""
    assert comments.attempted == []


def test_an_override_cannot_pass_a_failed_lookup():
    """With no listing there is nowhere to record the override, so it is refused."""
    comments = FakeComments()
    code, message = run(f"PROMOTE_OVER_CI_RED=why {GS_PROMOTE}", issues=FakeRedIssues(fails="down"), comments=comments)
    assert code == 2
    assert COULD_NOT_LOOK in message
    assert "an empty PROMOTE_OVER_CI_RED" not in message
    assert comments.attempted == []


@pytest.mark.parametrize(
    "command",
    [
        f"env PROMOTE_OVER_CI_RED=why {AG_PROMOTE}",
        f"bash -c 'PROMOTE_OVER_CI_RED=why {AG_PROMOTE}'",
    ],
)
def test_an_override_carried_by_a_wrapper_is_the_promotes_own(command):
    issues, comments = FakeRedIssues({AG: [red(AG, 2600)]}), FakeComments()
    assert_allowed(*run(command, issues=issues, comments=comments))
    assert comments.posted == [(AG, 2600, OVERRIDE_BODY.format("why"))]


def test_the_cadence_override_is_not_this_override():
    """GS_PROMOTE_HOTFIX answers the cadence guard; it does not pass a red."""
    comments = FakeComments()
    assert_red(*run(f"GS_PROMOTE_HOTFIX=why {GS_PROMOTE}", comments=comments))
    assert comments.attempted == []


# --- reading GitHub's answer -----------------------------------------------------------


def test_parse_red_issues_reads_number_and_title():
    payload = json.dumps([{"number": 3530, "title": "ci is red on PR #3529"}])
    assert g.parse_red_issues(GS, payload) == [red(GS, 3530, "ci is red on PR #3529")]


def test_parse_red_issues_skips_pull_requests():
    """The REST issues listing carries pull requests too; only issues are ci-red issues."""
    payload = json.dumps(
        [
            {"number": 3530, "title": "ci is red on PR #3529"},
            {"number": 3529, "title": "feat: x", "pull_request": {"url": "u"}},
        ]
    )
    assert g.parse_red_issues(GS, payload) == [red(GS, 3530, "ci is red on PR #3529")]


def test_the_lookup_reads_rest_not_the_search_index():
    """The REST listing, filtered to the label and to open issues, one page at the limit."""
    assert g.red_issues_endpoint(GS) == (
        f"repos/{GS}/issues?labels=ci-red&state=open&per_page={g.ISSUE_LIMIT}"
    )


@pytest.mark.parametrize("payload", ["not json", "{}", '{"message": "Bad credentials"}', '[{"title": "x"}]', "[1]"])
def test_an_unreadable_answer_is_a_lookup_failure(payload):
    with pytest.raises(g.LookupFailed):
        g.parse_red_issues(GS, payload)


def test_a_listing_that_fills_the_limit_is_a_lookup_failure():
    """The override must comment on every issue; a listing cut short would skip some."""
    full = json.dumps([{"number": n, "title": "t"} for n in range(g.ISSUE_LIMIT)])
    with pytest.raises(g.LookupFailed, match="the limit"):
        g.parse_red_issues(GS, full)
    under = json.dumps([{"number": n, "title": "t"} for n in range(g.ISSUE_LIMIT - 1)])
    assert len(g.parse_red_issues(GS, under)) == g.ISSUE_LIMIT - 1


# --- end to end: the hook as Claude Code runs it, with a fake gh on PATH -------------------


def _hook(tmp_path, command, *, listing="[]", list_exit=0, comment_exit=0):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (tmp_path / "list.out").write_text(listing, encoding="utf-8")
    log = tmp_path / "gh.log"
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'case "$1 $2" in\n'
        f'  "api repos/"*) cat "{tmp_path / "list.out"}"; exit {list_exit} ;;\n'
        f'  "issue comment") exit {comment_exit} ;;\n'
        "esac\n"
        "exit 99\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    env.pop("GH_REPO", None)
    env.pop("PROMOTE_OVER_CI_RED", None)
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


LISTING = json.dumps([{"number": 3530, "title": "ci is red on PR #3529"}])


def test_the_hook_refuses_while_ci_red_is_open_end_to_end(tmp_path):
    result, calls = _hook(tmp_path, GS_PROMOTE, listing=LISTING)
    assert result.returncode == 2
    assert RED in result.stderr
    assert "nathankrupa/grantspider#3530" in result.stderr
    assert "Traceback" not in result.stderr
    assert calls == [f"api {g.red_issues_endpoint(GS)}"]


def test_the_hook_allows_once_nothing_is_red_end_to_end(tmp_path):
    result, _ = _hook(tmp_path, GS_PROMOTE, listing="[]")
    assert result.returncode == 0
    assert result.stderr == ""


def test_the_hook_refuses_when_gh_fails_end_to_end(tmp_path):
    """A readable empty listing on a failed exit: only the exit code says gh failed."""
    result, _ = _hook(tmp_path, AG_PROMOTE, listing="[]", list_exit=1)
    assert result.returncode == 2
    assert COULD_NOT_LOOK in result.stderr
    assert "gh api exited 1" in result.stderr
    assert RED not in result.stderr
    assert "Traceback" not in result.stderr


def test_the_hook_records_the_override_end_to_end(tmp_path):
    result, calls = _hook(tmp_path, f"PROMOTE_OVER_CI_RED='prod down' {GS_PROMOTE}", listing=LISTING)
    assert result.returncode == 0
    assert "recorded on nathankrupa/grantspider#3530" in result.stderr
    assert calls[-1] == (
        "issue comment 3530 --repo nathankrupa/grantspider --body "
        + OVERRIDE_BODY.format("prod down")
    )


def test_the_hook_refuses_an_unrecorded_override_end_to_end(tmp_path):
    result, _ = _hook(tmp_path, f"PROMOTE_OVER_CI_RED=why {GS_PROMOTE}", listing=LISTING, comment_exit=1)
    assert result.returncode == 2
    assert UNRECORDED in result.stderr
    assert "gh issue comment exited 1" in result.stderr
    assert "Traceback" not in result.stderr


def test_the_hook_ignores_other_tools_and_bad_input(tmp_path):
    event = {"tool_name": "Edit", "tool_input": {"command": GS_PROMOTE}}
    for payload in (json.dumps(event), "not json"):
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)], input=payload, capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stderr == ""
