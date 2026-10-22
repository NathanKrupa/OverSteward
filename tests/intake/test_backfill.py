# ABOUTME: Tests for the one-time backfill — counts, the seeded sample, the report and the apply plan.
# ABOUTME: The plan only ever adds labels an issue lacks; it never removes one.

from __future__ import annotations

from oversteward.intake.backfill import (
    apply_plan,
    classify_all,
    count_by_repo,
    plan,
    render_report,
    sample_by_class,
)

from .conftest import issue


def _rows():
    return classify_all(
        [
            issue(1, title="Checkout breaks", labels=("bug",)),
            issue(2, title="Checkout breaks", labels=("bug", "kaizen")),
            issue(3, repo="oversteward", labels=("kaizen",)),
            issue(4, repo="oversteward", title="Think about it"),
            issue(5, repo="oversteward", labels=("kaizen", "agent-finding")),
        ]
    )


def test_counts_are_per_repo_per_class():
    counts = count_by_repo(_rows())
    assert counts["aigranthelper"] == {"tribe": 1, "tribe+agent-finding": 1}
    assert counts["oversteward"] == {"agent-finding": 2, "unclassified": 1}


def test_the_plan_adds_only_missing_labels():
    steps = {(s.repo, s.number): s.labels for s in plan(_rows())}
    assert steps[("aigranthelper", 1)] == ("tribe",)
    assert steps[("aigranthelper", 2)] == ("agent-finding", "tribe")
    assert steps[("oversteward", 3)] == ("agent-finding",)


def test_the_plan_skips_unclassified_and_already_labelled_issues():
    numbers = {(s.repo, s.number) for s in plan(_rows())}
    assert ("oversteward", 4) not in numbers
    assert ("oversteward", 5) not in numbers


def test_apply_keeps_going_past_a_failed_step_and_reports_it():
    """The failing step is a middle one, so a run that stopped there would skip #3."""
    calls = []

    def add(repo, number, labels):
        calls.append((repo, number, labels))
        if number == 2:
            raise RuntimeError("gh refused")

    failures = apply_plan(plan(_rows()), add)
    assert [c[1] for c in calls] == [1, 2, 3]
    assert [(f.step.number, f.error) for f in failures] == [(2, "gh refused")]


def test_the_sample_is_reproducible_for_a_seed_and_capped_per_class():
    rows = classify_all([issue(n, title="Checkout breaks", labels=("bug",)) for n in range(1, 40)])
    first = sample_by_class(rows, per_class=10, seed=7)
    again = sample_by_class(rows, per_class=10, seed=7)
    assert [r.issue.number for r in first["tribe"]] == [r.issue.number for r in again["tribe"]]
    assert len(first["tribe"]) == 10


def test_a_different_seed_draws_a_different_sample():
    rows = classify_all([issue(n, title="Checkout breaks", labels=("bug",)) for n in range(1, 40)])
    a = [r.issue.number for r in sample_by_class(rows, per_class=10, seed=1)["tribe"]]
    b = [r.issue.number for r in sample_by_class(rows, per_class=10, seed=2)["tribe"]]
    assert a != b


def test_a_class_smaller_than_the_cap_is_sampled_whole():
    assert len(sample_by_class(_rows(), per_class=10, seed=0)["unclassified"]) == 1


def test_the_report_carries_counts_samples_titles_and_reasons():
    report = render_report(_rows(), per_class=10, seed=0, generated="2026-10-21")
    assert "aigranthelper" in report and "oversteward" in report
    assert "Think about it" in report
    assert "label kaizen" in report
    assert "dry run" in report.lower()
    for klass in ("tribe", "agent-finding", "tribe+agent-finding", "unclassified"):
        assert f"## Sample: {klass}" in report


def test_the_report_states_how_many_labels_apply_would_add():
    report = render_report(_rows(), per_class=10, seed=0, generated="2026-10-21")
    assert "3 issues" in report


# --- --only: restrict the plan to named labels (OS#620) ---------------------

TRIBE_ONLY = frozenset({"tribe"})


def test_only_tribe_adds_tribe_alone_to_a_tribe_and_agent_finding_proposal():
    steps = {(s.repo, s.number): s.labels for s in plan(_rows(), only=TRIBE_ONLY)}
    assert steps[("aigranthelper", 2)] == ("tribe",)
    assert all("agent-finding" not in labels for labels in steps.values())


def test_only_tribe_plans_nothing_for_an_agent_finding_only_proposal():
    numbers = {(s.repo, s.number) for s in plan(_rows(), only=TRIBE_ONLY)}
    assert ("oversteward", 3) not in numbers
    assert numbers == {("aigranthelper", 1), ("aigranthelper", 2)}


def test_no_filter_plans_every_proposed_label():
    assert plan(_rows(), only=None) == plan(_rows())


def test_the_report_header_states_the_filter_and_the_filtered_counts():
    report = render_report(_rows(), per_class=10, seed=0, generated="2026-10-22", only=TRIBE_ONLY)
    header = report.split("## Counts per repository")[0]
    assert "--only tribe" in header
    assert "2 issues (2 label additions)" in header


def test_the_unfiltered_report_header_names_no_filter():
    report = render_report(_rows(), per_class=10, seed=0, generated="2026-10-22")
    assert "--only" not in report
