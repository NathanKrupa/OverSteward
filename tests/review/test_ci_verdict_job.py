# ABOUTME: Pins the CI wiring of the verdict gate — the job exists, and a body edit re-runs it.
# ABOUTME: CI cannot test its own triggers, so a missing `edited` type fails silently and forever.

from __future__ import annotations

import operator
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from oversteward.review_verdict import (
    EXIT_COULD_NOT_LOOK,
    EXIT_NOT_APPLICABLE,
    EXIT_OK,
    EXIT_VIOLATIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JOB = "reviewer-verdict"
GATE_PATH = "scripts/lint/require_review_verdict.py"


@pytest.fixture(scope="module")
def workflow() -> dict:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 reads a bare `on:` key as the boolean True; PyYAML follows it.
    parsed["on"] = parsed.get("on", parsed.get(True))
    return parsed


@pytest.fixture(scope="module")
def verdict_job(workflow: dict) -> dict:
    assert JOB in workflow["jobs"], f"no `{JOB}` job in {WORKFLOW.name}"
    return workflow["jobs"][JOB]


@pytest.fixture(scope="module")
def gate_step(verdict_job: dict) -> dict:
    """The one step in the job that runs the gate."""
    steps = [s for s in verdict_job["steps"] if GATE_PATH in s.get("run", "")]
    assert len(steps) == 1, (
        f"expected exactly one step running the gate, got {len(steps)}"
    )
    return steps[0]


def test_the_job_runs_the_gate_against_this_pull_request(verdict_job: dict) -> None:
    commands = "\n".join(step.get("run", "") for step in verdict_job["steps"])
    assert GATE_PATH in commands
    assert "--pr" in commands


def test_the_job_never_fires_on_a_push(verdict_job: dict) -> None:
    """A push to master has no PR body; judging one would be judging nothing."""
    assert "github.event_name == 'pull_request'" in verdict_job["if"]


# ---------------------------------------------------------------------------
# The `if:` expressions, evaluated rather than grepped (OS#444).
#
# `assert "edited" in job["if"]` is satisfied by the *opposite* of the rule it
# claims to enforce: inverting `!=` to `==` keeps the substring and flips the
# behaviour. So the subset of the expression language these conditions use is
# evaluated against a synthetic event, and the answer is asserted.
# ---------------------------------------------------------------------------

#: The two events that matter here: a body edit (which must not re-run the
#: suite) and a code push (which must).
EDITED = {"github.event.action": "edited", "github.event_name": "pull_request"}
SYNCHRONIZE = {
    "github.event.action": "synchronize",
    "github.event_name": "pull_request",
}


def _operand(token: str, context: dict[str, str]) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] == "'":
        return token[1:-1]
    if token in context:
        return context[token]
    raise AssertionError(
        f"unsupported operand {token!r} in a workflow `if:` — extend the "
        "evaluator rather than letting an unread condition pass."
    )


def _comparison(expression: str, context: dict[str, str]) -> bool:
    for symbol, compare in (("==", operator.eq), ("!=", operator.ne)):
        if symbol in expression:
            left, right = expression.split(symbol, 1)
            return compare(_operand(left, context), _operand(right, context))
    raise AssertionError(f"unsupported `if:` expression {expression!r}")


def evaluate(expression: str, context: dict[str, str]) -> bool:
    """The `==` / `!=` / `&&` / `||` subset of a GitHub `if:` expression.

    Anything outside the subset — parentheses, `!`, a function call, an
    unknown context key — raises rather than returning a value, so a condition
    this evaluator cannot read fails the test that calls it instead of quietly
    reading as satisfied.
    """
    expression = expression.strip()
    if "||" in expression:
        return any(evaluate(part, context) for part in expression.split("||"))
    if "&&" in expression:
        return all(evaluate(part, context) for part in expression.split("&&"))
    return _comparison(expression, context)


class TestTheIfEvaluator:
    """The evaluator is the instrument; an evaluator stuck on one answer would
    make every assertion below vacuous, so it is measured first."""

    def test_it_reads_an_inequality_both_ways(self) -> None:
        condition = "github.event.action != 'edited'"
        assert evaluate(condition, EDITED) is False
        assert evaluate(condition, SYNCHRONIZE) is True

    def test_it_reads_an_equality_both_ways(self) -> None:
        condition = "github.event.action == 'edited'"
        assert evaluate(condition, EDITED) is True
        assert evaluate(condition, SYNCHRONIZE) is False

    def test_it_reads_conjunction_and_disjunction(self) -> None:
        both = "github.event_name == 'pull_request' && github.event.action != 'edited'"
        assert evaluate(both, EDITED) is False
        assert evaluate(both, SYNCHRONIZE) is True
        either = "github.event.action == 'edited' || github.event_name == 'push'"
        assert evaluate(either, EDITED) is True

    def test_it_refuses_a_condition_it_cannot_read(self) -> None:
        with pytest.raises(AssertionError):
            evaluate("success()", EDITED)


def test_a_body_edit_re_runs_the_gate(workflow: dict) -> None:
    """The verdict is pasted in after opening. Without `edited` the check stays
    red however good the verdict is, and a check that cannot go green is one the
    estate learns to ignore."""
    assert "edited" in workflow["on"]["pull_request"]["types"]
    assert evaluate(workflow["jobs"][JOB]["if"], EDITED) is True


def test_a_body_edit_does_not_re_run_the_whole_suite(workflow: dict) -> None:
    """`edited` fires on every body keystroke-save; only the cheap job wants it."""
    for name, job in workflow["jobs"].items():
        if name == JOB:
            continue
        condition = job.get("if")
        assert condition, f"job `{name}` has no `if:` and re-runs on a body edit"
        assert evaluate(condition, EDITED) is False, (
            f"job `{name}` re-runs on a body edit"
        )
        assert evaluate(condition, SYNCHRONIZE) is True, (
            f"job `{name}` no longer runs on a code push"
        )


# ---------------------------------------------------------------------------
# The step's exit-code mapping, executed (OS#444).
#
# The mapping IS the deliverable of OS#437 — exit 3 must report green and
# exit 2 must report red — and it lived in a shell `case` no test ran. Three
# one-line edits to it each survived the whole suite. So the job's own `run:`
# block is pulled out of the YAML and executed against a stub gate, once per
# exit code the gate can produce.
# ---------------------------------------------------------------------------

#: gate exit code → the exit code the CI step must report for it.
#: 0 and 3 are green (judged clean / predates the gate); 1 and 2 are red
#: (a bad verdict / could not look, which must never soften into a pass).
STEP_EXIT_FOR_GATE_EXIT = {0: 0, 1: 1, 2: 2, 3: 0}


@pytest.fixture
def bash() -> str:
    """The shell these tests execute the job's `run:` block with.

    Requested by every test that spawns one, and by no other, so a machine
    without bash skips exactly those and still runs the table assertions. A
    skip that swallowed a real failure would be worse than the gap it covers,
    which is why this resolves the interpreter rather than merely testing for
    it: the tests below run the shell this fixture found.
    """
    found = shutil.which("bash")
    if found is None:
        pytest.skip("no bash on PATH — this test executes the job's own run: block")
    return found


def _shell_argv(step: dict, script: Path, bash: str) -> list[str]:
    """The runner's own interpreter for this step's `run:` block.

    The distinction is load-bearing rather than pedantic: the default shell is
    `bash -e {0}`, with no `pipefail`, so `gate | tail` there reports tail's
    status and a failing gate reads as a pass. An explicit `shell: bash` adds
    `-o pipefail` and would not. Emulating the wrong one would test a mapping
    the runner never executes.
    """
    shell = step.get("shell")
    if shell is None:
        return [bash, "--noprofile", "--norc", "-e", str(script)]
    assert shell == "bash", f"unhandled `shell: {shell}` — extend this emulation"
    return [bash, "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)]


def _stub_gate(root: Path, exit_code: int) -> None:
    """A `require_review_verdict.py` that prints and exits as asked."""
    gate = root / GATE_PATH
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(
        "import sys\n"
        f'sys.stdout.write("stub gate spoke, rc={exit_code}\\n")\n'
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )


def _run_step(
    step: dict, tmp_path: Path, gate_exit: int, bash: str
) -> subprocess.CompletedProcess:
    """Execute the job's shell in a sandbox whose gate exits ``gate_exit``.

    Everything the block writes — `verdict.log`, the step summary — lands under
    ``tmp_path``; the working tree is never touched.
    """
    _stub_gate(tmp_path, gate_exit)
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    summary = tmp_path / "step-summary.md"
    summary.touch()
    env = {
        **os.environ,
        "GH_TOKEN": "stub-token",
        "PR_NUMBER": "1",
        "PR_REPO": "NathanKrupa/OverSteward",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    return subprocess.run(
        _shell_argv(step, script, bash),
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestTheStepsExitCodeMapping:
    """Runs the job's `run:` block for every code the gate can return."""

    @pytest.mark.parametrize(
        ("gate_exit", "step_exit"), sorted(STEP_EXIT_FOR_GATE_EXIT.items())
    )
    def test_the_step_reports(
        self,
        gate_step: dict,
        tmp_path: Path,
        bash: str,
        gate_exit: int,
        step_exit: int,
    ) -> None:
        result = _run_step(gate_step, tmp_path, gate_exit, bash)
        assert result.returncode == step_exit, (
            f"gate exited {gate_exit}; the CI step must report {step_exit}, "
            f"reported {result.returncode}\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_red_and_green_are_both_reachable(self) -> None:
        """A mapping that answered one way for everything would satisfy every
        assertion above while gating nothing."""
        values = set(STEP_EXIT_FOR_GATE_EXIT.values())
        assert 0 in values and values - {0}

    def test_could_not_look_is_red_whatever_the_table_says(
        self, gate_step: dict, tmp_path: Path, bash: str
    ) -> None:
        """OS#437's load-bearing arm, asserted independently of the table.

        Exit 2 means the gate could not read the body at all — the API was
        unreachable, nothing was judged. Reporting that green would certify
        every PR a network blip touches, which is precisely the bite the
        four-valued exit contract exists to prevent.

        The parametrized case above pins this through STEP_EXIT_FOR_GATE_EXIT,
        and a table is not a guard when one commit can edit the table and the
        workflow arm together — `test_red_and_green_are_both_reachable` is
        satisfied by the `1 -> 1` entry alone and would not notice. So the
        property is asserted here against the executed step, reading nothing
        from the table.
        """
        result = _run_step(gate_step, tmp_path, EXIT_COULD_NOT_LOOK, bash)
        assert result.returncode != 0, (
            "the gate exited 2 (could not look) and the CI step reported "
            f"{result.returncode} — a green. A gate that could not look must "
            "never print or exit what a clean run does (OS#437).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_the_table_keeps_could_not_look_red(self) -> None:
        """The same property, pinned in the table — so the paired edit reddens
        both halves rather than sliding through on a consistent rename."""
        assert STEP_EXIT_FOR_GATE_EXIT[EXIT_COULD_NOT_LOOK] != 0, (
            "exit 2 is 'could not look', and it must map to a red step. A green "
            "there certifies every PR an unreachable API touches (OS#437)."
        )

    def test_the_gate_actually_ran(
        self, gate_step: dict, tmp_path: Path, bash: str
    ) -> None:
        """Guards the parametrized cases against passing on a gate that was
        never invoked — a `case` arm matching a stale `rc` would look identical."""
        result = _run_step(gate_step, tmp_path, 0, bash)
        assert "stub gate spoke, rc=0" in result.stdout

    def test_the_gates_words_reach_the_step_summary(
        self, gate_step: dict, tmp_path: Path, bash: str
    ) -> None:
        """The summary is where a human reads why a red is red."""
        _run_step(gate_step, tmp_path, 1, bash)
        summary = (tmp_path / "step-summary.md").read_text(encoding="utf-8")
        assert "stub gate spoke, rc=1" in summary


def test_the_mapping_covers_every_code_the_gate_can_return() -> None:
    """A code the gate returns but the job never maps falls to `*)`, which is
    correct only by accident. Assert the two sets are the same set.

    Spawns no shell — it compares two Python objects — so it carries no skip.
    """
    assert set(STEP_EXIT_FOR_GATE_EXIT) == {
        EXIT_OK,
        EXIT_VIOLATIONS,
        EXIT_COULD_NOT_LOOK,
        EXIT_NOT_APPLICABLE,
    }
