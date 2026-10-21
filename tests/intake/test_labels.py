# ABOUTME: Tests for the dispatch label taxonomy and the service that upserts it on every repo.
# ABOUTME: The taxonomy is the one place a dispatch label's name, colour and meaning are written.

from __future__ import annotations

import re

from oversteward.intake.labels import DISPATCH_LABELS, ensure_labels


def _names():
    return [spec.name for spec in DISPATCH_LABELS]


def test_the_intake_labels_are_in_the_taxonomy():
    assert {"tribe", "agent-finding", "shelved"} <= set(_names())


def test_the_existing_dispatch_labels_stay_in_the_taxonomy():
    assert {
        "ready-for-agent", "needs-scoping", "needs-input", "agent-in-progress",
        "reject-close", "dispatch-paused",
    } <= set(_names())


def test_label_names_are_unique():
    assert len(_names()) == len(set(_names()))


def test_every_colour_is_six_hex_digits_and_every_label_is_described():
    for spec in DISPATCH_LABELS:
        assert re.fullmatch(r"[0-9A-F]{6}", spec.color), spec
        assert spec.description.strip(), spec


def test_ensure_labels_upserts_every_label_on_every_repo():
    calls = []
    failures = ensure_labels(["o/a", "o/b"], lambda repo, spec: calls.append((repo, spec.name)))
    assert failures == []
    assert sorted(calls) == sorted((r, n) for r in ("o/a", "o/b") for n in _names())


def test_ensure_labels_keeps_going_past_a_failure_and_reports_it():
    calls = []

    def upsert(repo, spec):
        calls.append((repo, spec.name))
        if repo == "o/a" and spec.name == "tribe":
            raise RuntimeError("HTTP 403")

    failures = ensure_labels(["o/a", "o/b"], upsert)
    assert failures == [("o/a", "tribe", "HTTP 403")]
    assert ("o/b", "tribe") in calls
