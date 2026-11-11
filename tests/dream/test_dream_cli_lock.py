# ABOUTME: Tests that scripts/dream.py takes the run lock before any store write and maps refusals to exit codes.
# ABOUTME: A live `sleep` process is the foreign holder; every lock, ledger and store path is a temp path.

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from oversteward.dream import cycle, runlock
from oversteward.dream.consolidate import CommitResult

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude" / "skills" / "dream" / "SKILL.md"


def _dream_cli():
    """The `scripts/dream.py` CLI, loaded by path — `scripts/` is not a package."""
    path = REPO_ROOT / "scripts" / "dream.py"
    spec = importlib.util.spec_from_file_location("dream_cli_lock_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.usefixtures("never_the_live_lock")


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    store_repo = tmp_path / "steward-memory"
    store = store_repo / "memory"
    store.mkdir(parents=True)
    (store / "a-fact.md").write_text("---\nname: a fact\n---\nbody\n")
    return {
        "lock": tmp_path / "dream_run.lock",
        "runs": tmp_path / "dream_runs.jsonl",
        "store": store,
        "store_repo": store_repo,
        "ledger": tmp_path / "data" / "processed_transcripts.jsonl",
        "queue": tmp_path / "dream_queue.jsonl",
        "flagged": tmp_path / "data" / "flagged.jsonl",
        "tmp": tmp_path,
    }


def _lock_args(p: dict[str, Path]) -> list[str]:
    return ["--lock", str(p["lock"]), "--runs", str(p["runs"])]


def _rows(p: dict[str, Path]) -> list[dict]:
    if not p["runs"].exists():
        return []
    return [json.loads(line) for line in p["runs"].read_text().splitlines() if line.strip()]


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _write(path: Path, payload: object) -> str:
    path.write_text(json.dumps(payload))
    return str(path)


def _argv(command: str, p: dict[str, Path]) -> list[str]:
    tmp = p["tmp"]
    if command == "apply":
        return [
            "cycle", "apply",
            "--worksheet", _write(tmp / "worksheet.json", {"worksheets": []}),
            "--verdicts", _write(tmp / "verdicts.json", []),
            "--store", str(p["store"]),
        ]
    if command == "finalize":
        return [
            "cycle", "finalize",
            "--results", _write(tmp / "results.json", {"transcripts": []}),
            "--store", str(p["store"]),
            "--store-repo", str(p["store_repo"]),
            "--ledger", str(p["ledger"]),
            "--queue", str(p["queue"]),
            "--flagged", str(p["flagged"]),
        ]
    if command == "drain":
        return [
            "cycle", "drain",
            "--store", str(p["store"]),
            "--store-repo", str(p["store_repo"]),
            "--flagged", str(p["flagged"]),
        ]
    if command == "supersede":
        return ["supersede", "a-fact", "no successor — test", "--store", str(p["store"])]
    if command == "end":
        return ["cycle", "end", "--reason", "test"]
    raise AssertionError(command)


# Each writer's service seam, the call the lock must precede, and a return value shaped
# like the real one, so an unguarded handler runs to completion instead of crashing.
def _seam(command: str, cli) -> tuple[object, str, object]:
    if command == "apply":
        return cli.cycle, "apply_verdicts", []
    if command == "finalize":
        commit = CommitResult(committed=False, message="m")
        result = cycle.FinalizeResult(index_path=Path("i"), review_path=Path("r"), commit=commit)
        return cli.cycle, "finalize_run", result
    if command == "drain":
        return cli.cycle, "drain_flagged", cycle.DrainResult(drained=0, review_path=Path("r"), remaining=0)
    if command == "supersede":
        retired = mock.MagicMock(filename="a-fact.md", metadata={"superseded_by": "x"})
        return cli, "supersede", retired
    raise AssertionError(command)


WRITERS = ["apply", "drain", "finalize", "supersede"]


# ---- refusals ----------------------------------------------------------------


def test_begin_against_a_live_foreign_holder_exits_3_and_records_the_skip(
    paths, foreign, capsys
) -> None:
    paths["lock"].write_text(json.dumps(foreign))
    before = paths["lock"].read_bytes()

    code = _dream_cli().main(["cycle", "begin", *_lock_args(paths)])

    err = capsys.readouterr().err
    assert code == 3
    assert str(foreign["pid"]) in err and "timer" in err and "2026-11-11T03:30:00" in err
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1
    assert paths["lock"].read_bytes() == before
    rows = _rows(paths)
    assert [r["event"] for r in rows] == ["skipped"]
    assert rows[0]["reason"] == f"locked by {foreign['pid']}"


@pytest.mark.parametrize("command", WRITERS)
def test_writers_never_run_while_another_live_run_holds_the_lock(
    command, paths, foreign, capsys, monkeypatch
) -> None:
    cli = _dream_cli()
    owner, name, returned = _seam(command, cli)
    seam = mock.MagicMock(name=name, return_value=returned)
    monkeypatch.setattr(owner, name, seam)
    monkeypatch.setattr(cli, "classify", mock.MagicMock(return_value=mock.MagicMock(kind="model")))
    paths["lock"].write_text(json.dumps(foreign))
    lock_before = paths["lock"].read_bytes()
    store_before = _tree_digest(paths["store_repo"])

    code = cli.main([*_argv(command, paths), *_lock_args(paths)])

    err = capsys.readouterr().err
    assert code == 3
    assert f"locked by pid {foreign['pid']}" in err
    assert "Traceback" not in err
    seam.assert_not_called()
    assert _tree_digest(paths["store_repo"]) == store_before
    assert paths["lock"].read_bytes() == lock_before


def test_end_against_a_live_foreign_holder_exits_3_and_closes_nothing(paths, foreign, capsys) -> None:
    paths["lock"].write_text(json.dumps(foreign))
    before = paths["lock"].read_bytes()

    code = _dream_cli().main([*_argv("end", paths), *_lock_args(paths)])

    err = capsys.readouterr().err
    assert code == 3
    assert f"locked by pid {foreign['pid']}" in err
    assert "Traceback" not in err
    assert paths["lock"].read_bytes() == before
    assert "ended" not in [r["event"] for r in _rows(paths)]


def test_begin_twice_from_one_holder_is_one_run(paths, capsys) -> None:
    cli = _dream_cli()
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0
    first = json.loads(paths["lock"].read_text())
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0
    assert json.loads(paths["lock"].read_text())["started_at"] == first["started_at"]
    assert [r["event"] for r in _rows(paths)] == ["started"]


# ---- could not look ----------------------------------------------------------


def _assert_unreadable(code: int, err: str) -> None:
    assert code == 2
    assert "could not read the run lock" in err
    assert "locked by" not in err
    assert "Traceback" not in err


def test_a_garbage_lock_exits_2_and_writes_nothing(paths, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    seam = mock.MagicMock(name="apply_verdicts")
    monkeypatch.setattr(cli.cycle, "apply_verdicts", seam)
    paths["lock"].write_text("not json {")
    before = paths["lock"].read_bytes()

    code = cli.main([*_argv("apply", paths), *_lock_args(paths)])

    _assert_unreadable(code, capsys.readouterr().err)
    seam.assert_not_called()
    assert paths["lock"].read_bytes() == before


def test_blind_liveness_exits_2(paths, foreign, capsys, monkeypatch) -> None:
    paths["lock"].write_text(json.dumps(foreign))
    monkeypatch.setattr(runlock, "proc_start_time", lambda pid, proc_root=None: None)

    code = _dream_cli().main(["cycle", "begin", *_lock_args(paths)])

    _assert_unreadable(code, capsys.readouterr().err)


def test_a_held_flock_exits_2(paths, capsys, monkeypatch) -> None:
    monkeypatch.setattr(runlock, "DEFAULT_WAIT_SECONDS", 0.05)
    fd = os.open(paths["lock"], os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        code = _dream_cli().main(["cycle", "begin", *_lock_args(paths)])
    finally:
        os.close(fd)

    _assert_unreadable(code, capsys.readouterr().err)
    assert paths["lock"].read_bytes() == b""


# ---- release -----------------------------------------------------------------


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)


def _finalize_with_one_transcript(cli, paths) -> int:
    transcript = paths["tmp"] / "t.jsonl"
    transcript.write_text("bytes")
    pending = {"session_id": "s1", "path": str(transcript), "repo": "oversteward", "content_hash": "h1"}
    argv = _argv("finalize", paths)
    argv[argv.index("--results") + 1] = _write(paths["tmp"] / "results.json", {"transcripts": [pending]})
    return cli.main([*argv, *_lock_args(paths)])


def test_finalize_releases_and_records_the_count_on_success(paths, capsys) -> None:
    _init_git_repo(paths["store_repo"])
    cli = _dream_cli()
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0

    assert _finalize_with_one_transcript(cli, paths) == 0

    assert paths["lock"].read_bytes() == b""
    rows = _rows(paths)
    assert [r["event"] for r in rows] == ["started", "completed"]
    assert rows[1]["count"] == 1


def test_a_failed_finalize_keeps_the_lock(paths, capsys, monkeypatch) -> None:
    # A real store repo, so the failure is the commit's and not the store measurement's.
    _init_git_repo(paths["store_repo"])
    cli = _dream_cli()
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0
    held = paths["lock"].read_bytes()
    failure = subprocess.CalledProcessError(1, ["git", "commit"])
    monkeypatch.setattr(cycle, "commit_store", mock.MagicMock(side_effect=failure))

    with pytest.raises(subprocess.CalledProcessError):
        _finalize_with_one_transcript(cli, paths)

    assert paths["lock"].read_bytes() == held
    assert [r["event"] for r in _rows(paths)] == ["started"]


def test_end_closes_the_run_with_its_reason(paths, capsys) -> None:
    cli = _dream_cli()
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0
    assert cli.main(["cycle", "end", "--reason", "ledger current", *_lock_args(paths)]) == 0
    assert paths["lock"].read_bytes() == b""
    rows = _rows(paths)
    assert [r["event"] for r in rows] == ["started", "ended"]
    assert rows[1]["reason"] == "ledger current"


def test_a_writer_called_without_begin_takes_the_lock_itself(paths, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    monkeypatch.setattr(cli.cycle, "apply_verdicts", mock.MagicMock(return_value=[]))
    assert cli.main([*_argv("apply", paths), *_lock_args(paths)]) == 0
    assert json.loads(paths["lock"].read_text())["pid"] > 0
    assert [r["event"] for r in _rows(paths)] == ["started"]


def test_end_on_a_free_lock_records_the_close_and_no_start(paths, capsys) -> None:
    """After finalize released, an abort's `end` must not log a run that never began."""
    cli = _dream_cli()
    argv = ["cycle", "end", "--reason", "step 6 aborted", "--trigger", "session", *_lock_args(paths)]
    assert cli.main(argv) == 0
    assert not paths["lock"].exists() or paths["lock"].read_bytes() == b""
    rows = _rows(paths)
    assert [r["event"] for r in rows] == ["ended"]
    assert rows[0]["trigger"] == "session"


def _drain_seam(cli, monkeypatch) -> None:
    result = cycle.DrainResult(drained=0, review_path=Path("r"), remaining=0)
    monkeypatch.setattr(cli.cycle, "drain_flagged", mock.MagicMock(return_value=result))


def test_drain_alone_releases_what_it_acquired(paths, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    _drain_seam(cli, monkeypatch)
    assert cli.main([*_argv("drain", paths), *_lock_args(paths)]) == 0
    assert paths["lock"].read_bytes() == b""
    assert [r["event"] for r in _rows(paths)] == ["started", "ended"]


def test_drain_inside_a_run_leaves_the_run_holding(paths, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    _drain_seam(cli, monkeypatch)
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0
    held = paths["lock"].read_bytes()
    assert cli.main([*_argv("drain", paths), *_lock_args(paths)]) == 0
    assert paths["lock"].read_bytes() == held
    assert [r["event"] for r in _rows(paths)] == ["started"]


def test_supersede_alone_releases_what_it_acquired(paths, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    retired = mock.MagicMock(filename="a-fact.md", metadata={"superseded_by": "x"})
    monkeypatch.setattr(cli, "supersede", mock.MagicMock(return_value=retired))
    monkeypatch.setattr(cli, "classify", mock.MagicMock(return_value=mock.MagicMock(kind="model")))
    assert cli.main([*_argv("supersede", paths), *_lock_args(paths)]) == 0
    assert paths["lock"].read_bytes() == b""
    assert [r["event"] for r in _rows(paths)] == ["started", "ended"]


def test_supersede_inside_a_run_leaves_the_run_holding(paths, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    retired = mock.MagicMock(filename="a-fact.md", metadata={"superseded_by": "x"})
    monkeypatch.setattr(cli, "supersede", mock.MagicMock(return_value=retired))
    monkeypatch.setattr(cli, "classify", mock.MagicMock(return_value=mock.MagicMock(kind="model")))
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0
    held = paths["lock"].read_bytes()
    assert cli.main([*_argv("supersede", paths), *_lock_args(paths)]) == 0
    assert paths["lock"].read_bytes() == held
    assert [r["event"] for r in _rows(paths)] == ["started"]


# ---- the skill's Step 0 (a pin on prose, not a guard) --------------------------


def test_skill_takes_the_lock_before_enumerating() -> None:
    text = SKILL.read_text(encoding="utf-8")
    step0 = text.index("## Step 0")
    step1 = text.index("## Step 1")
    assert step0 < step1
    assert text.index("$DREAM begin") < text.index("$DREAM unprocessed")
    section0 = text[step0:step1]
    assert "exit 3" in section0.lower() or "`3`" in section0
    assert "skipped: locked by" in section0
    assert "`2`" in section0 or "exit 2" in section0.lower()
    step2 = text.index("## Step 2")
    assert "$DREAM end --reason" in text[step1:step2]
