# ABOUTME: Findings and the three-way outcome every estate-map check returns: clean, findings, could not look.
# ABOUTME: "Could not look" outranks findings, so a check that read nothing can never exit like one that passed.

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_COULD_NOT_LOOK = 2


@dataclass(frozen=True)
class Finding:
    check: str
    subject: str
    message: str

    def __str__(self) -> str:
        return f"{self.check}: {self.subject} — {self.message}"


@dataclass(frozen=True)
class Outcome:
    findings: tuple[Finding, ...] = ()
    could_not_look: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        if self.could_not_look:
            return EXIT_COULD_NOT_LOOK
        return EXIT_FINDINGS if self.findings else EXIT_CLEAN


def combine(outcomes: Iterable[Outcome]) -> Outcome:
    findings: list[Finding] = []
    blind: list[str] = []
    notes: list[str] = []
    for outcome in outcomes:
        findings.extend(outcome.findings)
        blind.extend(outcome.could_not_look)
        notes.extend(outcome.notes)
    return Outcome(tuple(findings), tuple(blind), tuple(notes))
