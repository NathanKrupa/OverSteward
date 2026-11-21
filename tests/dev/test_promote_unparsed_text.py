# ABOUTME: The promote guards read text their lexer rejects, by the lexer's own rules, before deciding.
# ABOUTME: Every row runs against both guards, each with its own state stand-in that refuses a promote.

"""Text the promote guards' lexer rejects is read before it is decided.

F1 reads the text as far as the lexer got; F2 reads again each line the lexer
began inside a quote; W, the wide reading (quote characters deleted, no
comment rule), only adds what would make a found call a promote. Each guard's
stand-in refuses every promote it sees: the cadence guard's last promote was
two days ago, and the ci-red guard has a red issue open on both repos.
"Allowed" also asserts the lookup seam was never called. Row ids name the
handed-over table's rows; a row marked "cost" is a counted false refusal.
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from datetime import timedelta
from typing import NamedTuple

import pytest

from tests.dev import test_guard_promote_cadence as cadence_tests
from tests.dev import test_guard_promote_ci_red as ci_red_tests

HERE, GS_DIR = "/home/natha/OverSteward", "/home/natha/grantspider"
GS_ORIGIN = "git@github.com:NathanKrupa/grantspider.git"
OS_ORIGIN = "git@github.com:NathanKrupa/OverSteward.git"

# P, a complete promote; N, an ordinary pull request on grantspider, base first.
P = "gh pr create --repo NathanKrupa/grantspider --base main --head staging --title t"
N = "gh pr create --base staging --repo NathanKrupa/grantspider --head fix/x --title t"
GS_CALL = "gh pr create --repo NathanKrupa/grantspider"
# A quoted heredoc in a quoted substitution, its body holding one double quote:
# bash reads it as data; the lexer closes the quote there and opens one later.
BODY = " --body \"$(cat <<'EOF'\nSummary\nsay \" here\nEOF\n)\""
# A heredoc whose body holds an apostrophe: the lexer opens a quote to the end.
APOSTROPHE = "cat > notes.md <<'EOF'\nit's done\nEOF\n"
NESTED = ' --body "$(printf "%s" "it\'s")"'
API = "gh api repos/NathanKrupa/grantspider/pulls"
API_BODY = " -f body=\"$(cat <<'EOF'\nsay \" here\nEOF\n)\""


class Checkout(NamedTuple):
    origin: str | None
    branch: str | None


def seam(**dirs: tuple[str | None, str | None]) -> dict[str, Checkout]:
    """What git says of ``here`` (the hook's cwd), ``gs`` and ``ag``, each as (origin, branch)."""
    paths = {"here": HERE, "gs": GS_DIR, "ag": "/home/natha/aigranthelper"}
    return {paths[k]: Checkout(*v) for k, v in dirs.items()}


def fake(dirs: dict[str, Checkout] | None):
    """A fresh git seam over ``dirs``, recording each directory asked about."""
    return cadence_tests.FakeCheckouts(dict(dirs or {}))


REFUSED = {
    "row1": (P + BODY, None),
    "row4": ('gh pr create --title "fix (x)" --repo NathanKrupa/grantspider --base main'
             " --head staging" + BODY, None),
    "row5": ("cat > notes.md <<EOF\nit's done\n" + P + "\nEOF", None),
    "row6-cost": (N + " --body \"$(cat <<'EOF'\nTo promote, run:\n" + P
                  + "\nsay \" here\nEOF\n)\"", None),
    "row7": (P + "\necho 'oops", None),
    "row10": (P + " \\", None),
    "row14-quoted-delimiter": ("cat <<'EOF'\nit's\nEOF\n" + P, None),
    "row14-escaped-delimiter": ("cat <<\\EOF\nit's\nEOF\n" + P, None),
    "row14-dash-operator": ("cat <<-EOF\n\tit's\n\tEOF\n" + P, None),
    "row14-operator-in-quotes": ('echo "a <<EOF b"\nit\'s\n' + P, None),
    "row14-operator-in-comment": ("echo x # <<EOF\nit's\n" + P, None),
    "row14-here-string": ("cat <<< \"it's\"; cat <<EOF\nit's\nEOF\n" + P, None),
    "row14-arithmetic-shift": ("echo $((1<<2))\ncat <<EOF\nit's\nEOF\n" + P, None),
    "row14-two-on-one-line": ("cat <<A <<B\nit's\nA\nB\n" + P, None),
    "row14-in-substitution": ('x="$(cat <<EOF\nsay " here\nEOF\n)"\n' + P, None),
    "row14-own-quoted": (P + " --body-file - <<'EOF'\nit's\nEOF", None),
    "row14-own-escaped": (P + " --body-file - <<\\EOF\nit's\nEOF", None),
    "row14-own-dash": (P + " --body-file - <<-EOF\n\tit's\n\tEOF", None),
    "row14-own-two": (P + " --body-file - <<A <<B\nit's\nA\nB", None),
    "h1": (GS_CALL + ' --title "#12 fix" --base main --head staging' + BODY, None),
    "h2": (GS_CALL + " --title t" + BODY + ' --label "#x" --base main --head staging', None),
    "h4-cost": (N + BODY + "  # then gh pr create --base main --head staging", None),
    "b1": (GS_CALL + " --base staging --title t" + BODY + " --base main --head staging",
           seam(here=(GS_ORIGIN, "fix/x"))),
    "b3-unreadable-branch": (GS_CALL + " --base staging --title t --body \"$(cat <<'EOF'\n"
                             "Next time pass --base main\nsay \" here\nEOF\n)\"",
                             seam(here=(GS_ORIGIN, None))),
    "c1": (APOSTROPHE + P, None),
    "c2": ("cd /home/natha/grantspider\ngh pr create --base main --head staging --title t"
           + BODY, seam(here=(OS_ORIGIN, "master"), gs=(GS_ORIGIN, "staging"))),
    "c2-line-read-again": ("cd /home/natha/grantspider\n" + APOSTROPHE
                           + "gh pr create --base main --head staging --title t",
                           seam(here=(OS_ORIGIN, "master"), gs=(GS_ORIGIN, "staging"))),
    "c3-continued-quoted-line": ('echo "x \\\n' + P + "\necho 'oops", None),
    "w-repo": ("gh pr create --base main --head staging --title t" + BODY
               + " --repo NathanKrupa/grantspider", seam(here=(OS_ORIGIN, "master"))),
    "w-attached-long": (GS_CALL + " --base staging --title t" + BODY
                        + " --base=main --head=staging", seam(here=(GS_ORIGIN, "fix/x"))),
    "w-attached-short": (GS_CALL + " --base staging --title t" + BODY + " -Bmain -Hstaging",
                         seam(here=(GS_ORIGIN, "fix/x"))),
    "a1": (API + " -f title=t" + API_BODY + " -f base=main -f head=staging", None),
    "a1-base": (API + " -f base=staging -f head=staging" + API_BODY + " -f base=main", None),
    "a1-head": (API + " -f base=main -f head=fix/x" + API_BODY + " -f head=staging", None),
    "a1-input": (API + " -f base=staging -f head=fix/x" + API_BODY + " --input pr.json", None),
    "a1-endpoint-after-break": ("gh api --method POST -f base=main -f head=staging" + API_BODY
                                + " repos/NathanKrupa/grantspider/pulls", None),
    "a1-post-after-break": (API + " -X GET -f base=main -f head=staging" + API_BODY + " -X POST",
                            None),
    "c4-cd-read-again-before-a-call": (
        "cat <<EOF\nit's\nEOF\ncd /home/natha/grantspider\ncat <<EOF\nit's\nEOF\n"
        "gh pr create --base main --head staging --title t\ncat <<EOF\nit's\nEOF\n",
        seam(here=(OS_ORIGIN, "master"), gs=(GS_ORIGIN, "staging"))),
    "nested-outer-comment-names-base-cost": (
        "bash -c '" + GS_CALL + ' --head staging --title t --body "$(cat <<EOF\nsay " x\nEOF\n)"'
        + "'\n# --base main\necho 'oops", None),
    "a1-fields-after-break-no-method": (API + " --jq \"$(cat <<'EOF'\nsay \" x\nEOF\n)\""
                                        " -f base=main -f head=staging", None),
    "m1": ('echo "\x1c\x1d\x1e\x1f"\n' + APOSTROPHE + P, None),
    "mp": (GS_CALL + " --title t" + NESTED + " --base main --head staging", None),
}

ALLOWED = {
    "row2": (N + BODY, None),
    "row3-gs": ('gh pr create --title "fix (x)" --base staging --head fix/x'
                " --repo NathanKrupa/grantspider" + BODY, None),
    "row3-ag": ('gh pr create --title "fix (x)" --base staging --head fix/x'
                " --repo NathanKrupa/aigranthelper" + BODY, None),
    "row8": (GS_CALL + ' --head staging --title "oops', None),
    "row9": (GS_CALL + ' --base staging --head staging --title "oops', None),
    "row11-no-call": ("echo 'oops", None),
    "row11-pr-view": ("gh pr view 12 --repo NathanKrupa/grantspider\necho 'oops", None),
    "row11-api-read": (API + "\necho 'oops", None),
    "row11-pr-list": (APOSTROPHE + "gh pr list --repo NathanKrupa/grantspider --base main", None),
    "h3": (N + " --body \"$(cat <<'EOF'\n# Heading\nsay \" here\nEOF\n)\"", None),
    "b2-gs": (GS_CALL + " --head staging --title t" + BODY, None),
    "b3-feature-branch": (GS_CALL + " --base staging --title t --body \"$(cat <<'EOF'\n"
                          "Next time pass --base main\nsay \" here\nEOF\n)\"",
                          seam(here=(GS_ORIGIN, "fix/x"))),
    "a1-ordinary": (API + " -f base=staging -f head=fix/x" + API_BODY + " -f title=t", None),
    "a1-own-base-read": (API + " -f base=staging -f head=staging" + API_BODY, None),
    "a1-explicit-get": (API + " -X GET -f state=open" + API_BODY + " -f base=main", None),
    "a1-other-endpoint-after-break": ("gh api --method POST -f base=main -f head=staging"
                                      + API_BODY + " repos/NathanKrupa/grantspider/issues", None),
    "w-unwatched-repo-written": (GS_CALL + " --head staging --title t --body \"$(cat <<'EOF'\n"
                                 "See --repo NathanKrupa/OverSteward\nsay \" here\nEOF\n)\"", None),
    "mp-ordinary": (GS_CALL + " --title t" + NESTED + " --base staging --head fix/x", None),
}


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


def _cadence(command: str, checkouts) -> Outcome:
    github = cadence_tests.FakeGitHub(ago=timedelta(days=2))
    code, message = cadence_tests.run(command, github=github, checkouts=checkouts, cwd=HERE)
    return Outcome(code, message, github.calls, "reason: " in message)


def _ci_red(command: str, checkouts) -> Outcome:
    gs, ag = ci_red_tests.GS, ci_red_tests.AG
    issues = ci_red_tests.FakeRedIssues({gs: [ci_red_tests.red(gs, 1)], ag: [ci_red_tests.red(ag, 2)]})
    comments = ci_red_tests.FakeComments()
    code, message = ci_red_tests.run(
        command, issues=issues, comments=comments, checkouts=checkouts, cwd=HERE
    )
    return Outcome(code, message, len(issues.asked), bool(comments.posted))


GUARDS = {
    "cadence": Guard(cadence_tests.g, "GS_PROMOTE_HOTFIX", cadence_tests.TOO_SOON, _cadence),
    "ci-red": Guard(ci_red_tests.g, "PROMOTE_OVER_CI_RED", ci_red_tests.RED, _ci_red),
}


@pytest.fixture(params=sorted(GUARDS))
def guard(request) -> Guard:
    return GUARDS[request.param]


def decide(guard: Guard, command: str, dirs=None, checkouts=None) -> Outcome:
    """The guard's verdict on ``command``, which must be text its lexer rejects."""
    assert guard.module._lex(command) is None, "the fixture parses: it is not this file's subject"
    return guard.run(command, checkouts if checkouts is not None else fake(dirs))


def assert_refused(guard: Guard, outcome: Outcome) -> None:
    assert (outcome.code, guard.refusal in outcome.message) == (2, True), outcome.message
    assert "Traceback" not in outcome.message


def assert_allowed_unlooked(outcome: Outcome) -> None:
    assert (outcome.code, outcome.message, outcome.lookups) == (0, "", 0)


@pytest.mark.parametrize("row", REFUSED)
def test_a_promote_in_rejected_text_is_refused(guard, row):
    command, checkouts = REFUSED[row]
    assert_refused(guard, decide(guard, command, checkouts))


@pytest.mark.parametrize("row", ALLOWED)
def test_rejected_text_naming_no_promote_is_allowed_unlooked(guard, row):
    command, checkouts = ALLOWED[row]
    assert_allowed_unlooked(decide(guard, command, checkouts))


def test_b2_an_unwritten_base_on_aigranthelper_is_its_default_main():
    """ci-red only: aigranthelper's default branch is main; cadence does not hold it."""
    command = "gh pr create --repo NathanKrupa/aigranthelper --head staging --title t" + BODY
    assert_refused(GUARDS["ci-red"], decide(GUARDS["ci-red"], command))
    assert_allowed_unlooked(decide(GUARDS["cadence"], command))


def test_w_two_watched_repos_written_could_be_either():
    """ci-red: W names both repos, so the call's repo is unread and both are looked up."""
    command = ("gh pr create --head staging --title t --repo NathanKrupa/grantspider" + BODY
               + " --repo NathanKrupa/aigranthelper")
    outcome = decide(GUARDS["ci-red"], command, seam(here=(OS_ORIGIN, "master")))
    assert_refused(GUARDS["ci-red"], outcome)
    assert outcome.lookups == 2


def test_w_a_repo_written_elsewhere_does_not_clear_the_calls_own():
    """ci-red: the call's own repo is aigranthelper (default main); grantspider written in
    prose must not replace it, or W would clear a promote."""
    command = ("cd /home/natha/aigranthelper\ngh pr create --head staging --title t --body \"$(cat"
               " <<'EOF'\nCompare --repo NathanKrupa/grantspider\nsay \" here\nEOF\n)\"")
    ag = ("git@github.com:NathanKrupa/aigranthelper.git", "fix/x")
    outcome = decide(GUARDS["ci-red"], command, seam(here=(OS_ORIGIN, "master"), ag=ag))
    assert_refused(GUARDS["ci-red"], outcome)


# --- row 12: the override, read from the promote's own prefix ------------------


def test_row12_the_override_on_the_promotes_own_prefix_is_honoured(guard):
    outcome = decide(guard, f"{guard.override}='prod is down' " + P + BODY)
    assert (outcome.code, outcome.recorded) == (0, True)
    assert "prod is down" in outcome.message


def test_row12_the_override_on_a_line_read_again_is_honoured(guard):
    outcome = decide(guard, APOSTROPHE + f"{guard.override}='prod is down' " + P)
    assert (outcome.code, outcome.recorded) == (0, True)


@pytest.mark.parametrize(
    "command",
    [f"{{var}}=why echo x; {P}{BODY}", f"{{var}}=why {APOSTROPHE}{P}"],
    ids=["another-command", "before-the-line-read-again"],
)
def test_row12_the_override_on_another_command_does_not_count(guard, command):
    outcome = decide(guard, command.format(var=guard.override))
    assert_refused(guard, outcome)
    assert not outcome.recorded


# --- row 13, c2's pin, and reading once ------------------------------------------


def test_row13_a_rejected_shell_script_holding_a_promote_is_refused(guard):
    script = "cat <<EOF\nit's\nEOF\n" + P
    command = 'bash -c "' + script + '"'
    assert guard.module._lex(command) is not None and guard.module._lex(script) is None
    assert_refused(guard, guard.run(command, fake(None)))


def test_c2_the_repo_is_read_from_the_directory_an_earlier_line_moved_to(guard):
    command, dirs = REFUSED["c2"]
    checkouts = fake(dirs)
    assert_refused(guard, decide(guard, command, checkouts=checkouts))
    assert checkouts.asked == [GS_DIR]


def test_c2_pin_the_parsed_twin_is_refused(guard):
    """A pin: text that parses keeps the verdict the line-true reading gives it."""
    command = REFUSED["c2"][0].removesuffix(BODY)
    assert guard.module._lex(command) is not None
    assert_refused(guard, guard.run(command, fake(seam(gs=(GS_ORIGIN, "staging")))))


def test_rejected_text_is_read_once(guard):
    """Both readings reject it; the fallback reads it once, so the repo is asked once."""
    checkouts = fake(seam(here=(GS_ORIGIN, "staging")))
    command = "gh pr create --base main --head staging --title t" + BODY
    assert_refused(guard, decide(guard, command, checkouts=checkouts))
    assert checkouts.asked == [HERE]


def test_a_relative_cd_in_rejected_text_ends(guard):
    """Directories reached by re-reading a run are not followed further, so the
    reading ends; an alarm turns a hang into a failure."""
    def ring(*_):
        raise TimeoutError("the reading of rejected text did not end")

    previous = signal.signal(signal.SIGALRM, ring)
    signal.alarm(5)
    try:
        outcome = decide(guard, "cd sub\n" + APOSTROPHE + "cd sub\necho done")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert_allowed_unlooked(outcome)


@pytest.mark.parametrize("row", ["row1", "c1", "row10", "m1"])
def test_both_readings_reject_exactly_what_lex_rejects(guard, row):
    module, command = guard.module, REFUSED[row][0]
    for text in (command, P):
        rejected = module._lex(text) is None
        assert (module._token_runs(text) is None, module._line_runs(text) is None) == (
            rejected,
            rejected,
        )


# --- end to end, through each hook's own entry point ---------------------------


def _dirs(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    return tmp_path / "a", tmp_path / "b"


def test_the_cadence_hook_refuses_row1_and_is_silent_on_row11(tmp_path):
    first, second = _dirs(tmp_path)
    recent = cadence_tests._merged(timedelta(days=2))
    result = cadence_tests._hook(first, P + BODY, gh_stdout=recent)
    assert (result.returncode, cadence_tests.TOO_SOON in result.stderr) == (2, True)
    quiet = cadence_tests._hook(second, "echo 'oops", gh_stdout=recent)
    assert (quiet.returncode, quiet.stderr) == (0, "")


def test_the_ci_red_hook_refuses_row1_and_is_silent_on_row11(tmp_path):
    first, second = _dirs(tmp_path)
    result, _ = ci_red_tests._hook(first, P + BODY, listing=ci_red_tests.LISTING)
    assert (result.returncode, ci_red_tests.RED in result.stderr) == (2, True)
    quiet, calls = ci_red_tests._hook(second, "echo 'oops", listing=ci_red_tests.LISTING)
    assert (quiet.returncode, quiet.stderr, calls) == (0, "", [])
