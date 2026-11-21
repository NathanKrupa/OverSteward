# ABOUTME: The promote guards read text their lexer rejects, by the lexer's own rules, before deciding.
# ABOUTME: Every row runs against both guards, each with its own state stand-in that refuses a promote.

"""Text the promote guards' lexer rejects is read before it is decided.

F1 reads the text as far as the lexer got; F2 reads again each line the lexer
began inside a quote; W, the wide reading (quote characters deleted, no
comment rule), only adds what would make a found call a promote. Each guard's
stand-in refuses every promote it sees: the cadence guard's last promote was
two days ago, and the ci-red guard has an open red issue on both repos. A row
"allowed, unlooked" also asserts the lookup seam was never called.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import NamedTuple

import pytest

from tests.dev import test_guard_promote_cadence as cadence_tests
from tests.dev import test_guard_promote_ci_red as ci_red_tests

OVERSTEWARD = "/home/natha/OverSteward"
GS_CHECKOUT = "/home/natha/grantspider"
GS_ORIGIN = "git@github.com:NathanKrupa/grantspider.git"

# P, a complete promote; N, an ordinary pull request on grantspider, base first.
P = "gh pr create --repo NathanKrupa/grantspider --base main --head staging --title t"
N = "gh pr create --base staging --repo NathanKrupa/grantspider --head fix/x --title t"
# A body, a quoted heredoc inside a quoted substitution, holding one stray
# double quote: bash reads it as data, the lexer closes the quote there.
BODY = " --body \"$(cat <<'EOF'\nSummary\nsay \" here\nEOF\n)\""
# A heredoc whose body holds one apostrophe: the lexer opens a quote to the end.
APOSTROPHE = "cat > notes.md <<'EOF'\nit's done\nEOF\n"


class Outcome(NamedTuple):
    code: int
    message: str
    lookups: int
    recorded: bool


class Guard(NamedTuple):
    module: object
    override: str
    refusal: str
    run: Callable[..., Outcome]


def _cadence(command: str, *, cwd: str, checkouts) -> Outcome:
    github = cadence_tests.FakeGitHub(ago=timedelta(days=2))
    code, message = cadence_tests.run(command, github=github, checkouts=checkouts, cwd=cwd)
    return Outcome(code, message, github.calls, "reason: " in message)


def _ci_red(command: str, *, cwd: str, checkouts) -> Outcome:
    issues = ci_red_tests.FakeRedIssues(
        {ci_red_tests.GS: [ci_red_tests.red(ci_red_tests.GS, 3530)],
         ci_red_tests.AG: [ci_red_tests.red(ci_red_tests.AG, 900)]}
    )
    comments = ci_red_tests.FakeComments()
    code, message = ci_red_tests.run(
        command, issues=issues, comments=comments, checkouts=checkouts, cwd=cwd
    )
    return Outcome(code, message, len(issues.asked), bool(comments.posted))


GUARDS = {
    "cadence": Guard(cadence_tests.g, "GS_PROMOTE_HOTFIX", cadence_tests.TOO_SOON, _cadence),
    "ci-red": Guard(ci_red_tests.g, "PROMOTE_OVER_CI_RED", ci_red_tests.RED, _ci_red),
}


@pytest.fixture(params=sorted(GUARDS))
def guard(request) -> Guard:
    return GUARDS[request.param]


def decide(guard: Guard, command: str, *, cwd: str = OVERSTEWARD, checkouts=None) -> Outcome:
    """The guard's verdict on ``command``, which must be text its lexer rejects."""
    assert guard.module._lex(command) is None, "the fixture parses: it is not this file's subject"
    return guard.run(command, cwd=cwd, checkouts=checkouts)


def assert_refused(guard: Guard, outcome: Outcome) -> None:
    assert outcome.code == 2
    assert guard.refusal in outcome.message
    assert "Traceback" not in outcome.message


def assert_allowed_unlooked(outcome: Outcome) -> None:
    assert (outcome.code, outcome.message, outcome.lookups) == (0, "", 0)


def checkouts(**branches: str | None):
    """A git seam: ``here`` (the hook's cwd) or ``gs`` as a grantspider checkout on that branch."""
    paths = {"here": OVERSTEWARD, "gs": GS_CHECKOUT}
    return cadence_tests.FakeCheckouts(
        {paths[name]: Checkout(GS_ORIGIN, branch) for name, branch in branches.items()}
    )


class Checkout(NamedTuple):
    """What the parser reads of a checkout, the same for both guards."""

    origin: str | None
    branch: str | None


# --- rows 1 to 4: a stray quote in a quoted body ------------------------------


def test_row1_a_promote_whose_body_holds_a_stray_quote_is_refused(guard):
    assert_refused(guard, decide(guard, P + BODY))


def test_row2_an_ordinary_pr_with_that_body_is_allowed_unlooked(guard):
    assert_allowed_unlooked(decide(guard, N + BODY))


@pytest.mark.parametrize("repo", ["grantspider", "aigranthelper"])
def test_row3_an_ordinary_pr_titled_first_with_parentheses_is_allowed(guard, repo):
    """Own flags come from an exact reading: with quotes removed the title's
    parenthesis would cut the call, and on aigranthelper an unread base is main."""
    command = (
        f'gh pr create --title "fix (x)" --base staging --head fix/x --repo NathanKrupa/{repo}'
        + BODY
    )
    assert_allowed_unlooked(decide(guard, command))


def test_row4_a_promote_titled_first_with_parentheses_is_refused(guard):
    command = 'gh pr create --title "fix (x)" --repo NathanKrupa/grantspider --base main --head staging'
    assert_refused(guard, decide(guard, command + BODY))


# --- rows 5 and 6: lines the lexer began inside a quote -----------------------


def test_row5_a_promote_line_after_a_stray_quote_in_an_unquoted_body_is_refused(guard):
    """As in text that parses, an unquoted body's lines are read as lines."""
    assert_refused(guard, decide(guard, "cat > notes.md <<EOF\nit's done\n" + P + "\nEOF"))


def test_row6_a_promote_written_as_prose_in_a_quoted_body_is_refused(guard):
    """A counted cost (prose-call-line): telling prose from mis-tracked quoting
    would need a construct finder, which the rule does not have."""
    body = " --body \"$(cat <<'EOF'\nTo promote, run:\n" + P + "\nsay \" here\nEOF\n)\""
    assert_refused(guard, decide(guard, N + body))


# --- rows 7 to 11: where the lexer lost the thread ------------------------------


def test_row7_a_promote_before_an_unterminated_quote_on_a_later_line_is_refused(guard):
    assert_refused(guard, decide(guard, P + "\necho 'oops"))


def test_row8_a_call_whose_line_holds_the_open_quote_and_no_base_is_allowed(guard):
    """grantspider's default base is staging, and nothing written names main."""
    command = 'gh pr create --repo NathanKrupa/grantspider --head staging --title "oops'
    assert_allowed_unlooked(decide(guard, command))


def test_row9_the_same_call_with_base_staging_before_the_break_is_allowed(guard):
    command = 'gh pr create --repo NathanKrupa/grantspider --base staging --head staging --title "oops'
    assert_allowed_unlooked(decide(guard, command))


def test_row10_a_promote_followed_by_a_lone_trailing_backslash_is_refused(guard):
    assert_refused(guard, decide(guard, P + " \\"))


@pytest.mark.parametrize(
    "command",
    [
        "echo 'oops",
        "gh pr view 12 --repo NathanKrupa/grantspider\necho 'oops",
        "gh api repos/NathanKrupa/grantspider/pulls\necho 'oops",
        APOSTROPHE + "gh pr list --repo NathanKrupa/grantspider --base main",
    ],
)
def test_row11_rejected_text_opening_no_pull_request_is_allowed_unlooked(guard, command):
    assert_allowed_unlooked(decide(guard, command))


# --- row 12: the override -----------------------------------------------------


def test_row12_the_override_on_the_promotes_own_prefix_is_honoured(guard):
    outcome = decide(guard, f"{guard.override}='prod is down' " + P + BODY)
    assert outcome.code == 0 and outcome.recorded
    assert "prod is down" in outcome.message


def test_row12_the_override_on_a_line_read_again_is_honoured(guard):
    outcome = decide(guard, APOSTROPHE + f"{guard.override}='prod is down' " + P)
    assert outcome.code == 0 and outcome.recorded


def test_row12_the_override_on_another_command_does_not_count(guard):
    outcome = decide(guard, f"{guard.override}='prod is down' echo x; " + P + BODY)
    assert_refused(guard, outcome)
    assert not outcome.recorded


def test_row12_the_override_on_a_command_before_the_line_read_again_does_not_count(guard):
    outcome = decide(guard, f"{guard.override}=why " + APOSTROPHE + P)
    assert_refused(guard, outcome)
    assert not outcome.recorded


# --- row 13: a script inside a command that parses ----------------------------


def test_row13_a_rejected_shell_script_holding_a_promote_is_refused(guard):
    command = 'bash -c "' + "cat <<EOF\nit's\nEOF\n" + P + '"'
    assert guard.module._lex(command) is not None
    assert guard.module._lex("cat <<EOF\nit's\nEOF\n" + P) is None
    assert_refused(guard, guard.run(command, cwd=OVERSTEWARD, checkouts=None))


# --- row 14: no heredoc form is special, because nothing looks for one ---------


@pytest.mark.parametrize(
    "prefix",
    [
        "cat <<'EOF'\nit's\nEOF\n",
        "cat <<\\EOF\nit's\nEOF\n",
        "cat <<-EOF\n\tit's\n\tEOF\n",
        'echo "a <<EOF b"\nit\'s\n',
        "echo x # <<EOF\nit's\n",
        "cat <<< \"it's\"; cat <<EOF\nit's\nEOF\n",
        "echo $((1<<2))\ncat <<EOF\nit's\nEOF\n",
        "cat <<A <<B\nit's\nA\nB\n",
        'x="$(cat <<EOF\nsay " here\nEOF\n)"\n',
    ],
)
def test_row14_a_promote_after_a_stray_quote_is_refused_whatever_the_form(guard, prefix):
    assert_refused(guard, decide(guard, prefix + P))


@pytest.mark.parametrize(
    "suffix",
    [
        " --body-file - <<'EOF'\nit's\nEOF",
        " --body-file - <<\\EOF\nit's\nEOF",
        " --body-file - <<-EOF\n\tit's\n\tEOF",
        " --body-file - <<A <<B\nit's\nA\nB",
    ],
)
def test_row14_a_promote_whose_own_heredoc_holds_a_stray_quote_is_refused(guard, suffix):
    assert_refused(guard, decide(guard, P + suffix))


# --- rows h1 to h4: a hash cannot hide a flag ----------------------------------


def test_h1_a_promote_whose_quoted_title_starts_with_a_hash_is_refused(guard):
    command = 'gh pr create --repo NathanKrupa/grantspider --title "#12 fix" --base main --head staging'
    assert_refused(guard, decide(guard, command + BODY))


def test_h2_base_and_head_behind_a_quoted_hash_after_the_body_are_read(guard):
    """F1 and F2 lose them: the lexer holds the hash as a comment's start after the
    stray quote. W, with no comment rule, still sees them."""
    command = (
        "gh pr create --repo NathanKrupa/grantspider --title t"
        + BODY
        + ' --label "#x" --base main --head staging'
    )
    assert_refused(guard, decide(guard, command))


def test_h3_a_hash_line_in_an_ordinary_prs_body_is_allowed_unlooked(guard):
    body = " --body \"$(cat <<'EOF'\n# Heading\nsay \" here\nEOF\n)\""
    assert_allowed_unlooked(decide(guard, N + body))


def test_h4_a_comment_naming_a_promote_after_an_ordinary_pr_is_refused(guard):
    """A counted cost (comment-names-promote): W has no comment rule."""
    command = N + BODY + "  # then gh pr create --base main --head staging"
    assert_refused(guard, decide(guard, command))


# --- rows b1 to b3: the base and the head -------------------------------------


def test_b1_a_base_main_after_the_break_overrides_a_base_read_before_it(guard):
    command = "gh pr create --repo NathanKrupa/grantspider --base staging --title t"
    assert_refused(guard, decide(guard, command + BODY + " --base main --head staging"))


@pytest.mark.parametrize(("repo", "refused"), [("aigranthelper", True), ("grantspider", False)])
def test_b2_an_unwritten_base_is_the_repos_default(repo, refused):
    """ci-red: aigranthelper's default branch is main, grantspider's is staging."""
    guard = GUARDS["ci-red"]
    command = f"gh pr create --repo NathanKrupa/{repo} --head staging --title t" + BODY
    outcome = decide(guard, command)
    if refused:
        assert_refused(guard, outcome)
    else:
        assert_allowed_unlooked(outcome)


def test_b2_cadence_holds_only_grantspider(guard):
    command = "gh pr create --repo NathanKrupa/grantspider --head staging --title t" + BODY
    assert_allowed_unlooked(decide(guard, command))


_PROSE_BASE = " --body \"$(cat <<'EOF'\nNext time pass --base main\nsay \" here\nEOF\n)\""


def test_b3_a_written_base_main_and_a_feature_checkout_is_allowed(guard):
    command = "gh pr create --repo NathanKrupa/grantspider --base staging --title t" + _PROSE_BASE
    assert_allowed_unlooked(decide(guard, command, checkouts=checkouts(here="fix/x")))


def test_b3_a_written_base_main_and_an_unreadable_branch_is_refused(guard):
    command = "gh pr create --repo NathanKrupa/grantspider --base staging --title t" + _PROSE_BASE
    assert_refused(guard, decide(guard, command, checkouts=checkouts(here=None)))


# --- rows c1 and c2: lines and directories ------------------------------------


def test_c1_a_promote_on_a_line_after_the_lexers_error_is_refused(guard):
    assert_refused(guard, decide(guard, APOSTROPHE + P))


_C2 = "cd /home/natha/grantspider\ngh pr create --base main --head staging --title t"


def test_c2_the_repo_is_read_from_the_directory_an_earlier_line_moved_to(guard):
    seam = checkouts(gs="staging")
    assert_refused(guard, decide(guard, _C2 + BODY, checkouts=seam))
    assert GS_CHECKOUT in seam.asked


def test_c2_pin_the_parsed_twin_is_refused(guard):
    """A pin: text that parses keeps the verdict the line-true reading gives it."""
    assert guard.module._lex(_C2) is not None
    assert_refused(guard, guard.run(_C2, cwd=OVERSTEWARD, checkouts=checkouts(gs="staging")))


def test_rejected_text_is_read_once(guard):
    """Both readings reject it; the fallback reads it once, so the repo is asked once."""
    command = "gh pr create --base main --head staging --title t" + BODY
    seam = checkouts(here="staging")
    assert_refused(guard, decide(guard, command, checkouts=seam))
    assert seam.asked == [OVERSTEWARD]


# --- row a1: the API form -----------------------------------------------------

_API = "gh api repos/NathanKrupa/grantspider/pulls"
_API_BODY = " -f body=\"$(cat <<'EOF'\nsay \" here\nEOF\n)\""


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (" -f title=t", " -f base=main -f head=staging"),
        (" -f base=staging -f head=staging", " -f base=main"),
        (" -f base=main -f head=fix/x", " -f head=staging"),
        (" -f base=staging -f head=fix/x", " --input pr.json"),
    ],
)
def test_a1_api_fields_after_the_break_make_a_promote(guard, before, after):
    assert_refused(guard, decide(guard, _API + before + _API_BODY + after))


def test_a1_an_api_pull_request_naming_no_promote_is_allowed_unlooked(guard):
    command = _API + " -f base=staging -f head=fix/x" + _API_BODY + " -f title=t"
    assert_allowed_unlooked(decide(guard, command))


# --- rows m1 and mp: the marker characters, and quotes nested in a substitution ---


def test_m1_a_promote_in_text_holding_the_marker_characters_is_refused(guard):
    command = 'echo "\x1c\x1d\x1e\x1f"\n' + APOSTROPHE + P
    assert_refused(guard, decide(guard, command))


_NESTED = ' --body "$(printf "%s" "it\'s")"'


def test_mp_a_promote_whose_flags_follow_nested_quotes_is_refused(guard):
    """The lexer pairs nested quotes wrongly and loses the flags after them; W reads them."""
    command = "gh pr create --repo NathanKrupa/grantspider --title t" + _NESTED
    assert_refused(guard, decide(guard, command + " --base main --head staging"))


def test_mp_an_ordinary_pr_whose_flags_follow_nested_quotes_is_allowed(guard):
    command = "gh pr create --repo NathanKrupa/grantspider --title t" + _NESTED
    assert_allowed_unlooked(decide(guard, command + " --base staging --head fix/x"))


# --- the readings reject the same text -----------------------------------------


@pytest.mark.parametrize(
    "command", [P + BODY, APOSTROPHE + P, P + " \\", 'echo "\x1c\x1d\x1e\x1f"\n' + APOSTROPHE, P]
)
def test_both_readings_reject_exactly_what_lex_rejects(guard, command):
    module = guard.module
    rejected = module._lex(command) is None
    assert (module._token_runs(command) is None) is rejected
    assert (module._line_runs(command) is None) is rejected


# --- end to end, through each hook's own entry point ---------------------------


def _dirs(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    return tmp_path / "a", tmp_path / "b"


def test_the_cadence_hook_refuses_row1_and_is_silent_on_row11(tmp_path):
    first, second = _dirs(tmp_path)
    recent = cadence_tests._merged(timedelta(days=2))
    result = cadence_tests._hook(first, P + BODY, gh_stdout=recent)
    assert result.returncode == 2
    assert cadence_tests.TOO_SOON in result.stderr
    quiet = cadence_tests._hook(second, "echo 'oops", gh_stdout=recent)
    assert (quiet.returncode, quiet.stderr) == (0, "")


def test_the_ci_red_hook_refuses_row1_and_is_silent_on_row11(tmp_path):
    first, second = _dirs(tmp_path)
    result, _ = ci_red_tests._hook(first, P + BODY, listing=ci_red_tests.LISTING)
    assert result.returncode == 2
    assert ci_red_tests.RED in result.stderr
    quiet, calls = ci_red_tests._hook(second, "echo 'oops", listing=ci_red_tests.LISTING)
    assert (quiet.returncode, quiet.stderr, calls) == (0, "", [])
