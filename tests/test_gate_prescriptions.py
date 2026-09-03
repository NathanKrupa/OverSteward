# ABOUTME: Guards every card and skill against prescribing a warn-tier gaudi gate.
# ABOUTME: The warn tier is not gated by policy (churn), and no shipped text may say it cannot be.

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from oversteward.gaudi_binary import gaudi_binary

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

# The estate gates on the error tier and nothing softer. Under gaudi 0.3.0
# `--exit-code` gates at whatever `--severity` selects, so a warn-tier gate does
# work — and is still forbidden, because Nathan's 2026-08-31 audit put the warn
# tier at roughly half churn and a fifth harm, so enforcing it would spend the
# ratchet on noise. The warn report is reviewer input, delivered by
# scripts/review/assemble_review_input.py; it is a question for the reviewer,
# never a defect to gate on. (The prohibition is OS#445's; the reason it gives
# changed with 0.3.0 — see OS#461.)
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
        + "\nThe estate gates on the error tier by policy: the warn tier is too noisy "
        "to enforce, not too weak to enforce. Gate on `--severity error --exit-code`; "
        "the warn report reaches the adversarial reviewer through "
        "scripts/review/assemble_review_input.py."
    )


# --------------------------------------------------------------------------
# The rationale has to stay true, not just the prohibition (OS#461).
#
# gaudi 0.2.0's `--exit-code` ignored the `--severity` threshold, so a warn-tier
# gate passed however many warnings were present, and the cards said so. 0.3.0
# gates at the selected threshold, which falsified that sentence while leaving
# the prohibition correct for a different reason. A false safety claim is worse
# than no claim: it tells every agent that warn-tier enforcement is impossible,
# so nobody checks.
# --------------------------------------------------------------------------

UV_LOCK = REPO_ROOT / "uv.lock"

#: The release that moved `--exit-code` onto the `--severity` threshold. Its
#: `gaudi check --help`: "The gate is the threshold --severity selected, so
#: --severity warn --exit-code fails on a warning."
THRESHOLD_GATING_SINCE = (0, 3, 0)

#: Claims that gaudi's own behaviour has falsified. Deliberately narrow — this
#: forbids asserting the warn tier *cannot* gate, never the policy that it
#: *must not*.
FALSIFIED_WARN_TIER_CLAIM = re.compile(
    r"(?:acts|gates|fires|counts|acted|gated)\s+on\s+(?:the\s+)?errors?(?:\s+tier)?\s+alone"
    r"|error\s+tier\s+alone"
    r"|exits?\s+0\s+with\s+(?:the\s+)?(?:warnings|findings)",
    re.IGNORECASE,
)

FALSIFIED_EXEMPLARS = [
    # Verbatim from the card this guard was written against.
    "`--exit-code` acts on errors alone, so pairing it with a warn minimum "
    "severity exits 0 with the warnings merely reported",
    "`--exit-code` gates on the error tier alone, so this exits 0 with findings reported.",
    "gaudi check --exit-code counts the error tier alone",
]

PERMITTED_RATIONALE = [
    # The policy, stated without the falsified mechanism.
    "The estate gates on the error tier by policy: the warn tier is too noisy to enforce.",
    "`--severity warn --exit-code` does fail on a warning under 0.3.0, and is still forbidden.",
    "Gate on `--severity error --exit-code`.",
]


def _locked_gaudi_version() -> tuple[int, ...]:
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "gaudi-linter"]
    assert versions, "uv.lock does not resolve gaudi-linter at all"
    return tuple(int(part) for part in versions[0].split("."))


def _falsified_claims(text: str) -> list[str]:
    return [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if FALSIFIED_WARN_TIER_CLAIM.search(line)
    ]


@pytest.mark.parametrize("text", FALSIFIED_EXEMPLARS)
def test_the_guard_catches_a_falsified_warn_tier_claim(text: str) -> None:
    assert _falsified_claims(text), f"no longer catches: {text!r}"


@pytest.mark.parametrize("text", PERMITTED_RATIONALE)
def test_the_guard_leaves_the_policy_rationale_alone(text: str) -> None:
    assert not _falsified_claims(text), f"cries wolf on: {text!r}"


def test_the_lock_resolves_a_gaudi_that_gates_at_the_selected_threshold() -> None:
    """The premise of the guard below, asserted rather than assumed."""
    assert _locked_gaudi_version() >= THRESHOLD_GATING_SINCE, (
        "uv.lock resolves a gaudi older than 0.3.0, where `--exit-code` fired on "
        "the error tier alone — the claims forbidden below would be true again, "
        "and this guard must be revisited rather than deleted."
    )


@pytest.mark.parametrize(
    "path", _instruction_files(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_shipped_text_claims_the_warn_tier_cannot_gate(path: Path) -> None:
    findings = _falsified_claims(path.read_text(encoding="utf-8"))
    assert not findings, (
        f"{path.relative_to(REPO_ROOT)} tells agents that `--exit-code` ignores the "
        f"warn tier:\n  " + "\n  ".join(findings) + "\n"
        f"uv.lock resolves gaudi "
        f"{'.'.join(str(n) for n in _locked_gaudi_version())}, which gates at whatever "
        "`--severity` selects. The warn tier is forbidden as policy (churn), not "
        "because it cannot fail — say that instead."
    )


def test_the_locked_gaudi_really_does_gate_on_a_warning(tmp_path: Path) -> None:
    """The behavioural half: the version claim above, checked against the binary.

    Skipped — never passed — when the interpreter's gaudi is not the one the
    lock resolves, which is the normal state of a session worktree sharing a
    deliberately un-synced venv. CI installs from the lock, so it runs there.
    """
    found = gaudi_binary()
    if found is None:
        pytest.skip(f"no gaudi beside {sys.executable}; nothing to check against")
    installed = subprocess.run(  # nosec B603
        [str(found), "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    locked = ".".join(str(n) for n in _locked_gaudi_version())
    if not installed.endswith(locked):
        pytest.skip(f"installed {installed!r} is not the locked {locked} — cannot verify")

    warn_only = tmp_path / "warn_only.py"
    body = "\n".join(f"    value_{n} = {n}" for n in range(60))
    warn_only.write_text(f"def long_function():\n{body}\n    return 0\n", encoding="utf-8")

    def check(severity: str) -> int:
        return subprocess.run(  # nosec B603
            [str(found), "check", str(warn_only), "--severity", severity, "--exit-code"],
            capture_output=True, text=True, check=False,
        ).returncode

    assert check("error") == 0, "the fixture is meant to carry warnings and no errors"
    assert check("warn") != 0, (
        f"gaudi {locked} exited 0 on a file with warnings at `--severity warn "
        "--exit-code` — the threshold-gating premise is wrong and the cards' "
        "rationale must be revisited"
    )


def test_this_modules_own_commentary_does_not_repeat_the_falsified_claim() -> None:
    """This file taught the falsehood too, in its ABOUTME and its rationale comment.

    Only comment lines are scanned, and deliberately so: the string literals in
    this module are the guard's negative fixtures and its assertion messages,
    which must be free to quote the forbidden sentence verbatim. The narrative
    an engineer reads is the comments, and that is what is pinned.
    """
    comments = "\n".join(
        line
        for line in Path(__file__).read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#")
    )
    findings = _falsified_claims(comments)
    assert not findings, "this guard's own commentary states what gaudi has falsified:\n  " + "\n  ".join(findings)
