# ABOUTME: Tests for the intake gh connector — argv shape, the truncation guard, failure mapping.
# ABOUTME: The runner is injected; no test reaches GitHub.

from __future__ import annotations

import pytest

from oversteward.intake import github
from oversteward.intake.labels import LabelSpec


def test_list_open_issues_asks_for_open_issues_with_the_fields_the_classifier_reads():
    seen = []

    def run(args):
        seen.append(args)
        return [{"number": 1}]

    assert github.list_open_issues("o/r", run=run) == [{"number": 1}]
    args = seen[0]
    assert args[:2] == ["issue", "list"]
    assert args[args.index("--repo") + 1] == "o/r"
    assert args[args.index("--state") + 1] == "open"
    fields = set(args[args.index("--json") + 1].split(","))
    assert {"number", "title", "labels", "body", "createdAt", "url"} <= fields
    assert int(args[args.index("--limit") + 1]) == github.OPEN_LIMIT


def test_a_page_that_fills_its_limit_is_refused():
    with pytest.raises(github.TruncatedReadError):
        github.list_open_issues("o/r", run=lambda args: [{}] * github.OPEN_LIMIT)


def test_a_page_one_under_the_limit_is_accepted():
    rows = github.list_open_issues("o/r", run=lambda args: [{}] * (github.OPEN_LIMIT - 1))
    assert len(rows) == github.OPEN_LIMIT - 1


def test_add_labels_repeats_the_add_label_flag():
    seen = []
    github.add_labels("o/r", 7, ("agent-finding", "tribe"), run=seen.append)
    assert seen == [
        ["issue", "edit", "7", "--repo", "o/r", "--add-label", "agent-finding",
         "--add-label", "tribe"]
    ]


def test_upsert_label_forces_so_a_rerun_updates_rather_than_fails():
    seen = []
    github.upsert_label("o/r", LabelSpec("tribe", "0052CC", "desc"), run=seen.append)
    assert seen == [
        ["label", "create", "tribe", "--repo", "o/r", "--color", "0052CC",
         "--description", "desc", "--force"]
    ]


class _Proc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_a_failing_gh_raises_gh_error_carrying_its_stderr():
    with pytest.raises(github.GhError, match="auth required"):
        github.gh(["issue", "list"], run=lambda *a, **k: _Proc(4, stderr="auth required"))


def test_gh_runs_the_gh_binary_with_the_args():
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return _Proc(0, stdout="ok")

    assert github.gh(["label", "list"], run=run) == "ok"
    assert seen == [["gh", "label", "list"]]


def test_gh_json_parses_stdout():
    run = lambda *a, **k: _Proc(0, stdout='[{"number": 3}]')  # noqa: E731
    assert github.gh_json(["issue", "list"], run=run) == [{"number": 3}]


def test_gh_json_reads_empty_output_as_no_rows():
    assert github.gh_json(["issue", "list"], run=lambda *a, **k: _Proc(0, stdout="  ")) == []
