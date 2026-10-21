# ABOUTME: Tests for the deterministic backfill classifier — one negative fixture per rule.
# ABOUTME: Each rule is pinned by an issue it must catch and a near-miss it must leave alone.

from __future__ import annotations

import pytest

from oversteward.intake.classify import classify

from .conftest import issue

# --- agent-finding: labels ------------------------------------------------


@pytest.mark.parametrize("label", ["kaizen", "agent-finding", "from:grantspider"])
def test_an_agent_label_marks_agent_finding(label):
    proposal = classify(issue(1, repo="oversteward", labels=(label,)))
    assert "agent-finding" in proposal.labels


def test_a_plain_label_does_not_mark_agent_finding():
    assert classify(issue(1, repo="oversteward", labels=("bug",))).labels == frozenset()


# --- agent-finding: strong body markers ------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Body.\n\n---\nFiled by the grantspider agent via The Telegraph. Origin: x",
        "Body.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)",
        "Sentry AIGRANTHELPER-2A fires on every save.",
        "PYTHON-9 in the grantspider project.",
        "RED row from the stage_health sweep.",
    ],
)
def test_a_strong_body_marker_marks_agent_finding(body):
    proposal = classify(issue(1, repo="oversteward", body=body))
    assert "agent-finding" in proposal.labels


def test_a_strong_marker_beats_a_nathan_origin_phrase():
    body = "Nathan asked for this.\n\n🤖 Generated with [Claude Code](https://claude.com)"
    assert "agent-finding" in classify(issue(1, repo="oversteward", body=body)).labels


@pytest.mark.parametrize(
    "body",
    [
        "Mentions Claude Code but carries no attribution line.",
        "Sentry Cron check-ins for the long drains.",
        "A Python-3 upgrade.",
        "stage health in prose, not the tool name",
    ],
)
def test_a_near_miss_body_is_not_a_strong_marker(body):
    assert classify(issue(1, repo="oversteward", body=body)).labels == frozenset()


# --- agent-finding: weak markers and the Nathan-origin veto ----------------


@pytest.mark.parametrize(
    "text",
    [
        "Found while working #12.",
        "Surfaced during the PR #40 pickup.",
        "Spotted in the gaudi baseline.",
        "Discovered while fixing the cache.",
        "Noticed during the deploy.",
        "Adversarial review finding 3 on PR #9.",
        "The reviewer's round 2 verdict named this.",
        "Follow-up to #2443.",
        "follow-up from PR #12",
    ],
)
def test_a_weak_marker_marks_agent_finding(text):
    assert "agent-finding" in classify(issue(1, repo="oversteward", body=text)).labels


def test_a_weak_marker_in_the_title_counts():
    proposal = classify(issue(1, repo="oversteward", title="Gaps (follow-up to #2443)"))
    assert "agent-finding" in proposal.labels


@pytest.mark.parametrize(
    "phrase",
    [
        "Nathan asked for this", "Nathan asks for this", "Nathan wants it", "Nathan wanted it",
        "Nathan requested it", "Nathan's request", "Nathan's idea", "Nathan's ideas",
        "Nathan suggested it",
    ],
)
def test_a_nathan_origin_phrase_vetoes_a_weak_marker(phrase):
    proposal = classify(issue(1, repo="oversteward", body=f"{phrase}. Found while testing."))
    assert "agent-finding" not in proposal.labels
    assert any("Nathan" in reason for reason in proposal.reasons)


@pytest.mark.parametrize(
    "text",
    [
        "We found the bug.",
        "A review of the copy.",
        "Follow up with the client.",
        "Nathan ruling 2026-10-21.",
    ],
)
def test_a_near_miss_weak_marker_is_left_alone(text):
    assert classify(issue(1, repo="oversteward", body=text)).labels == frozenset()


# --- tribe: repo scope -----------------------------------------------------


@pytest.mark.parametrize("repo", ["oversteward", "wphelper", "fiscus", "exchequer", "ai-assistants"])
def test_only_the_product_repos_propose_tribe(repo):
    # A title both the AG and the GS rules accept, so no product rule can rescue it.
    title = "Checkout shows the wrong foundation page"
    proposal = classify(issue(1, repo=repo, title=title, labels=("bug",)))
    assert "tribe" not in proposal.labels


def test_an_existing_tribe_label_is_kept_in_any_repo():
    assert "tribe" in classify(issue(1, repo="oversteward", labels=("tribe",))).labels


# --- tribe: aigranthelper --------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["bug", "product", "design", "auth", "epic:mobile-excellence", "epic:grant-readiness",
     "epic:lifecycle"],
)
def test_an_ag_user_facing_label_proposes_tribe(label):
    assert "tribe" in classify(issue(1, title="Save button", labels=(label,))).labels


#: One title per alternative of the AG user-surface rule, each matching it alone.
_AG_SURFACE_TITLES = [
    "beta feedback: slow",
    "in-app feedback asks for an export",
    "Food bank users see the wrong total",
    "Pantries cannot export a report",
    "On a phone the header overlaps",
    "Mobile header overlaps",
    "Tap target under 24px",
    "Contrast under 4.5:1",
    "Checkout accepts a retired price",
    "Pricing page shows a stale total",
    "Foundation page header overlaps",
    "Funder page header overlaps",
    "Draft editor loses text",
    "Deadline field prints N/A",
    "Studio stalls on save",
    "Workshop cards overlap",
    "Dashboard counts are off",
    "Kanban columns overlap",
    "Onboarding step repeats",
    "Sign-up form rejects a valid name",
    "Login form rejects a valid name",
    "Magic-link expires early",
    "Monday update email lists nothing",
]


@pytest.mark.parametrize("title", _AG_SURFACE_TITLES)
def test_an_ag_user_surface_in_the_title_proposes_tribe(title):
    assert "tribe" in classify(issue(1, title=title)).labels


def test_an_ag_user_surface_only_in_the_body_does_not_propose_tribe():
    assert "tribe" not in classify(issue(1, title="Rename a module", body="the draft editor")).labels


def test_an_ag_issue_with_no_signal_is_not_tribe():
    assert "tribe" not in classify(issue(1, title="Rename a module")).labels


@pytest.mark.parametrize(
    "label", ["code-quality", "tech-debt", "documentation", "infrastructure", "security", "seo",
              "ops", "planning", "architecture", "stability", "gaudi"],
)
def test_an_internal_label_vetoes_tribe(label):
    proposal = classify(issue(1, title="Checkout breaks", labels=("bug", label)))
    assert "tribe" not in proposal.labels


#: One fixture per alternative of the internal-title rule, each matching that
#: alternative alone, so deleting any one alternative turns its fixture tribe.
_INTERNAL_TITLES = [
    # words anywhere in the title
    "Staging checkout times out",
    "Smoke run hits the checkout",
    "Playwright clicks the checkout",
    "Draft editor telemetry gap",
    "Lighthouse score on the checkout",
    "Unverified: does caching skip the draft",
    "Investigate the slow checkout",
    "Cron sends the deadline email twice",
    "Backfill draft rows",
    # a leading type, optionally behind a bracketed tag
    "tests: pricing page red under with_test_env",
    "test_pricing depends on .env",
    "chore: bump the checkout library",
    "ci: checkout job flakes",
    "docs: deadline help page",
    "[P2] docs: deadline help page",
    "refactor: checkout view",
    "build: draft bundle size",
    "ops: checkout alert",
    "perf: draft editor",
    "spike: checkout flow",
    # a conventional-commit scope
    "fix(ci): checkout passes",
    "fix(tests): checkout fixture",
    "feat(ops): checkout alert",
    "fix(infra): checkout host",
    "fix(deps): checkout library",
    "fix(lint): checkout view",
    "fix(gaudi): checkout view",
]


@pytest.mark.parametrize("title", _INTERNAL_TITLES)
def test_an_internal_title_vetoes_tribe(title):
    assert "tribe" not in classify(issue(1, title=title, labels=("bug",))).labels


@pytest.mark.parametrize("title", ["Checkout breaks", "Draft editor loses text"])
def test_a_user_facing_title_with_a_user_label_is_tribe(title):
    """The positive twin of the internal-title fixtures: same label, no internal word."""
    assert "tribe" in classify(issue(1, title=title, labels=("bug",))).labels


# --- tribe: grantspider ----------------------------------------------------


#: One title per alternative of the GS surface and user-report rules.
_GS_SURFACE_TITLES = [
    "Wrong figure on the foundation page",
    "Funder page shows stale data",
    "AG page lists the wrong city",
    "AG search misses funders",
    "Public page lists the wrong city",
    "Wrong city shown on AG",
    "AG users see stale data",
    "beta corrections: seven reports",
    "beta feedback on funder data",
    "user-reported data correction for a funder",
]


@pytest.mark.parametrize("title", _GS_SURFACE_TITLES)
def test_a_gs_title_naming_what_ag_users_see_proposes_tribe(title):
    assert "tribe" in classify(issue(1, repo="grantspider", title=title)).labels


def test_a_gs_bug_whose_body_names_the_ag_surface_proposes_tribe():
    proposal = classify(
        issue(1, repo="grantspider", title="Row dropped", labels=("bug",),
              body="It is missing from the funder page.")
    )
    assert "tribe" in proposal.labels


def test_a_gs_non_bug_whose_body_names_the_ag_surface_is_not_tribe():
    proposal = classify(
        issue(1, repo="grantspider", title="Row dropped", body="It is missing from the funder page.")
    )
    assert "tribe" not in proposal.labels


def test_a_gs_product_label_alone_does_not_propose_tribe():
    assert "tribe" not in classify(issue(1, repo="grantspider", title="x", labels=("bug",))).labels


# --- proposal shape --------------------------------------------------------


def test_the_two_labels_are_independent():
    proposal = classify(issue(1, title="Checkout breaks", labels=("bug", "kaizen")))
    assert proposal.labels == frozenset({"tribe", "agent-finding"})
    assert proposal.klass == "tribe+agent-finding"


def test_an_issue_with_no_signal_is_unclassified_with_a_reason():
    proposal = classify(issue(1, repo="oversteward", title="Think about it"))
    assert proposal.klass == "unclassified"
    assert proposal.reasons


def test_every_proposed_label_carries_a_reason():
    proposal = classify(issue(1, title="Checkout breaks", labels=("bug", "kaizen")))
    assert len(proposal.reasons) >= 2
