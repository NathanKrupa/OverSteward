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

#: Section order is fixed so two runs over one tree render byte-identically.
SECTION_ORDER = ("diff", "issue", "changed-test-files", "repo-doctrine", "gaudi-warn")

_TEST_FILENAME_PREFIX = "test_"
_TEST_FILENAME_SUFFIX = "_test.py"
_TEST_DIR_NAMES = frozenset({"tests", "test"})
_FIXTURE_MODULE = "conftest.py"


class CouldNotLookError(RuntimeError):
    """A required input was unavailable, so no review input can honestly be built."""


@dataclass(frozen=True)
class Section:
    """One labelled input the reviewer reads, and whether anything actually measured it."""

    name: str
    body: str
    measured: bool

    @property
    def rendered_body(self) -> str:
        """The body, or an explicit statement of absence — never a blank that reads as clean."""
        if not self.measured:
            return COULD_NOT_LOOK
        return self.body if self.body.strip() else "(empty — the probe answered with nothing)"


@dataclass(frozen=True)
class AssembledInput:
    """Every input the reviewer gets, plus the provenance needed to reproduce it."""

    repo: str
    base: str
    sections: tuple[Section, ...]

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

    def issue_body(self, repo: str, number: int) -> str | None: ...

    def file_text(self, relpath: str) -> str | None: ...

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


def _test_files_section(collector: Collector, changed: Sequence[str]) -> Section:
    test_paths = [path for path in changed if is_test_path(path)]
    if not test_paths:
        return Section(
            name="changed-test-files",
            body=(
                "This diff changes no test files. A behaviour change with no test "
                "change is itself a finding worth stating."
            ),
            measured=True,
        )
    chunks = []
    for relpath in test_paths:
        text = collector.file_text(relpath)
        rendered = text if text is not None else COULD_NOT_LOOK
        chunks.append(f"----- {relpath} -----\n{rendered}")
    unreadable = any(collector.file_text(p) is None for p in test_paths)
    return Section(
        name="changed-test-files",
        body="\n\n".join(chunks),
        measured=not unreadable,
    )


def _doctrine_section(collector: Collector) -> Section:
    text = collector.claude_md()
    if text is None:
        return Section(name="repo-doctrine", body=COULD_NOT_LOOK, measured=False)
    return Section(name="repo-doctrine", body=text, measured=True)


def _gaudi_section(collector: Collector, changed: Sequence[str]) -> Section:
    python_files = [path for path in changed if path.endswith(".py")]
    if not python_files:
        return Section(
            name="gaudi-warn",
            body="This diff changes no Python files, so there is nothing for gaudi to read.",
            measured=True,
        )
    report = collector.gaudi_json(list(python_files))
    if report is None:
        return Section(name="gaudi-warn", body=COULD_NOT_LOOK, measured=False)
    return Section(
        name="gaudi-warn",
        body=(
            "gaudi check --severity warn --format json, per changed Python file.\n"
            "A warn finding is a QUESTION, not a defect — report one only where it "
            "hides a defect.\n\n" + report
        ),
        measured=True,
    )


def assemble(
    collector: Collector,
    *,
    repo: str,
    base: str,
    issue: int | None,
    no_issue: bool = False,
) -> AssembledInput:
    """Gather every reviewer input in a fixed order from a fixed set of probes."""
    diff = _diff_section(collector, base)
    changed = collector.changed_files(base)
    if changed is None:
        raise CouldNotLookError(f"could not list the files changed against {base!r}")
    changed = sorted(set(changed))
    sections = (
        diff,
        _issue_section(collector, repo, issue, no_issue),
        _test_files_section(collector, changed),
        _doctrine_section(collector),
        _gaudi_section(collector, changed),
    )
    return AssembledInput(repo=repo, base=base, sections=sections)


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
        f"sections: {', '.join(SECTION_ORDER)}",
    ]
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
            f"<!-- review-input:{section.name} -->\n"
            f"## {section.name}\n\n{section.rendered_body}"
        )
    return "\n\n".join(parts) + "\n"
