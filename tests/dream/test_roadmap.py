# ABOUTME: Tests for the roadmap intent-reconciliation pass (§13.4) — staleness probe + context packet.
# ABOUTME: Uses inline roadmap text and tmp_path git repos; never reads the real documentation/ROADMAP.md.

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from oversteward.dream.roadmap import (
    count_merges_since,
    gather_packet,
    list_merges_since,
    packet_for_repo,
    parse_last_updated,
    probe_repo,
    probe_staleness,
)

FRESH_STAMP = "*Last updated: 2026-07-26 (July reconciliation, hand-run).*\n"


# ---- parse_last_updated ------------------------------------------------------


def test_parse_last_updated_finds_stamp() -> None:
    text = "# Roadmap\n\nbody\n\n" + FRESH_STAMP
    assert parse_last_updated(text) == date(2026, 7, 26)


def test_parse_last_updated_missing_returns_none() -> None:
    assert parse_last_updated("# Roadmap\nno stamp here\n") is None


def test_parse_last_updated_takes_the_last_occurrence() -> None:
    text = (
        "*Last updated: 2026-06-24 (first dream cycle).*\n\n"
        "history…\n\n"
        "*Last updated: 2026-07-26 (July reconciliation).*\n"
    )
    assert parse_last_updated(text) == date(2026, 7, 26)


def test_parse_last_updated_malformed_date_returns_none() -> None:
    assert parse_last_updated("*Last updated: sometime in July*\n") is None


# ---- probe_staleness ---------------------------------------------------------


def test_probe_fresh_when_recent_and_quiet() -> None:
    report = probe_staleness(FRESH_STAMP, merges_since=0, now=date(2026, 7, 27))
    assert report.stale is False
    assert report.reasons == []
    assert report.stamp == date(2026, 7, 26)


def test_probe_fresh_within_grace_even_with_merges() -> None:
    # Merges landed but the stamp is younger than the grace window — not yet stale.
    report = probe_staleness(FRESH_STAMP, merges_since=3, now=date(2026, 7, 28))
    assert report.stale is False


def test_probe_stale_when_merges_after_grace() -> None:
    report = probe_staleness(FRESH_STAMP, merges_since=3, now=date(2026, 8, 5))
    assert report.stale is True
    assert any("merge" in r for r in report.reasons)


def test_probe_stale_at_hard_cap_even_when_quiet() -> None:
    report = probe_staleness(FRESH_STAMP, merges_since=0, now=date(2026, 8, 30))
    assert report.stale is True
    assert any("hard cap" in r for r in report.reasons)


def test_probe_stale_when_stamp_missing() -> None:
    report = probe_staleness("no stamp\n", merges_since=0, now=date(2026, 7, 27))
    assert report.stale is True
    assert report.stamp is None


def test_probe_to_dict_round_trips_stamp() -> None:
    report = probe_staleness(FRESH_STAMP, merges_since=0, now=date(2026, 7, 27))
    payload = report.to_dict()
    assert payload["stale"] is False
    assert payload["stamp"] == "2026-07-26"
    assert payload["days_old"] == 1


# ---- merge counting against a real (temp) git repo ---------------------------


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *argv],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


def _repo_with_one_merge(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    (repo / "a.txt").write_text("a")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "feature")
    (repo / "b.txt").write_text("b")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "feature work")
    _git(repo, "checkout", "master")
    _git(repo, "merge", "--no-ff", "feature", "-m", "Merge pull request #1 from feature")
    return repo


def test_merges_prefer_origin_master_when_present(tmp_path: Path) -> None:
    # The primary checkout's local master runs behind origin (OS#64) — when an
    # origin/master ref exists, merge counting must use it, not the local ref.
    repo = _repo_with_one_merge(tmp_path)
    # Point origin/master at the pre-merge base commit: counting against it sees
    # zero merges, while the local master ref would see one.
    _git(repo, "update-ref", "refs/remotes/origin/master", "master~1")
    assert count_merges_since(repo, date(2020, 1, 1)) == 0
    assert list_merges_since(repo, date(2020, 1, 1)) == []


def test_count_and_list_merges_since(tmp_path: Path) -> None:
    repo = _repo_with_one_merge(tmp_path)
    assert count_merges_since(repo, date(2020, 1, 1)) == 1
    titles = list_merges_since(repo, date(2020, 1, 1))
    assert titles == ["Merge pull request #1 from feature"]
    # A since-date in the future sees nothing.
    assert count_merges_since(repo, date(2099, 1, 1)) == 0


# ---- disk-level composition --------------------------------------------------


def test_probe_repo_stale_via_merge_after_old_stamp(tmp_path: Path) -> None:
    repo = _repo_with_one_merge(tmp_path)
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("*Last updated: 2026-06-01 (old).*\n")
    report = probe_repo(roadmap, repo, now=date(2026, 7, 27))
    assert report.stale is True
    assert report.merges_since == 1


def test_packet_for_repo_includes_merge_subjects(tmp_path: Path) -> None:
    repo = _repo_with_one_merge(tmp_path)
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("*Last updated: 2026-06-01 (old).*\n")
    packet = packet_for_repo(roadmap, repo, issues=[], prs=[])
    assert "Merge pull request #1 from feature" in packet
    assert "2026-06-01" in packet


# ---- gather_packet -----------------------------------------------------------


def test_gather_packet_includes_all_sections() -> None:
    packet = gather_packet(
        roadmap_text="# Roadmap\n\n" + FRESH_STAMP,
        merges=["Merge pull request #233 from session/roadmap-freshness"],
        issues=[
            {"number": 231, "title": "intent pass", "state": "OPEN"},
            {"number": 114, "title": "dream trigger", "state": "CLOSED"},
        ],
        prs=[{"number": 233, "title": "July reconciliation", "state": "MERGED"}],
    )
    assert "2026-07-26" in packet
    assert "#233" in packet
    assert "OPEN #231" in packet
    assert "CLOSED #114" in packet
    assert "MERGED #233" in packet


def test_gather_packet_handles_empty_feeds() -> None:
    packet = gather_packet(roadmap_text="no stamp", merges=[], issues=[], prs=[])
    assert "(none)" in packet
    assert "unknown" in packet
