# ABOUTME: Guards every card and skill against prescribing a gaudi gate that cannot fail.
# ABOUTME: `--exit-code` gates on errors alone, so a warn-severity gate exits 0 with warnings present.

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every directory whose markdown tells an agent which command to run. A card
#: and its deployed byte-copy are both scanned: a prohibition that only reaches
#: the canonical source leaves the consumed copy still prescribing the shape.
INSTRUCTION_DIRS = (
    REPO_ROOT / "shared" / "agents",
    REPO_ROOT / "shared" / "skills",
    REPO_ROOT / ".claude" / "agents",
    REPO_ROOT / ".claude" / "skills",
)

MARKDOWN_GLOB = "*.md"

# `gaudi check --exit-code` counts the error tier alone, so pairing it with a
# warn (or info) minimum severity produces a gate that exits 0 while reporting
# findings — inert by construction, not by accident (OS#445). The warn report is
# reviewer input, delivered by scripts/review/assemble_review_input.py; it is a
# question for the reviewer, never a defect to gate on.
_SOFT_SEVERITY = r"(?:--severity[=\s]+(?:warn|info)\b|-s[=\s]+(?:warn|info)\b)"
_EXIT_CODE = r"--exit-code\b"

SOFT_SEVERITY_GATE = re.compile(rf"{_SOFT_SEVERITY}.*{_EXIT_CODE}|{_EXIT_CODE}.*{_SOFT_SEVERITY}")

def _logical_commands(text: str) -> list[tuple[int, str]]:
    """Each logical line, joined across shell continuations, with its first line number.

    A guard that reads rendered lines is defeated by a line break: the card
    hard-wraps, and `--severity warn \\` / `--exit-code` on two lines is still
    one command.
    """
    commands: list[tuple[int, str]] = []
    pending: list[str] = []
    start = 1
    for number, line in enumerate(text.splitlines(), start=1):
        if not pending:
            start = number
        if line.endswith("\\"):
            pending.append(line[:-1])
            continue
        commands.append((start, " ".join(part.strip() for part in [*pending, line])))
        pending = []
    if pending:
        commands.append((start, " ".join(part.strip() for part in pending)))
    return commands


def _soft_gate_findings(text: str) -> list[str]:
    return [
        f"line {number}: {line.strip()}"
        for number, line in _logical_commands(text)
        if SOFT_SEVERITY_GATE.search(line)
    ]


#: The fixture that makes the guard fail. A pattern nobody has watched catch
#: anything is a pattern that may catch nothing (`pr-workflow.md` § False
#: greens: a new check ships with the fixture that makes it fail).
FORBIDDEN_EXEMPLARS = [
    # Verbatim from the wording this guard was written against (OS#445).
    ".venv/bin/gaudi check src/ --severity warn --exit-code",
    # Flag order carries no meaning to the CLI, so it carries none here either.
    ".venv/bin/gaudi check src/ --exit-code --severity warn",
    ".venv/bin/gaudi check src/ --severity=warn --exit-code",
    ".venv/bin/gaudi check src/ -s warn --exit-code",
    ".venv/bin/gaudi check src/ --severity info --exit-code",
    # Wrapped for the card's hard-wrap width — still one logical command.
    ".venv/bin/gaudi check src/ --severity warn \\\n    --exit-code",
]

#: Prose that must stay legal, or the guard cries wolf and gets ignored.
PERMITTED_PROSE = [
    # The gate: the error tier is what `--exit-code` actually acts on.
    ".venv/bin/gaudi check src/ --severity error --exit-code",
    # The reviewer-input path, which reports rather than gates.
    "| `gaudi-warn` | `gaudi check --severity warn --format json` on the changed files |",
    ".venv/bin/gaudi check src/ --severity warn --format text",
    # Explicitly asking for no exit code is a report, not a gate.
    ".venv/bin/gaudi check src/ --severity warn --no-exit-code",
]


def _instruction_files() -> list[Path]:
    return sorted(
        path for directory in INSTRUCTION_DIRS for path in directory.rglob(MARKDOWN_GLOB)
    )


def test_there_are_instruction_files_to_scan() -> None:
    """A parametrized guard over an empty glob passes vacuously."""
    assert _instruction_files(), f"no markdown found under {INSTRUCTION_DIRS}"


@pytest.mark.parametrize("text", FORBIDDEN_EXEMPLARS)
def test_the_guard_catches_a_soft_severity_exit_code_gate(text: str) -> None:
    assert _soft_gate_findings(text), f"no longer catches: {text!r}"


@pytest.mark.parametrize("text", PERMITTED_PROSE)
def test_the_guard_leaves_reporting_invocations_alone(text: str) -> None:
    assert not _soft_gate_findings(text), f"cries wolf on: {text!r}"


@pytest.mark.parametrize(
    "path",
    _instruction_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_no_card_or_skill_prescribes_a_gate_that_cannot_fail(path: Path) -> None:
    findings = _soft_gate_findings(path.read_text(encoding="utf-8"))
    assert not findings, (
        f"{path.relative_to(REPO_ROOT)} prescribes a gaudi gate that cannot fail:\n  "
        + "\n  ".join(findings)
        + "\n`--exit-code` gates on the error tier alone, so this exits 0 with findings "
        "reported. Gate on `--severity error --exit-code`; the warn report reaches the "
        "adversarial reviewer through scripts/review/assemble_review_input.py."
    )
