# ABOUTME: Tests for the dream store-health report — the dangling-link queue, store size against a ceiling,
# ABOUTME: and its CLI/finalize wiring. Temp stores and temp git repos only; the live store is never touched.

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from oversteward.dream import cycle, runlock, store_health
from oversteward.dream.consolidate import MemoryStore, StoreUnreadable, first_added_dates
from oversteward.dream.ledger import ProcessedLedger, transcript_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude" / "skills" / "dream" / "SKILL.md"
TODAY = date(2026, 11, 11)


# ---- helpers ----------------------------------------------------------------


def _note(root: Path, filename: str, *, name: str | None = None, body: str = "Body.\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem
    path = root / filename
    path.write_text(f"---\nname: {name or stem}\ndescription: d\n---\n\n{body}", encoding="utf-8")
    return path


def _init_git_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)


def _commit(repo: Path, paths: list[Path], when: str) -> None:
    """Commit ``paths`` with both git dates pinned to ``when`` (YYYY-MM-DD)."""
    stamp = f"{when}T12:00:00+00:00"
    env = {**os.environ, "GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp}
    rels = [str(p.relative_to(repo)) for p in paths]
    subprocess.run(["git", "add", "--", *rels], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", f"add {when}"], cwd=repo, check=True, env=env)


def _measure(root: Path, **kwargs: object) -> store_health.StoreHealth:
    kwargs.setdefault("added_on", {})
    kwargs.setdefault("today", TODAY)
    kwargs.setdefault("ceilings", store_health.Ceilings())
    return store_health.measure(MemoryStore(root), **kwargs)


def _targets(health: store_health.StoreHealth) -> list[str]:
    return [link.target for link in health.dangling]


def _dream_cli():
    """The `scripts/dream.py` CLI, loaded by path — `scripts/` is not a package."""
    path = REPO_ROOT / "scripts" / "dream.py"
    spec = importlib.util.spec_from_file_location("dream_cli_store_health_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _never_the_live_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the lock defaults at a sentinel, so a finalize that forgets --lock fails loudly."""
    sentinel = tmp_path / "default-must-not-exist"
    monkeypatch.setattr(runlock, "DEFAULT_LOCK_PATH", sentinel / "dream_run.lock")
    monkeypatch.setattr(runlock, "DEFAULT_RUNS_PATH", sentinel / "dream_runs.jsonl")
    yield
    assert not sentinel.exists()


# ---- the dangling-link queue ------------------------------------------------


def test_a_link_to_no_note_is_queued_with_its_citer(tmp_path: Path) -> None:
    _note(tmp_path, "present.md")
    _note(tmp_path, "citer.md", body="See [[missing]] and [[present]].\n")

    health = _measure(tmp_path)

    assert _targets(health) == ["missing"]
    assert health.dangling[0].citers == ("citer.md",)
    assert health.unique_targets == 2


def test_a_link_resolves_by_the_name_field(tmp_path: Path) -> None:
    _note(tmp_path, "a_file.md", name="other-slug")
    _note(tmp_path, "citer.md", body="[[other-slug]] and [[missing]]\n")

    assert _targets(_measure(tmp_path)) == ["missing"]


def test_a_link_resolves_by_the_filename_stem(tmp_path: Path) -> None:
    _note(tmp_path, "a_file.md", name="other-slug")
    _note(tmp_path, "citer.md", body="[[a_file]] and [[missing]]\n")

    assert _targets(_measure(tmp_path)) == ["missing"]


def test_a_target_is_trimmed_loses_one_md_suffix_and_an_empty_one_is_skipped(
    tmp_path: Path,
) -> None:
    _note(tmp_path, "a_file.md")
    _note(tmp_path, "citer.md", body="[[a_file.md]] [[ a_file ]] [[ ]] [[]] [[missing]]\n")

    health = _measure(tmp_path)

    assert _targets(health) == ["missing"]
    assert health.unique_targets == 2


def test_a_link_inside_code_is_not_a_link(tmp_path: Path) -> None:
    _note(tmp_path, "fenced.md", body="Prose.\n\n```\n[[ghost]]\n```\n\n~~~md\n[[ghost]]\n~~~\n")
    _note(tmp_path, "spanned.md", body="Write `[[ghost]]` or ``a [[ghost]] b`` to link.\n")
    _note(tmp_path, "prose.md", body="A real [[ghost]] link.\n")

    health = _measure(tmp_path)

    assert _targets(health) == ["ghost"]
    assert health.dangling[0].citers == ("prose.md",)


def test_only_fact_notes_are_scanned(tmp_path: Path) -> None:
    _note(tmp_path, "fact.md")
    _note(tmp_path, "MEMORY_REVIEW.md", body="[[ghost]]\n")
    _note(tmp_path, "MEMORY.md", body="[[ghost]]\n")
    _note(tmp_path, "fact.steward-variant.md", body="[[ghost]]\n")

    health = _measure(tmp_path)

    assert _targets(health) == []
    assert health.sizes.notes == 1


def test_the_queue_is_oldest_first(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    store = repo / "memory"
    zzz_citer = _note(store, "cites_zzz.md", body="[[zzz]]\n")
    _commit(repo, [zzz_citer], "2026-01-05")
    aaa_citer = _note(store, "cites_aaa.md", body="[[aaa]]\n")
    _commit(repo, [aaa_citer], "2026-03-01")
    _note(store, "cites_new.md", body="[[mmm]]\n")  # uncommitted: no add date, age 0

    health = _measure(store, added_on=first_added_dates(repo, store))

    assert _targets(health) == ["zzz", "aaa", "mmm"]
    assert [link.added for link in health.dangling] == [
        date(2026, 1, 5),
        date(2026, 3, 1),
        None,
    ]
    assert [link.age_days for link in health.dangling] == [310, 255, 0]


def test_the_oldest_citer_dates_a_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    store = repo / "memory"
    early = _note(store, "early.md", body="[[ghost]]\n")
    _commit(repo, [early], "2026-02-01")
    late = _note(store, "late.md", body="[[ghost]]\n")
    _commit(repo, [late], "2026-06-01")

    health = _measure(store, added_on=first_added_dates(repo, store))

    assert _targets(health) == ["ghost"]
    assert health.dangling[0].citers == ("early.md", "late.md")
    assert health.dangling[0].added == date(2026, 2, 1)


def test_a_re_added_note_keeps_its_first_add_date(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    store = repo / "memory"
    note = _note(store, "fact.md")
    _commit(repo, [note], "2026-01-01")
    subprocess.run(["git", "rm", "-q", "--", "memory/fact.md"], cwd=repo, check=True)
    _commit(repo, [], "2026-02-01")
    note = _note(store, "fact.md", body="Back again.\n")
    _commit(repo, [note], "2026-03-01")

    assert first_added_dates(repo, store) == {"fact.md": date(2026, 1, 1)}


# ---- size against a ceiling -------------------------------------------------


@pytest.mark.parametrize("measure", ["notes", "memory_full_bytes", "total_bytes"])
def test_each_measure_is_over_only_when_strictly_greater(tmp_path: Path, measure: str) -> None:
    _note(tmp_path, "one.md")
    _note(tmp_path, "two.md")
    (tmp_path / "MEMORY_FULL.md").write_text("x" * 500, encoding="utf-8")
    actual = _measure(tmp_path).sizes
    at = {
        "notes": actual.notes,
        "memory_full_bytes": actual.memory_full_bytes,
        "total_bytes": actual.total_bytes,
    }
    assert at == {"notes": 2, "memory_full_bytes": 500, "total_bytes": actual.total_bytes}
    ceilings = store_health.Ceilings(**{**at, measure: at[measure] - 1})

    health = _measure(tmp_path, ceilings=ceilings)

    assert health.over == (measure,)
    assert "OVER CEILING" in health.closing_line()


def test_a_store_at_every_ceiling_is_not_over(tmp_path: Path) -> None:
    _note(tmp_path, "one.md")
    sizes = _measure(tmp_path).sizes
    ceilings = store_health.Ceilings(
        notes=sizes.notes,
        memory_full_bytes=sizes.memory_full_bytes,
        total_bytes=sizes.total_bytes,
    )

    health = _measure(tmp_path, ceilings=ceilings)

    assert health.over == ()
    assert "OVER CEILING" not in health.closing_line()


def test_the_planned_ceilings_and_queue_limit() -> None:
    assert store_health.Ceilings() == store_health.Ceilings(
        notes=3_500, memory_full_bytes=1_000_000, total_bytes=6_000_000
    )
    assert store_health.DEFAULT_QUEUE_LIMIT == 10


# ---- could not read ---------------------------------------------------------


def test_a_missing_root_is_unreadable_not_empty(tmp_path: Path) -> None:
    with pytest.raises(StoreUnreadable, match="not a directory"):
        _measure(tmp_path / "absent")


def test_a_malformed_note_is_unreadable(tmp_path: Path) -> None:
    (tmp_path / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")

    with pytest.raises(StoreUnreadable, match="broken.md"):
        _measure(tmp_path)


def test_a_store_outside_git_is_unreadable(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "fact.md")

    with pytest.raises(StoreUnreadable, match="git"):
        first_added_dates(tmp_path, store)


def test_a_repo_with_no_commits_dates_nothing(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    store = tmp_path / "memory"
    _note(store, "fact.md", body="[[ghost]]\n")

    added = first_added_dates(tmp_path, store)
    health = _measure(store, added_on=added)

    assert added == {}
    assert [(link.target, link.added, link.age_days) for link in health.dangling] == [
        ("ghost", None, 0)
    ]


# ---- ruled this run ---------------------------------------------------------


def test_ruled_is_the_set_of_snapshot_targets_that_no_longer_dangle(tmp_path: Path) -> None:
    _note(tmp_path, "citer.md", body="[[b]] [[c]]\n")

    health = _measure(tmp_path, dangling_before=frozenset({"a", "b"}))

    assert health.ruled == 1
    assert health.closing_line().startswith("2 dangling (1 ruled this run); store 1 notes / ")


def test_ruled_without_a_snapshot_is_unmeasured(tmp_path: Path) -> None:
    _note(tmp_path, "citer.md", body="[[b]]\n")

    health = _measure(tmp_path)

    assert health.ruled is None
    assert health.closing_line().startswith("1 dangling (ruled: unmeasured); store 1 notes / ")


def test_the_closing_line_reports_size_against_the_total_ceiling(tmp_path: Path) -> None:
    _note(tmp_path, "citer.md", body="[[b]]\n")
    (tmp_path / "MEMORY_FULL.md").write_text("x" * 7_000, encoding="utf-8")
    ceilings = store_health.Ceilings(notes=10, memory_full_bytes=5_000, total_bytes=9_000)

    line = _measure(tmp_path, ceilings=ceilings).closing_line()

    assert line.startswith("1 dangling (ruled: unmeasured); store 1 notes / 7 KB of 9 KB ceiling")
    assert line.endswith(" — OVER CEILING: MEMORY_FULL.md 7,000/5,000 B")


# ---- the CLI ----------------------------------------------------------------


def _cli_store(tmp_path: Path, *, full_bytes: int) -> tuple[Path, Path]:
    repo = tmp_path / "steward-memory"
    _init_git_repo(repo)
    store = repo / "memory"
    old = _note(store, "old.md", body="[[ghost]] [[old]]\n")
    _commit(repo, [old], "2026-10-01")
    (store / "MEMORY_FULL.md").write_text("x" * full_bytes, encoding="utf-8")
    return repo, store


def _store_health_argv(repo: Path, store: Path) -> list[str]:
    return [
        "cycle", "store-health",
        "--store", str(store), "--store-repo", str(repo), "--today", "2026-11-11",
    ]


def test_cli_store_health_under_every_ceiling_exits_0_and_names_its_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, store = _cli_store(tmp_path, full_bytes=1_000_000)

    code = _dream_cli().main(_store_health_argv(repo, store))

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["over"] == []
    assert out["dangling_total"] == 1
    assert out["unique_targets"] == 2
    assert out["queue"] == [
        {"target": "ghost", "citers": ["old.md"], "added": "2026-10-01", "age_days": 41}
    ]
    assert out["sizes"]["notes"] == 1
    assert out["sizes"]["memory_full_bytes"] == 1_000_000
    assert out["ceilings"] == {
        "notes": 3_500,
        "memory_full_bytes": 1_000_000,
        "total_bytes": 6_000_000,
    }
    assert out["closing_line"].startswith("1 dangling (ruled: unmeasured); store 1 notes / ")


def test_cli_store_health_over_a_ceiling_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, store = _cli_store(tmp_path, full_bytes=1_000_001)

    code = _dream_cli().main(_store_health_argv(repo, store))

    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["over"] == ["memory_full_bytes"]


def test_cli_store_health_limits_the_queue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, store = _cli_store(tmp_path, full_bytes=10)
    _note(store, "more.md", body="[[g1]] [[g2]] [[g3]]\n")

    code = _dream_cli().main([*_store_health_argv(repo, store), "--limit", "2"])

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["dangling_total"] == 4
    assert [entry["target"] for entry in out["queue"]] == ["ghost", "g1"]


def _assert_could_not_read(code: int, captured: pytest.CaptureFixture[str]) -> None:
    out, err = captured.out, captured.err
    assert code == 2
    assert out == ""
    assert "store unreadable" in err
    assert "Traceback" not in err


def test_cli_store_health_missing_store_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "steward-memory"
    _init_git_repo(repo)

    code = _dream_cli().main(_store_health_argv(repo, repo / "memory"))

    _assert_could_not_read(code, capsys.readouterr())


def test_cli_store_health_malformed_note_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, store = _cli_store(tmp_path, full_bytes=10)
    (store / "broken.md").write_text("no frontmatter\n", encoding="utf-8")

    code = _dream_cli().main(_store_health_argv(repo, store))

    _assert_could_not_read(code, capsys.readouterr())


def test_cli_store_health_non_git_store_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "plain" / "memory"
    _note(store, "fact.md")

    code = _dream_cli().main(_store_health_argv(tmp_path / "plain", store))

    _assert_could_not_read(code, capsys.readouterr())


# ---- finalize ---------------------------------------------------------------


def _finalize_fixture(tmp_path: Path) -> tuple[Path, MemoryStore, ProcessedLedger, Path]:
    repo = tmp_path / "steward-memory"
    _init_git_repo(repo)
    store = MemoryStore(repo / "memory")
    _note(store.root, "citer.md", body="[[missing]] [[kept]]\n")
    ledger = ProcessedLedger(tmp_path / "data" / "ledger.jsonl")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("bytes")
    return repo, store, ledger, transcript


def _processed(transcript: Path) -> list[cycle.PendingTranscript]:
    return [
        cycle.PendingTranscript("s1", str(transcript), "oversteward", transcript_hash(transcript))
    ]


def test_finalize_run_measures_the_store_it_commits(tmp_path: Path) -> None:
    repo, store, ledger, transcript = _finalize_fixture(tmp_path)

    result = cycle.finalize_run(
        store,
        cycle.RunResults(written_paths=[store.root / "citer.md"], processed=_processed(transcript)),
        ledger,
        cycle.FinalizeOptions(
            repo_root=repo,
            now=datetime(2026, 11, 11, tzinfo=timezone.utc),
            dangling_before=frozenset({"missing", "gone"}),
        ),
    )

    assert result.store_health is not None
    assert result.store_health.closing_line().startswith(
        "2 dangling (1 ruled this run); store 1 notes / "
    )
    assert result.commit.committed is True


def test_an_unreadable_measurement_leaves_no_commit_and_no_ledger_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, store, ledger, transcript = _finalize_fixture(tmp_path)
    failure = StoreUnreadable("git log failed")
    monkeypatch.setattr(store_health, "first_added_dates", mock.MagicMock(side_effect=failure))

    with pytest.raises(StoreUnreadable):
        cycle.finalize_run(
            store,
            cycle.RunResults(processed=_processed(transcript)),
            ledger,
            cycle.FinalizeOptions(repo_root=repo),
        )

    head = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert head.returncode == 1  # still no commits
    assert ledger.is_processed(transcript_hash(transcript)) is False


def _finalize_argv(tmp_path: Path, repo: Path, store: MemoryStore, transcript: Path) -> list[str]:
    pending = _processed(transcript)[0].to_dict()
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"transcripts": [pending]}), encoding="utf-8")
    return [
        "cycle", "finalize",
        "--results", str(results),
        "--store", str(store.root),
        "--store-repo", str(repo),
        "--ledger", str(tmp_path / "data" / "ledger.jsonl"),
        "--queue", str(tmp_path / "queue.jsonl"),
        "--flagged", str(tmp_path / "data" / "flagged.jsonl"),
        "--lock", str(tmp_path / "dream_run.lock"),
        "--runs", str(tmp_path / "dream_runs.jsonl"),
    ]


def test_cli_finalize_emits_store_health_with_the_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, store, _, transcript = _finalize_fixture(tmp_path)
    before = tmp_path / "dangling.json"
    before.write_text(
        json.dumps({"queue": [{"target": "missing"}, {"target": "gone"}]}), encoding="utf-8"
    )
    argv = [*_finalize_argv(tmp_path, repo, store, transcript), "--dangling-before", str(before)]

    code = _dream_cli().main(argv)

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["committed"] is True
    assert out["store_health"]["closing_line"].startswith(
        "2 dangling (1 ruled this run); store 1 notes / "
    )
    assert out["store_health"]["dangling_total"] == 2


def test_cli_finalize_over_a_ceiling_still_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, store, _, transcript = _finalize_fixture(tmp_path)
    # A sidecar is no fact note, but its bytes count toward the store's total.
    (store.root / "big.steward-variant.md").write_bytes(b"x" * 6_000_001)

    code = _dream_cli().main(_finalize_argv(tmp_path, repo, store, transcript))

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["committed"] is True
    assert out["store_health"]["over"] == ["total_bytes"]


def test_cli_finalize_unreadable_store_exits_2_and_keeps_the_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, store, _, transcript = _finalize_fixture(tmp_path)
    failure = StoreUnreadable("git log failed")
    monkeypatch.setattr(store_health, "first_added_dates", mock.MagicMock(side_effect=failure))

    code = _dream_cli().main(_finalize_argv(tmp_path, repo, store, transcript))

    _assert_could_not_read(code, capsys.readouterr())
    assert (tmp_path / "dream_run.lock").read_bytes() != b""


# ---- the skill (a pin on prose, not a guard) --------------------------------


def test_skill_runs_store_health_and_feeds_the_snapshot_to_finalize() -> None:
    """A text pin: SKILL.md names the commands. It proves the prose, not the behaviour."""
    text = SKILL.read_text(encoding="utf-8")
    assert "## Step 3b" in text
    step1 = text.split("## Step 1")[1].split("## Step 2")[0]
    step3b = text.split("## Step 3b")[1].split("## Step 4")[0]
    step4 = text.split("## Step 4")[1].split("## Step 5")[0]
    report = text.split("## Report")[1].split("## Invariants")[0]

    assert "$DREAM store-health" in step1
    assert "$DREAM store-health" in step3b
    assert "written_paths" in step3b
    assert "--dangling-before" in step4
    assert "closing line" in report
    assert 'just "ledger current."' not in text
