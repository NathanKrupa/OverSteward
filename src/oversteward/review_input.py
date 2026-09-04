# ABOUTME: Assembles the adversarial reviewer's inputs deterministically from the repo and gh.
# ABOUTME: The author agent runs this; it never writes the reviewer's prompt, so it cannot curate.

"""Deterministic assembly of the adversarial pre-PR reviewer's inputs (OS#428).

The reviewer's whole value is that it never saw the author's rationale. If the
*author* composes what the reviewer reads, that guarantee degrades silently: a
summary of the diff instead of the diff, a test file omitted, a gaudi report
never run. None of those leave a trace, and all of them make the reviewer
cheaper and more agreeable — which is exactly the pressure the instrument
exists to resist. So the inputs are gathered by code, in a fixed order, from
fixed probes, and the author's only move is to run it.

Rule 5 (`pr-workflow.md` § False greens) is the spine of the design: a probe
that could not answer is never rendered as an empty answer. Each section
carries ``measured``; an unmeasured section prints ``COULD NOT LOOK``, is named
in the header, and turns the exit code into 2. "gaudi found nothing" and "gaudi
was not installed" must not reach the reviewer looking the same, or the
reviewer certifies a tree it never saw linted.

Stdlib only, deliberately: this module is read by a byte-copy family script and
must run under a bare interpreter in any repo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_COULD_NOT_LOOK = 2

#: Printed in place of a body a probe could not produce. Greppable on purpose:
#: a reviewer transcript containing it names an input nobody actually checked.
COULD_NOT_LOOK = "COULD NOT LOOK — this input was unavailable; do not treat it as clean."

#: Precedes a file the diff deleted, whose body is the base-branch version. The
#: deletion is the reviewable act, so the content must arrive labelled as gone
#: rather than looking like code that still exists.
DELETED_BY_THIS_DIFF = (
    "DELETED BY THIS DIFF — the body below is the base-branch version, i.e. the "
    "material this change removed from review. It no longer exists on the branch."
)

#: Names *why* an input is missing when the reason is that the deletion list
#: itself could not be read. "Missing because this diff removed it" and
#: "missing for a reason nobody can name" are different reviewable facts, and
#: only the first licenses showing the base-branch version.
DELETION_LIST_UNREADABLE = (
    "The list of paths this diff deleted could not be read, so a file absent "
    "from the working tree cannot be told from one the diff removed."
)

#: Section order is fixed so two runs over one tree render byte-identically.
TEST_FILES_SECTION = "changed-test-files"
GAUDI_SECTION = "gaudi-warn"
PREVIOUS_VERDICT_SECTION = "previous-verdict"
SECTION_ORDER = (
    "diff",
    "issue",
    TEST_FILES_SECTION,
    "repo-doctrine",
    GAUDI_SECTION,
    PREVIOUS_VERDICT_SECTION,
)

#: How many review rounds one change may take before the loop stops and the
#: remaining findings go to Nathan as issues. GS#2540's first PR ran eleven
#: rounds at roughly 110k reviewer tokens each; the cap is the mechanism the
#: brief's "do not enter a third round" never had.
MAX_ROUNDS = 3

_TEST_FILENAME_PREFIX = "test_"
_TEST_FILENAME_SUFFIX = "_test.py"
_TEST_DIR_NAMES = frozenset({"tests", "test"})
_FIXTURE_MODULE = "conftest.py"


class CouldNotLookError(RuntimeError):
    """A required input was unavailable, so no review input can honestly be built."""


class RoundCapError(RuntimeError):
    """The change has used its review rounds; the loop stops here unless overridden."""


@dataclass(frozen=True)
class Section:
    """One labelled input the reviewer reads, and whether anything actually measured it."""

    name: str
    body: str
    measured: bool
    #: Why the probe could not answer, when it could not. An unmeasured body
    #: is discarded at render time, so a reason held only in the body never
    #: reaches the reviewer — and "missing" without "why" is not actionable.
    reason: str = ""

    @property
    def rendered_body(self) -> str:
        """The body, or an explicit statement of absence — never a blank that reads as clean."""
        if not self.measured:
            return f"{COULD_NOT_LOOK}\n\n{self.reason}" if self.reason else COULD_NOT_LOOK
        return self.body if self.body.strip() else "(empty — the probe answered with nothing)"


@dataclass(frozen=True)
class AssembledInput:
    """Every input the reviewer gets, plus the provenance needed to reproduce it."""

    repo: str
    base: str
    sections: tuple[Section, ...]
    #: Which review round this input serves; round 1 reads the whole change.
    round_number: int = 1
    #: For a re-review, the commit the previous round reviewed: the diff section
    #: then carries only what changed since, and the header says so.
    since: str | None = None
    #: The operator's stated reason for reviewing past :data:`MAX_ROUNDS`.
    cap_override: str = ""

    @property
    def unmeasured(self) -> tuple[str, ...]:
        return tuple(section.name for section in self.sections if not section.measured)


class Collector(Protocol):
    """The outside world, as this module is allowed to touch it.

    Injected rather than called directly so a test can state what git, gh and
    gaudi answered — including "nothing", which is the branch that matters.
    """

    def diff(self, base: str) -> str | None: ...

    def changed_files(self, base: str) -> list[str] | None: ...

    def deleted_files(self, base: str) -> list[str] | None: ...

    def issue_body(self, repo: str, number: int) -> str | None: ...

    def file_text(self, relpath: str) -> str | None: ...

    def file_text_at_base(self, base: str, relpath: str) -> str | None: ...

    def claude_md(self) -> str | None: ...

    def gaudi_json(self, relpaths: list[str]) -> str | None: ...


def is_test_path(relpath: str) -> bool:
    """Whether a repo-relative path is test code the reviewer must read in full.

    A diff hunk of a test file is not enough to judge whether the test would
    have been red before the fix — the reviewer needs the whole module, plus
    the ``conftest.py`` carrying the fixtures it leans on.
    """
    path = Path(relpath)
    if path.suffix != ".py":
        return False
    if path.name == _FIXTURE_MODULE:
        return True
    if path.name.startswith(_TEST_FILENAME_PREFIX) or path.name.endswith(_TEST_FILENAME_SUFFIX):
        return True
    return any(part in _TEST_DIR_NAMES for part in path.parts[:-1])


def _diff_section(collector: Collector, base: str) -> Section:
    diff = collector.diff(base)
    if diff is None:
        raise CouldNotLookError(
            f"could not read the diff against {base!r} — check the base ref exists and is fetched"
        )
    if not diff.strip():
        raise CouldNotLookError(
            f"the diff against {base!r} is empty; there is nothing to review. "
            "Commit the work before assembling review input."
        )
    return Section(name="diff", body=diff, measured=True)


def _issue_section(collector: Collector, repo: str, issue: int | None, no_issue: bool) -> Section:
    if issue is None:
        if not no_issue:
            raise CouldNotLookError(
                "no issue number supplied. Pass --issue <n>, or --no-issue to record "
                "deliberately that this change closes none — an omission must be a "
                "decision, not a default."
            )
        return Section(
            name="issue",
            body="No issue: the author declared this change closes none (--no-issue).",
            measured=True,
        )
    body = collector.issue_body(repo, issue)
    if body is None:
        return Section(name="issue", body=COULD_NOT_LOOK, measured=False)
    return Section(name="issue", body=f"{repo}#{issue}\n\n{body}", measured=True)


def _previous_verdict_section(previous_verdict: str | None, round_number: int) -> Section:
    """What the last round found — a re-review must see it, a first review has none."""
    if round_number == 1:
        if previous_verdict is not None:
            raise CouldNotLookError(
                "round 1 takes no --previous-verdict; a first review reads the whole change"
            )
        return Section(
            name=PREVIOUS_VERDICT_SECTION,
            body="Round 1 — there is no previous verdict.",
            measured=True,
        )
    if previous_verdict is None or not previous_verdict.strip():
        raise CouldNotLookError(
            f"round {round_number} needs --previous-verdict <file>: a re-review that cannot "
            "see what the last round found re-derives it at full price."
        )
    return Section(name=PREVIOUS_VERDICT_SECTION, body=previous_verdict, measured=True)


def _check_round(round_number: int, since: str | None, cap_override: str) -> None:
    """The round bookkeeping the loop's economy rests on."""
    if round_number < 1:
        raise CouldNotLookError(f"round must be 1 or more, got {round_number}")
    if round_number == 1 and since:
        raise CouldNotLookError(
            "--since is for a re-review (round 2+); round 1 reads the whole change"
        )
    if round_number > MAX_ROUNDS and not cap_override.strip():
        raise RoundCapError(
            f"round {round_number} exceeds the {MAX_ROUNDS}-round cap. Stop: file the remaining "
            "findings as issues and hand the change to Nathan, or pass "
            "--override-cap '<reason>' to record why one more round is worth its cost."
        )


def _labelled(relpath: str, body: str, *, state: str = "") -> str:
    """One file under a delimiter the reviewer cannot mistake for the file's own text."""
    return f"----- {relpath}{state} -----\n{body}"


def _test_file_chunk(
    collector: Collector, base: str, relpath: str, deleted: frozenset[str] | None
) -> tuple[str, bool]:
    """One file's rendering, and whether anything actually produced its content."""
    text = collector.file_text(relpath)
    if text is not None:
        return _labelled(relpath, text), True
    # Not in the working tree. That is reviewable material when the diff
    # deleted it — a deleted test is the one that could have failed — and an
    # unmeasured input when nobody can say why it is missing. Under a `None`
    # deletion list nothing can be certified as deleted, so this falls through
    # to the unmeasured rendering; the *reason* is named once, by the section
    # (`_test_files_section`), because an unmeasured body is discarded at
    # render time and a second copy here would reach nobody.
    if deleted is not None and relpath in deleted:
        base_text = collector.file_text_at_base(base, relpath)
        if base_text is not None:
            body = f"{DELETED_BY_THIS_DIFF}\n\n{base_text}"
            return _labelled(relpath, body, state=" (deleted)"), True
    return _labelled(relpath, COULD_NOT_LOOK), False


def _test_files_section(
    collector: Collector, base: str, changed: Sequence[str], deleted: frozenset[str] | None
) -> Section:
    test_paths = [path for path in changed if is_test_path(path)]
    if not test_paths:
        return Section(
            name=TEST_FILES_SECTION,
            body=(
                "This diff changes no test files. A behaviour change with no test "
                "change is itself a finding worth stating."
            ),
            measured=True,
        )
    rendered = [_test_file_chunk(collector, base, path, deleted) for path in test_paths]
    measured = all(obtained for _, obtained in rendered)
    return Section(
        name=TEST_FILES_SECTION,
        body="\n\n".join(chunk for chunk, _ in rendered),
        measured=measured,
        # An unmeasured body is discarded at render time, so the reason has to
        # travel beside `measured` or the reviewer reads only that something
        # was missing, never that the deletion list was the blind spot.
        reason="" if measured or deleted is not None else DELETION_LIST_UNREADABLE,
    )


def _doctrine_section(collector: Collector) -> Section:
    text = collector.claude_md()
    if text is None:
        return Section(name="repo-doctrine", body=COULD_NOT_LOOK, measured=False)
    return Section(name="repo-doctrine", body=text, measured=True)


def _skipped_note(skipped: Sequence[str]) -> str:
    """Names the files gaudi did not read, so a narrower run is never silent."""
    if not skipped:
        return ""
    return (
        "\n\nSkipped by design — deleted by this diff, so there is no file to lint: "
        + ", ".join(skipped)
    )


#: Replaces the skipped-by-design note when the deletion list is unreadable.
#: Nothing may be skipped as deleted then, because nothing can be shown to be.
_DELETIONS_UNKNOWABLE_NOTE = (
    "\n\nNothing above was skipped as deleted, and nothing could be: "
    + DELETION_LIST_UNREADABLE
    + " Every changed Python file was submitted to gaudi, so a file this diff "
    "removed was read as absent rather than as clean."
)


def _gaudi_scope(
    python_files: Sequence[str], deleted: frozenset[str] | None
) -> tuple[list[str], str]:
    """The files gaudi reads, and the note accounting for the ones it does not."""
    if deleted is None:
        return list(python_files), _DELETIONS_UNKNOWABLE_NOTE
    return (
        [path for path in python_files if path not in deleted],
        _skipped_note([path for path in python_files if path in deleted]),
    )


def _gaudi_body(report: str, note: str) -> str:
    return (
        "gaudi check --severity warn --format json, per changed Python file that "
        "still exists.\n"
        "A warn finding is a QUESTION, not a defect — report one only where it "
        "hides a defect.\n\n" + report + note
    )


def _gaudi_section(
    collector: Collector, changed: Sequence[str], deleted: frozenset[str] | None
) -> Section:
    python_files = [path for path in changed if path.endswith(".py")]
    if not python_files:
        return Section(
            name=GAUDI_SECTION,
            body="This diff changes no Python files, so there is nothing for gaudi to read.",
            measured=True,
        )
    # A deleted file has nothing to lint, and naming it as skipped is a
    # measurement; letting it poison the whole probe into COULD NOT LOOK would
    # hide the findings on the files that do still exist. When the deletion
    # list could not be read, no file may be named as skipped-by-design — the
    # note says the skip reason is unknowable instead.
    present, note = _gaudi_scope(python_files, deleted)
    if not present:
        return Section(
            name=GAUDI_SECTION,
            body=(
                "Every Python file this diff touches was deleted by it, so gaudi has "
                "nothing to read. The deleted sources are reproduced above where they "
                "are test modules." + note
            ),
            measured=True,
        )
    report = collector.gaudi_json(present)
    if report is None:
        return Section(name=GAUDI_SECTION, body=COULD_NOT_LOOK, measured=False)
    return Section(name=GAUDI_SECTION, body=_gaudi_body(report, note), measured=True)


def assemble(
    collector: Collector,
    *,
    repo: str,
    base: str,
    issue: int | None,
    no_issue: bool = False,
    since: str | None = None,
    round_number: int = 1,
    previous_verdict: str | None = None,
    cap_override: str = "",
) -> AssembledInput:
    """Gather every reviewer input in a fixed order from a fixed set of probes.

    A re-review (``round_number`` 2+) may name ``since``, the commit the last
    round reviewed: the diff section then carries only the fix commits, while
    the changed-test-files list still spans the whole branch — a reviewer
    mutates whole test modules, not hunks. The previous verdict rides along so
    the round verifies fixes instead of re-deriving findings.
    """
    _check_round(round_number, since, cap_override)
    diff = _diff_section(collector, since or base)
    changed = collector.changed_files(base)
    if changed is None:
        raise CouldNotLookError(f"could not list the files changed against {base!r}")
    changed = sorted(set(changed))
    # None means the deletion list itself could not be read, which is not
    # "nothing was deleted". Under None no missing file can be certified as
    # deleted, so the base version is withheld and both sections name
    # DELETION_LIST_UNREADABLE as the blind spot — pinned by
    # TestAnUnreadableDeletionListNamesItselfRatherThanFoldingAway, because an
    # unenforced comment is the distinction rotting quietly (OS#442).
    reported_deletions = collector.deleted_files(base)
    deleted = None if reported_deletions is None else frozenset(reported_deletions)
    sections = (
        diff,
        _issue_section(collector, repo, issue, no_issue),
        _test_files_section(collector, base, changed, deleted),
        _doctrine_section(collector),
        _gaudi_section(collector, changed, deleted),
        _previous_verdict_section(previous_verdict, round_number),
    )
    return AssembledInput(
        repo=repo,
        base=base,
        sections=sections,
        round_number=round_number,
        since=since,
        cap_override=cap_override,
    )


def exit_code_for(assembled: AssembledInput) -> int:
    """0 when every input was measured, 2 when any could only be guessed at."""
    return EXIT_COULD_NOT_LOOK if assembled.unmeasured else EXIT_OK


def render(assembled: AssembledInput) -> str:
    """The reviewer's whole prompt payload, deterministic and self-describing.

    No timestamp, no host, no ordering that depends on how the probes answered
    — two runs over one tree must produce identical bytes, so a diff between
    two assemblies is a diff in the tree and never in the assembler.
    """
    unmeasured = assembled.unmeasured
    header = [
        "# Review input (assembled deterministically — do not edit)",
        "",
        f"repo: {assembled.repo}",
        f"base: {assembled.base}",
        f"round: {assembled.round_number} of {MAX_ROUNDS}",
        (
            f"since: {assembled.since} — the diff below is only what changed since the "
            "last round; the test files are whole"
            if assembled.since
            else "since: (none — the diff below is the whole change from base)"
        ),
        f"sections: {', '.join(SECTION_ORDER)}",
    ]
    if assembled.cap_override:
        header.append(f"CAP OVERRIDDEN: {assembled.cap_override}")
    if unmeasured:
        header.append(f"UNMEASURED INPUTS: {', '.join(unmeasured)}")
        header.append(
            "At least one input could not be gathered. Say so in the verdict block; "
            "do not review as if it were clean."
        )
    else:
        header.append("Every input above was measured.")
    parts = ["\n".join(header)]
    for section in assembled.sections:
        parts.append(
            f"<!-- review-input:{section.name} -->\n## {section.name}\n\n{section.rendered_body}"
        )
    return "\n\n".join(parts) + "\n"
