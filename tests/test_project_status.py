# ABOUTME: Tests for scripts/project_status.py's tribe-first ranking (OS#613).
# ABOUTME: The scoping candidate and the dispatch-queue block both put a `tribe` issue first.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ps():
    """project_status.py imports its sibling ``registry`` by bare name, as a script does."""
    prior = sys.modules.get("registry")
    _load("registry", SCRIPTS / "registry.py")
    module = _load("oversteward_project_status", SCRIPTS / "project_status.py")
    yield module
    if prior is None:
        sys.modules.pop("registry", None)
    else:
        sys.modules["registry"] = prior


def _issue(number, labels=(), created="2026-10-01T00:00:00Z", title=None):
    return {
        "number": number,
        "title": title or f"issue {number}",
        "url": f"https://github.com/NathanKrupa/aigranthelper/issues/{number}",
        "labels": [{"name": name} for name in labels],
        "createdAt": created,
        "updatedAt": created,
    }


def test_a_young_tribe_scoping_issue_outranks_an_old_plain_one(ps):
    old = _issue(1, ("needs-scoping",), created="2026-01-01T00:00:00Z")
    young_tribe = _issue(2, ("needs-scoping", "tribe"), created="2026-10-01T00:00:00Z")
    picked, source = ps.pick_scoping_candidate([old, young_tribe])
    assert (picked["number"], source) == (2, "labeled")


def test_the_scoping_fallback_also_ranks_tribe_first(ps):
    old = _issue(1, created="2026-01-01T00:00:00Z")
    young_tribe = _issue(2, ("tribe",), created="2026-10-01T00:00:00Z")
    picked, source = ps.pick_scoping_candidate([old, young_tribe])
    assert (picked["number"], source) == (2, "fallback")


def test_without_tribe_the_oldest_scoping_issue_still_wins(ps):
    old = _issue(1, ("needs-scoping",), created="2026-01-01T00:00:00Z")
    young = _issue(2, ("needs-scoping",), created="2026-10-01T00:00:00Z")
    assert ps.pick_scoping_candidate([young, old])[0]["number"] == 1


def test_the_dispatch_queue_block_lists_tribe_first_and_marks_it(ps):
    results = [
        {
            "repo": "aigranthelper",
            "open_issues": [
                _issue(1, ("ready-for-agent",), created="2026-01-01T00:00:00Z", title="old plain"),
                _issue(2, ("ready-for-agent", "tribe"), title="pantry draft"),
                _issue(3, ("tribe",), title="unready tribe"),
            ],
            "open_prs": [],
        }
    ]
    lines = "\n".join(ps.render_dispatch_queues(results))
    assert lines.index("pantry draft") < lines.index("old plain")
    assert "unready tribe" not in lines
    assert "[tribe]" in lines


def test_an_errored_repo_is_left_out_of_the_queue_block(ps):
    lines = ps.render_dispatch_queues([{"repo": "aigranthelper", "error": "gh failed"}])
    assert "gh failed" not in "\n".join(lines)


def test_the_full_render_carries_the_dispatch_queue_block(ps):
    from datetime import UTC, datetime

    now = datetime(2026, 10, 21, tzinfo=UTC)
    results = [
        {
            "repo": "aigranthelper",
            "open_issues": [_issue(2, ("ready-for-agent", "tribe"), title="pantry draft")],
            "open_prs": [],
            "closed_issue_count": 0,
            "merged_pr_count": 0,
            "merged_prs_window": [],
            "closed_unmerged_count_window": 0,
        }
    ]
    out = ps.render(results, now, False, now, ps.compute_metrics(results, now))
    assert "pantry draft" in out
    assert "tribe first" in out
