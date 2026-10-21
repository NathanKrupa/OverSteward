# ABOUTME: Deterministic backfill classifier — proposes tribe / agent-finding for an open issue.
# ABOUTME: Labels, body markers agents write, title shapes and the repo only; never an LLM call.

"""Propose intake labels for an issue filed before OS#613 existed.

The two labels are independent: ``agent-finding`` is about who filed an issue,
``tribe`` about who would notice it, so one issue can earn both. Every proposed
label carries the rule that produced it, because Nathan eyeballs a sample of
the proposals before anything is applied.

The rules are deliberately conservative. A wrong ``tribe`` pushes ordinary work
ahead of the pantry user's, and a wrong ``agent-finding`` hides one of Nathan's
own asks among agent noise; ``unclassified`` costs nothing but a later look.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from oversteward.intake.labels import AGENT_FINDING, TRIBE
from oversteward.intake.models import IntakeIssue

UNCLASSIFIED = "unclassified"

# --- agent-finding ---------------------------------------------------------

#: Labels only an agent pipeline applies: kaizen clusters, and the Telegraph
#: relay's ``from:<repo>`` provenance tag.
_AGENT_LABELS = frozenset({AGENT_FINDING, "kaizen"})
_PROVENANCE_PREFIX = "from:"

#: Body text an agent writes and Nathan does not.
_STRONG_BODY = (
    ("Telegraph relay footer", re.compile(r"Filed by the [\w-]+ agent")),
    ("Claude Code attribution", re.compile(r"Generated with \[Claude Code\]")),
    (
        "Sentry short id",
        re.compile(r"\b(?:AIGRANTHELPER|GRANTSPIDER|OVERSTEWARD|WPHELPER|FISCUS|PYTHON)-[0-9A-Z]{1,5}\b"),
    ),
    ("stage_health filing", re.compile(r"\bstage_health\b")),
)

#: How an agent describes work it came across while doing other work.
_WEAK_TEXT = (
    (
        "found during other work",
        re.compile(r"\b(?:found|surfaced|spotted|discovered|noticed)\s+(?:while|during|in)\b", re.I),
    ),
    (
        "review finding",
        re.compile(r"\b(?:adversarial[- ]review|reviewer(?:'s)?\s+(?:finding|round|verdict))", re.I),
    ),
    ("follow-up to earlier work", re.compile(r"\bfollow[- ]?up\s+(?:to|from)\s+(?:#|PR\b)", re.I)),
)

#: Phrases that say an issue records Nathan's own ask. They veto a weak marker,
#: never a strong one: an agent can quote Nathan, but does not sign as him.
_NATHAN_ORIGIN = re.compile(
    r"\bNathan(?:'s)?\s+(?:asked|asks|wants|wanted|requested|request|idea|ideas|suggested)\b", re.I
)

# --- tribe -----------------------------------------------------------------

#: Only these repositories hold work a pantry user of AI Grant Helper can see.
_AG = "aigranthelper"
_GS = "grantspider"

#: Labels that mark work no user sees, whatever else the issue says.
_INTERNAL_LABELS = frozenset(
    {
        "code-quality", "tech-debt", "documentation", "infrastructure", "security", "seo",
        "ops", "planning", "architecture", "stability", "gaudi",
    }
)

#: Title shapes of internal work: tests, CI, docs, staging, instrumentation.
_INTERNAL_TITLE = re.compile(
    r"\b(?:staging|smoke|playwright|telemetry|lighthouse|unverified|investigate|cron|backfill)\b"
    r"|^\s*(?:\[[^\]]*\]\s*)?(?:tests?|test_\w+|chore|ci|docs?|refactor|build|ops|perf|spike)\b"
    r"|\b(?:fix|chore|feat|perf|refactor)\((?:ci|tests?|ops|infra|deps|lint|gaudi)\)",
    re.I,
)

#: AI Grant Helper labels for work a user meets in the product.
_AG_USER_LABELS = frozenset(
    {
        "bug", "product", "design", "auth",
        "epic:mobile-excellence", "epic:grant-readiness", "epic:lifecycle",
    }
)

#: AI Grant Helper surfaces a user touches, matched in the title only — a body
#: mentions a draft or a deadline in passing far more often than it is about one.
_AG_USER_SURFACE = re.compile(
    r"\b(?:beta feedback|in-app feedback|food bank|pantr(?:y|ies)|on a phone|mobile|tap target|"
    r"contrast|checkout|pricing page|foundation page|funder page|draft|deadline|studio|workshop|"
    r"dashboard|kanban|onboarding|sign[- ]?up|log[- ]?in|magic[- ]link|email)",
    re.I,
)

#: GrantSpider data a user sees on an AI Grant Helper page.
_GS_AG_SURFACE = re.compile(
    r"\b(?:foundation page|funder page|AG page|AG search|public page|on AG\b|AG users?\b)", re.I
)
_GS_USER_REPORT = re.compile(r"\b(?:beta (?:corrections?|feedback)|user[- ]reported)", re.I)


@dataclass(frozen=True, slots=True)
class Proposal:
    labels: frozenset[str]
    reasons: tuple[str, ...]

    @property
    def klass(self) -> str:
        if self.labels == {TRIBE, AGENT_FINDING}:
            return f"{TRIBE}+{AGENT_FINDING}"
        if self.labels:
            return next(iter(self.labels))
        return UNCLASSIFIED


def _agent_finding(issue: IntakeIssue) -> tuple[bool, str | None]:
    for label in sorted(issue.labels & _AGENT_LABELS):
        return True, f"label {label}"
    for label in sorted(issue.labels):
        if label.startswith(_PROVENANCE_PREFIX):
            return True, f"label {label}"
    for name, pattern in _STRONG_BODY:
        if pattern.search(issue.body):
            return True, f"body: {name}"
    text = f"{issue.title}\n{issue.body}"
    for name, pattern in _WEAK_TEXT:
        if pattern.search(text):
            if _NATHAN_ORIGIN.search(text):
                return False, f"agent marker ({name}) vetoed: text records a Nathan ask"
            return True, f"text: {name}"
    return False, None


def _tribe(issue: IntakeIssue) -> tuple[bool, str | None]:
    if TRIBE in issue.labels:
        return True, "label tribe"
    if issue.repo not in (_AG, _GS):
        return False, None
    internal = sorted(issue.labels & _INTERNAL_LABELS)
    if internal:
        return False, f"internal label {internal[0]}"
    if _INTERNAL_TITLE.search(issue.title):
        return False, "internal title"
    if issue.repo == _AG:
        user_labels = sorted(issue.labels & _AG_USER_LABELS)
        if user_labels:
            return True, f"AG user-facing label {user_labels[0]}"
        surface = _AG_USER_SURFACE.search(issue.title)
        if surface:
            return True, f"AG user surface in title: {surface.group(0)!r}"
        return False, None
    surface = _GS_AG_SURFACE.search(issue.title) or _GS_USER_REPORT.search(issue.title)
    if surface:
        return True, f"GS title names what AG users see: {surface.group(0)!r}"
    if "bug" in issue.labels:
        surface = _GS_AG_SURFACE.search(issue.body)
        if surface:
            return True, f"GS bug whose body names the AG surface: {surface.group(0)!r}"
    return False, None


def classify(issue: IntakeIssue) -> Proposal:
    labels: set[str] = set()
    reasons: list[str] = []
    for label, rule in ((TRIBE, _tribe), (AGENT_FINDING, _agent_finding)):
        hit, reason = rule(issue)
        if hit:
            labels.add(label)
        if reason:
            reasons.append(reason)
    if not reasons:
        reasons.append("no rule matched")
    return Proposal(frozenset(labels), tuple(reasons))
