# ABOUTME: Parses and judges the adversarial reviewer's verdict block in a PR body.
# ABOUTME: Missing, malformed and BLOCK are all red — only a well-formed PASS certifies anything.

"""The blocking verdict the adversarial reviewer writes into the PR body (OS#428).

The block is fenced with the info string ``reviewer-verdict`` rather than being
prose, for one reason: prose is satisfiable by writing prose. "The reviewer said
it looks fine" is a sentence an author can produce without a reviewer having
run, and a gate that accepts it is decoration. A fenced block with three
required keys and an internal-consistency rule is still forgeable, but it can no
longer be produced *by accident* or by a hurried summary — and forging it is a
recorded lie in the PR body rather than an omission nobody can see.

Consistency is checked because a fabricated block tends to be inconsistent:
``PASS`` with two findings, or ``BLOCK`` with none. Those are refused as
malformed rather than read charitably.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_COULD_NOT_LOOK = 2
EXIT_NOT_APPLICABLE = 3

#: The instant the CI job that runs this gate was opened as a pull request —
#: PR#443's own ``created_at`` (OS#437). A PR opened at or before it cannot have
#: carried a verdict for a gate that did not yet exist, so the gate does not
#: govern it.
#:
#: This is a cutoff, not a bypass, and the difference is the point. A bypass is
#: per-PR and available to whoever wants it — a label, a magic phrase, a skip
#: flag — so the cheapest response to a red gate is always to use it. A cutoff
#: is one fixed instant that nobody can move without this file's history
#: recording it, it grants nothing to any PR opened from now on, and it shrinks
#: to nothing as the affected PRs merge. It is refused a future value by
#: ``tests/review/test_verdict_gate_scope.py``, because a cutoff ahead of `now`
#: exempts every PR that will ever exist.
GATE_LIVE_FROM = "2026-09-02T02:40:24+00:00"

BLOCK = "BLOCK"
PASS = "PASS"
PASS_WITH_FINDINGS = "PASS-WITH-FINDINGS"

#: Ordered worst-first; the reviewer picks exactly one.
VERDICTS = (BLOCK, PASS_WITH_FINDINGS, PASS)

FENCE = "reviewer-verdict"
UNKNOWN = "unknown"

_BLOCK_RE = re.compile(rf"^```{FENCE}\s*$(?P<body>.*?)^```\s*$", re.MULTILINE | re.DOTALL)
_KEY_RE = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>.*?)\s*$", re.MULTILINE)

_REQUIRED_KEYS = ("verdict", "findings", "tokens")


class MissingVerdictError(RuntimeError):
    """The PR body carries no reviewer verdict block at all."""


class MalformedVerdictError(RuntimeError):
    """A verdict block exists but does not say something a gate can act on."""


@dataclass(frozen=True)
class Verdict:
    """One reviewer verdict, as read from a PR body."""

    verdict: str
    findings: int
    tokens: int | None

    @property
    def blocking(self) -> bool:
        return self.verdict == BLOCK


def _check_consistency(verdict: str, findings: int) -> None:
    """Refuse a block whose own two halves disagree — the fabrication signature."""
    if verdict == PASS and findings != 0:
        raise MalformedVerdictError(
            f"verdict is {PASS} but findings is {findings}. A PASS reports no findings; "
            f"use {PASS_WITH_FINDINGS}."
        )
    if verdict == PASS_WITH_FINDINGS and findings == 0:
        raise MalformedVerdictError(
            f"verdict is {PASS_WITH_FINDINGS} but findings is 0. Use {PASS}."
        )
    if verdict == BLOCK and findings == 0:
        raise MalformedVerdictError(
            f"verdict is {BLOCK} but findings is 0. A block must name what blocks it."
        )


def parse_verdict(body: str) -> Verdict:
    """The verdict block in ``body``, or an exception naming what is wrong with it."""
    matches = _BLOCK_RE.findall(body)
    if not matches:
        raise MissingVerdictError(
            f"no ```{FENCE} block in the PR body. Run the adversarial reviewer "
            "(shared/agents/adversarial-reviewer.md) and paste its verdict."
        )
    if len(matches) > 1:
        raise MalformedVerdictError(
            f"{len(matches)} ```{FENCE} blocks in the PR body. Exactly one verdict "
            "governs a PR; two mean an earlier verdict was left standing."
        )
    fields = {m.group("key"): m.group("value") for m in _KEY_RE.finditer(matches[0])}
    missing = [key for key in _REQUIRED_KEYS if key not in fields]
    if missing:
        raise MalformedVerdictError(f"verdict block is missing: {', '.join(missing)}")

    verdict = fields["verdict"]
    if verdict not in VERDICTS:
        raise MalformedVerdictError(
            f"unknown verdict {verdict!r}; expected one of {', '.join(VERDICTS)}"
        )
    try:
        findings = int(fields["findings"])
    except ValueError as exc:
        raise MalformedVerdictError(
            f"findings must be a whole number, got {fields['findings']!r}"
        ) from exc
    if findings < 0:
        raise MalformedVerdictError(f"findings cannot be negative, got {findings}")

    raw_tokens = fields["tokens"]
    if raw_tokens == UNKNOWN:
        tokens = None
    else:
        try:
            tokens = int(raw_tokens)
        except ValueError as exc:
            raise MalformedVerdictError(
                f"tokens must be a whole number or {UNKNOWN!r}, got {raw_tokens!r}"
            ) from exc

    _check_consistency(verdict, findings)
    return Verdict(verdict=verdict, findings=findings, tokens=tokens)


def governs(created_at: str | None) -> bool:
    """Whether this gate governs a PR opened at ``created_at`` (ISO 8601).

    Fails closed. The exemption is granted only on a timestamp that could
    actually be read *and* that is at or before :data:`GATE_LIVE_FROM`; an
    absent, empty or unparseable one is governed, so "I could not tell how old
    it is" can never widen into a bypass.
    """
    if not created_at:
        return True
    try:
        opened = datetime.fromisoformat(created_at)
    except ValueError:
        return True
    return opened > datetime.fromisoformat(GATE_LIVE_FROM)


def judge(body: str | None) -> tuple[int, str]:
    """An exit code and a human sentence for one PR body.

    ``None`` is "the body could not be read", which exits 2 — distinct from
    both a pass and a failure, because a gate that could not look must not
    print what a clean run prints.
    """
    if body is None:
        return EXIT_COULD_NOT_LOOK, "could not read the PR body"
    try:
        parsed = parse_verdict(body)
    except MissingVerdictError as exc:
        return EXIT_VIOLATIONS, str(exc)
    except MalformedVerdictError as exc:
        return EXIT_VIOLATIONS, str(exc)
    if parsed.blocking:
        return EXIT_VIOLATIONS, (
            f"reviewer returned {BLOCK} with {parsed.findings} finding(s). "
            "Fix them and re-review; a second BLOCK escalates to Nathan via needs-input."
        )
    return EXIT_OK, parsed.verdict


def render_template(
    verdict: str | None, *, findings: int | None, tokens: int | None
) -> str:
    """The verdict block, for the agent card and for tests.

    Called with ``None`` it renders the unfilled placeholder form, which the
    parser must reject — a copy-pasted template certifies nothing.
    """
    return (
        "## Adversarial review\n\n"
        f"```{FENCE}\n"
        f"verdict: {verdict if verdict is not None else '<BLOCK|PASS-WITH-FINDINGS|PASS>'}\n"
        f"findings: {findings if findings is not None else '<N>'}\n"
        f"tokens: {tokens if tokens is not None else '<N or unknown>'}\n"
        "```\n"
    )
