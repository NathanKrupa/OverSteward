# ABOUTME: Tests for `dream.py correction apply` and `correction probe`: the three verdicts, their guards,
# ABOUTME: the closing-row ledger, the conflict hold and its commit, and the run lock. Temp paths only.

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from oversteward.dream import cycle
from oversteward.dream.consolidate import REVIEW_FILENAME, MemoryStore
from oversteward.dream.correction_ledger import CorrectionLedger

from tests.dream.test_correction import TODAY, _dream_cli, _note, _sources

pytestmark = pytest.mark.usefixtures("never_the_live_lock")

TRACKED = "scripts/dream.py"
UNTRACKED = "scripts/gone.py"


# ---- helpers ----------------------------------------------------------------


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    store_repo = tmp_path / "steward-memory"
    store = store_repo / "memory"
    store.mkdir(parents=True)
    return {
        "store": store,
        "store_repo": store_repo,
        "corrections": tmp_path / "data" / "corrections.jsonl",
        "flagged": tmp_path / "data" / "flagged.jsonl",
        "lock": tmp_path / "dream_run.lock",
        "runs": tmp_path / "dream_runs.jsonl",
        "tmp": tmp_path,
    }


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _init_store_repo(p: dict[str, Path]) -> None:
    root = p["store_repo"]
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (p["store"] / "MEMORY.md").write_text("# index\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(p, filename: str, *, paths=(), issues=()) -> dict:
    """A worksheet row as `correction worklist` emits it, hashed from the note on disk."""
    return {
        "filename": filename,
        "kind": "law",
        "provenance": None,
        "effective_date": "2025-01-01",
        "undated": False,
        "description": "A standing order.",
        "content_sha256": _sha(p["store"] / filename),
        "references": {
            "paths": [
                {"path": path, "status": status, "repos": ["oversteward"] if status == "tracked" else []}
                for path, status in paths
            ],
            "issues": [{"ref": ref, "state": state} for ref, state in issues],
            "unchecked": [],
            "named": [],
        },
    }


def _write_json(path: Path, payload: object) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _lock_args(p) -> list[str]:
    return ["--lock", str(p["lock"]), "--runs", str(p["runs"])]


def _apply_argv(p, rows: list[dict], verdicts: list[dict]) -> list[str]:
    return [
        "correction", "apply",
        "--worksheet", _write_json(p["tmp"] / "worksheet.json", {"counts": {}, "worklist": rows}),
        "--verdicts", _write_json(p["tmp"] / "verdicts.json", verdicts),
        "--store", str(p["store"]),
        "--store-repo", str(p["store_repo"]),
        "--flagged", str(p["flagged"]),
        "--corrections-ledger", str(p["corrections"]),
        *_lock_args(p),
    ]


def _apply(p, rows, verdicts, cli=None) -> int:
    return (cli or _dream_cli()).main(_apply_argv(p, rows, verdicts))


def _ledger(p) -> list[dict]:
    if not p["corrections"].exists():
        return []
    return [json.loads(line) for line in p["corrections"].read_text().splitlines() if line.strip()]


def _verdict_rows(p) -> list[dict]:
    return [r for r in _ledger(p) if r["event"] == "verdict"]


def _closed(p) -> dict:
    closed = [r for r in _ledger(p) if r["event"] == "closed"]
    assert len(closed) == 1, closed
    return closed[0]


def _runs(p) -> list[dict]:
    if not p["runs"].exists():
        return []
    return [json.loads(line) for line in p["runs"].read_text().splitlines() if line.strip()]


def _assert_refused(capsys, code: int, filename: str, why: str) -> None:
    out, err = capsys.readouterr()
    assert code == 1
    assert f"refused {filename}: " in err and why in err, err
    assert "Traceback" not in err
    refused = {r["filename"]: r["why"] for r in json.loads(out)["refused"]}
    assert why in refused[filename]


# ---- confirmed needs a tracked basis -------------------------------------------


@pytest.mark.parametrize(
    ("basis", "why"),
    [([], "needs a basis"), ([UNTRACKED], f"{UNTRACKED} is not a tracked path")],
    ids=["no-basis", "untracked-basis"],
)
def test_confirmed_without_a_tracked_basis_is_refused(paths, capsys, basis, why) -> None:
    _note(paths["store"], "a_bad.md")
    _note(paths["store"], "b_good.md")
    rows = [
        _row(paths, "a_bad.md", paths=[(TRACKED, "tracked"), (UNTRACKED, "untracked")]),
        _row(paths, "b_good.md", paths=[(TRACKED, "tracked")]),
    ]
    verdicts = [
        {"filename": "a_bad.md", "verdict": "confirmed", "basis": basis, "reason": "still true"},
        {"filename": "b_good.md", "verdict": "confirmed", "basis": [TRACKED]},
    ]

    code = _apply(paths, rows, verdicts)

    _assert_refused(capsys, code, "a_bad.md", why)
    assert [(r["filename"], r["verdict"], r["basis"]) for r in _verdict_rows(paths)] == [
        ("b_good.md", "confirmed", [TRACKED])
    ]
    closed = _closed(paths)
    assert (closed["checked"], closed["confirmed"]) == (1, 1)
    assert closed["skipped"]["refused"] == 1


def test_a_basis_the_row_never_named_is_refused(paths, capsys) -> None:
    """A path the worksheet did not report is no basis, however real it is."""
    _note(paths["store"], "a.md")
    rows = [_row(paths, "a.md", paths=[(TRACKED, "tracked")])]
    verdicts = [{"filename": "a.md", "verdict": "confirmed", "basis": ["src/elsewhere.py"]}]

    code = _apply(paths, rows, verdicts)

    _assert_refused(capsys, code, "a.md", "src/elsewhere.py is not a tracked path")
    assert _verdict_rows(paths) == []


@pytest.mark.parametrize(
    "evidence",
    [{"paths": [(TRACKED, "tracked"), (UNTRACKED, "untracked")]},
     {"paths": [(TRACKED, "tracked")], "issues": [("OS#9", "missing")]}],
    ids=["untracked-path", "missing-issue"],
)
def test_confirmed_over_contrary_evidence_needs_a_reason(paths, capsys, evidence) -> None:
    _note(paths["store"], "a.md")
    _note(paths["store"], "b.md")
    rows = [_row(paths, "a.md", **evidence), _row(paths, "b.md", **evidence)]
    verdicts = [
        {"filename": "a.md", "verdict": "confirmed", "basis": [TRACKED]},
        {"filename": "b.md", "verdict": "confirmed", "basis": [TRACKED], "reason": "renamed; rule holds"},
    ]

    code = _apply(paths, rows, verdicts)

    _assert_refused(capsys, code, "a.md", "needs a reason")
    assert [(r["filename"], r["reason"]) for r in _verdict_rows(paths)] == [
        ("b.md", "renamed; rule holds")
    ]


# ---- unverified needs its search -------------------------------------------------


def test_unverified_needs_searched_and_is_never_counted_confirmed(paths, capsys) -> None:
    _note(paths["store"], "a.md")
    _note(paths["store"], "b.md")
    rows = [_row(paths, "a.md"), _row(paths, "b.md")]
    verdicts = [
        {"filename": "a.md", "verdict": "unverified"},
        {"filename": "b.md", "verdict": "unverified", "searched": ["MEMORY_FULL.md: 'gh pr merge'"]},
    ]

    code = _apply(paths, rows, verdicts)

    _assert_refused(capsys, code, "a.md", "needs searched")
    assert [(r["filename"], r["verdict"], r["searched"]) for r in _verdict_rows(paths)] == [
        ("b.md", "unverified", ["MEMORY_FULL.md: 'gh pr merge'"])
    ]
    closed = _closed(paths)
    assert (closed["unverified"], closed["confirmed"], closed["checked"]) == (1, 0, 1)


# ---- vocabulary and identity -------------------------------------------------------


@pytest.mark.parametrize("verdict", ["corrected", "superseded", "CONFIRMED"])
def test_verdicts_outside_this_vocabulary_are_refused(paths, capsys, verdict) -> None:
    _note(paths["store"], "a.md")
    rows = [_row(paths, "a.md", paths=[(TRACKED, "tracked")])]

    code = _apply(paths, rows, [{"filename": "a.md", "verdict": verdict, "basis": [TRACKED]}])

    _assert_refused(capsys, code, "a.md", f"unknown verdict {verdict!r}")
    assert _verdict_rows(paths) == []


def test_a_filename_off_the_worksheet_is_refused(paths, capsys) -> None:
    _note(paths["store"], "a.md")
    _note(paths["store"], "b.md")
    rows = [_row(paths, "a.md")]

    code = _apply(paths, rows, [{"filename": "b.md", "verdict": "unverified", "searched": ["x"]}])

    _assert_refused(capsys, code, "b.md", "not on the worksheet")
    closed = _closed(paths)
    assert closed["skipped"] == {"stale": 0, "refused": 1, "unjudged": 1}


def test_a_second_verdict_for_one_note_is_refused(paths, capsys) -> None:
    _note(paths["store"], "a.md")
    rows = [_row(paths, "a.md")]
    verdicts = [
        {"filename": "a.md", "verdict": "unverified", "searched": ["x"]},
        {"filename": "a.md", "verdict": "unverified", "searched": ["y"]},
    ]

    code = _apply(paths, rows, verdicts)

    _assert_refused(capsys, code, "a.md", "duplicate verdict")
    assert [r["searched"] for r in _verdict_rows(paths)] == [["x"]]


# ---- stale ---------------------------------------------------------------------


def test_a_note_changed_since_the_worksheet_is_stale(paths, capsys, monkeypatch) -> None:
    _note(paths["store"], "a_changed.md")
    _note(paths["store"], "b_same.md")
    rows = [_row(paths, "a_changed.md"), _row(paths, "b_same.md", paths=[(TRACKED, "tracked")])]
    _note(paths["store"], "a_changed.md", body="Edited after the worksheet.\n")
    merge = mock.MagicMock(name="merge")
    monkeypatch.setattr(cycle.FlaggedStore, "merge", merge)
    verdicts = [
        {"filename": "a_changed.md", "verdict": "conflict", "reason": "r", "proposal": "p"},
        {"filename": "b_same.md", "verdict": "confirmed", "basis": [TRACKED]},
    ]

    code = _apply(paths, rows, verdicts)

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["stale"] == ["a_changed.md"]
    merge.assert_not_called()
    assert [r["filename"] for r in _verdict_rows(paths)] == ["b_same.md"]
    assert _closed(paths)["skipped"]["stale"] == 1


# ---- conflict ------------------------------------------------------------------


def _conflict(filename: str, reason: str, proposal: str) -> dict:
    return {"filename": filename, "verdict": "conflict", "reason": reason, "proposal": proposal}


def test_a_conflict_holds_once_surfaces_and_commits_the_review_surface_only(paths, capsys) -> None:
    _init_store_repo(paths)
    # A note with no metadata.type: the hold must still survive open_items().
    note = paths["store"] / "a_law.md"
    note.write_text(
        "---\nname: a_law\ndescription: Merge with --merge only.\nmetadata:\n"
        "  provenance: nathan-approved\n  last_reinforced: '2025-01-01'\n---\n\nBody.\n",
        encoding="utf-8",
    )
    _git(paths["store_repo"], "add", "-A")
    _git(paths["store_repo"], "commit", "-q", "-m", "note")
    # Pre-existing uncommitted work the correction commit must not sweep in.
    (paths["store"] / "MEMORY.md").write_text("# index, edited by hand\n", encoding="utf-8")
    _note(paths["store"], "untracked_note.md")
    note_before = note.read_bytes()
    head_before = _git(paths["store_repo"], "rev-parse", "HEAD")
    rows = [_row(paths, "a_law.md")]

    first = _apply(paths, rows, [_conflict("a_law.md", "the merge flag changed", "Use --rebase.")])
    capsys.readouterr()
    second = _apply(paths, rows, [_conflict("a_law.md", "different words", "Use --squash.")])
    capsys.readouterr()

    assert (first, second) == (0, 0)
    assert note.read_bytes() == note_before
    held = cycle.FlaggedStore(paths["flagged"]).open_items()
    assert len(held) == 1
    assert held[0].candidate.description == "Merge with --merge only."
    assert held[0].nearest.filename == "a_law.md"
    assert held[0].reason == "CONFLICT: different words"
    surface = (paths["store"] / REVIEW_FILENAME).read_text(encoding="utf-8")
    assert "- **reason:** CONFLICT: different words" in surface
    assert "Use --squash." in surface
    assert surface.count("## Merge with --merge only.") == 1
    log = _git(paths["store_repo"], "log", "--format=%s", "--name-only", f"{head_before.strip()}..HEAD")
    assert [line for line in log.splitlines() if line and not line.startswith("dream:")] == [
        f"memory/{REVIEW_FILENAME}",
        f"memory/{REVIEW_FILENAME}",
    ]
    assert "[skip ci]" in log
    status = _git(paths["store_repo"], "status", "--porcelain")
    assert " M memory/MEMORY.md" in status
    assert "?? memory/untracked_note.md" in status
    assert [r["verdict"] for r in _verdict_rows(paths)] == ["conflict", "conflict"]


def test_a_conflict_keeps_the_open_set_it_found(paths, capsys) -> None:
    _init_store_repo(paths)
    _note(paths["store"], "a.md")
    prior = {
        "candidate": {
            "type": "user", "description": "An earlier hold.", "body": "b",
            "provenance": "nathan-stated", "confidence": "high", "is_procedural": False,
        },
        "reason": "contradicts a nathan-stated memory — surfaced, never auto-written",
        "similarity": 0.9,
        "nearest_filename": "z.md",
    }
    cycle.FlaggedStore(paths["flagged"]).merge([cycle.flagged_from_dict(prior)])

    assert _apply(paths, [_row(paths, "a.md")], [_conflict("a.md", "r", "p")]) == 0

    surface = (paths["store"] / REVIEW_FILENAME).read_text(encoding="utf-8")
    assert "## An earlier hold." in surface and "## A standing order." in surface
    assert len(cycle.FlaggedStore(paths["flagged"]).open_items()) == 2


def test_a_conflict_needs_a_reason(paths, capsys, monkeypatch) -> None:
    _note(paths["store"], "a.md")
    merge = mock.MagicMock(name="merge")
    monkeypatch.setattr(cycle.FlaggedStore, "merge", merge)

    code = _apply(paths, [_row(paths, "a.md")], [{"filename": "a.md", "verdict": "conflict"}])

    _assert_refused(capsys, code, "a.md", "needs a reason")
    merge.assert_not_called()


# ---- every run closes ------------------------------------------------------------


def test_an_empty_worksheet_still_opens_and_closes(paths, capsys) -> None:
    code = _apply(paths, [], [])

    assert code == 0
    assert [r["event"] for r in _ledger(paths)] == ["opened", "closed"]
    closed = _closed(paths)
    assert closed["checked"] == 0
    assert closed["error"] is None
    assert closed["skipped"] == {"stale": 0, "refused": 0, "unjudged": 0}
    assert (closed["corrected"], closed["superseded"]) == (0, 0)


def test_aborted_closes_the_run_with_its_reason(paths, capsys) -> None:
    argv = [
        "correction", "apply", "--aborted", "worklist exited 2: instrument blind",
        "--corrections-ledger", str(paths["corrections"]), *_lock_args(paths),
    ]

    code = _dream_cli().main(argv)

    assert code == 0
    rows = _ledger(paths)
    assert [r["event"] for r in rows] == ["opened", "closed"]
    assert rows[1]["aborted"] == "worklist exited 2: instrument blind"
    assert rows[1]["checked"] == 0
    assert rows[0]["run"] == rows[1]["run"]


def test_verdict_rows_and_the_closing_row_are_one_append(paths, capsys, monkeypatch) -> None:
    """A closing row never lands without the verdict rows that start its clock."""
    _note(paths["store"], "a.md")
    _note(paths["store"], "b.md")
    calls: list[list[str]] = []
    real_append = CorrectionLedger.append

    def spy(self, rows):
        calls.append([row["event"] for row in rows])
        return real_append(self, rows)

    monkeypatch.setattr(CorrectionLedger, "append", spy)
    rows = [_row(paths, "a.md"), _row(paths, "b.md")]
    verdicts = [
        {"filename": "a.md", "verdict": "unverified", "searched": ["x"]},
        {"filename": "b.md", "verdict": "unverified", "searched": ["y"]},
    ]

    assert _apply(paths, rows, verdicts) == 0

    assert calls == [["opened"], ["verdict", "verdict", "closed"]]


def test_a_failed_commit_still_closes_the_run_and_releases(paths, capsys, monkeypatch) -> None:
    _note(paths["store"], "a.md")
    cli = _dream_cli()
    failure = subprocess.CalledProcessError(128, ["git", "commit"], stderr="fatal: no repo")
    monkeypatch.setattr(cli, "commit_store", mock.MagicMock(side_effect=failure))

    code = _apply(paths, [_row(paths, "a.md")], [_conflict("a.md", "r", "p")], cli=cli)

    out, err = capsys.readouterr()
    assert code == 1
    assert "correction commit failed" in err
    assert "Traceback" not in err
    assert out == ""
    closed = _closed(paths)
    assert "CalledProcessError" in closed["error"]
    assert [r["event"] for r in _runs(paths)] == ["started", "ended"]
    assert _runs(paths)[1]["reason"] == "correction"


# ---- the lock --------------------------------------------------------------------


def test_a_live_foreign_holder_skips_the_pass_and_writes_no_row(paths, foreign, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    engine = mock.MagicMock(name="apply_corrections")
    monkeypatch.setattr(cli.correction_apply, "apply_corrections", engine)
    paths["corrections"].parent.mkdir(parents=True)
    paths["corrections"].write_text('{"event": "opened", "run": "earlier", "at": "2026-11-01T00:00:00+00:00"}\n')
    ledger_before = paths["corrections"].read_bytes()
    paths["lock"].write_text(json.dumps(foreign))
    _note(paths["store"], "a.md")

    code = _apply(paths, [_row(paths, "a.md")], [], cli=cli)

    err = capsys.readouterr().err
    assert code == 3
    assert f"skipped — locked by pid {foreign['pid']}" in err
    assert "Traceback" not in err
    engine.assert_not_called()
    assert paths["corrections"].read_bytes() == ledger_before


def test_aborted_under_a_foreign_holder_writes_no_row(paths, foreign, capsys) -> None:
    paths["lock"].write_text(json.dumps(foreign))
    argv = [
        "correction", "apply", "--aborted", "x",
        "--corrections-ledger", str(paths["corrections"]), *_lock_args(paths),
    ]

    assert _dream_cli().main(argv) == 3
    assert not paths["corrections"].exists()


def test_a_lock_already_ours_is_not_released(paths, capsys) -> None:
    cli = _dream_cli()
    assert cli.main(["cycle", "begin", *_lock_args(paths)]) == 0
    held = paths["lock"].read_bytes()

    assert _apply(paths, [], [], cli=cli) == 0

    assert paths["lock"].read_bytes() == held
    assert [r["event"] for r in _runs(paths)] == ["started"]


def test_a_lock_taken_here_is_released_with_reason_correction(paths, capsys) -> None:
    assert _apply(paths, [], []) == 0

    assert paths["lock"].read_bytes() == b""
    rows = _runs(paths)
    assert [r["event"] for r in rows] == ["started", "ended"]
    assert rows[1]["reason"] == "correction"


def test_a_lock_taken_here_is_released_when_the_engine_raises(paths, capsys, monkeypatch) -> None:
    cli = _dream_cli()
    monkeypatch.setattr(
        cli.correction_apply, "apply_corrections", mock.MagicMock(side_effect=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        _apply(paths, [], [], cli=cli)

    assert paths["lock"].read_bytes() == b""
    assert [(r["event"], r.get("reason")) for r in _runs(paths)] == [
        ("started", None),
        ("ended", "correction"),
    ]


# ---- could not look ----------------------------------------------------------------


@pytest.mark.parametrize(
    "worksheet",
    [
        {"counts": {}},
        {"worklist": [{"filename": "a.md"}]},
        ["not", "an", "object"],
        {"worklist": [{"filename": "../outside.md", "content_sha256": "0",
                       "references": {"paths": [], "issues": []}}]},
    ],
    ids=["no-worklist", "row-without-sha", "not-an-object", "filename-with-a-path"],
)
def test_an_unreadable_worksheet_exits_2_before_any_row(paths, capsys, worksheet) -> None:
    argv = _apply_argv(paths, [], [])
    argv[argv.index("--worksheet") + 1] = _write_json(paths["tmp"] / "bad.json", worksheet)

    code = _dream_cli().main(argv)

    out, err = capsys.readouterr()
    assert code == 2
    assert "correction apply could not look" in err
    assert "Traceback" not in err
    assert out == ""
    assert not paths["corrections"].exists()


def test_an_unreadable_ledger_stops_the_worklist(paths, capsys) -> None:
    _note(paths["store"], "a.md")
    paths["corrections"].parent.mkdir(parents=True)
    paths["corrections"].write_text("{broken\n")
    argv = [
        "correction", "worklist", "--store", str(paths["store"]), "--today", TODAY.isoformat(),
        "--corrections-ledger", str(paths["corrections"]),
    ]

    code = _dream_cli().main(argv, correction_sources=_sources())

    out, err = capsys.readouterr()
    assert code == 2
    assert "corrections.jsonl:1" in err
    assert "Traceback" not in err
    assert out == ""


# ---- probe -----------------------------------------------------------------------


def test_probe_reports_the_ledger(paths, capsys) -> None:
    argv = ["correction", "probe", "--corrections-ledger", str(paths["corrections"]),
            "--today", TODAY.isoformat()]

    assert _dream_cli().main(argv) == 0
    assert json.loads(capsys.readouterr().out)["never_run"] is True


def test_probe_of_a_corrupt_ledger_exits_2_by_name(paths, capsys) -> None:
    paths["corrections"].parent.mkdir(parents=True)
    paths["corrections"].write_text("{broken\n")
    argv = ["correction", "probe", "--corrections-ledger", str(paths["corrections"])]

    code = _dream_cli().main(argv)

    out, err = capsys.readouterr()
    assert code == 2
    assert "corrections.jsonl:1" in err
    assert "Traceback" not in err
    assert out == ""


# ---- the pass end to end, and the store it never edits ----------------------------------


def _store_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_confirmed_and_unverified_leave_the_store_and_its_log_unchanged(paths, capsys) -> None:
    """Invariant pin: those two verdicts write the ledger only."""
    _init_store_repo(paths)
    _note(paths["store"], "a.md")
    _note(paths["store"], "b.md")
    _git(paths["store_repo"], "add", "-A")
    _git(paths["store_repo"], "commit", "-q", "-m", "notes")
    before = (_store_digest(paths["store_repo"]), _git(paths["store_repo"], "log", "--format=%H"))
    rows = [_row(paths, "a.md", paths=[(TRACKED, "tracked")]), _row(paths, "b.md")]
    verdicts = [
        {"filename": "a.md", "verdict": "confirmed", "basis": [TRACKED]},
        {"filename": "b.md", "verdict": "unverified", "searched": ["x"]},
    ]

    assert _apply(paths, rows, verdicts) == 0

    after = (_store_digest(paths["store_repo"]), _git(paths["store_repo"], "log", "--format=%H"))
    assert after == before
    assert not paths["flagged"].exists()


def test_a_checked_note_leaves_the_next_worklist(paths, capsys) -> None:
    _note(paths["store"], "a.md", last_reinforced="'2025-01-01'")
    _note(paths["store"], "b.md", last_reinforced="'2025-01-02'")
    rows = [_row(paths, "a.md")]
    assert _apply(paths, rows, [{"filename": "a.md", "verdict": "unverified", "searched": ["x"]}]) == 0
    capsys.readouterr()
    argv = [
        "correction", "worklist", "--store", str(paths["store"]),
        "--corrections-ledger", str(paths["corrections"]),
    ]

    assert _dream_cli().main(argv, correction_sources=_sources()) == 0

    offered = [row["filename"] for row in json.loads(capsys.readouterr().out)["worklist"]]
    assert offered == ["b.md"]


# ---- the skill's Step 7 and the review surface (pins on prose, not guards) ----------------

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "dream" / "SKILL.md"
BOUNDED_SEARCH = (
    "1. grep the store's MEMORY_FULL.md for two or three of the note's distinctive terms; "
    "read only later notes;",
    "2. `git grep -n` up to three `named` terms in the repo the note's `scope` names;",
    "3. transcripts only as escalation before a conflict/corrected/superseded verdict: `grep -l` "
    "the term in transcripts dated after the note, at most three files, matching lines only. "
    "Never to reach `confirmed`.",
)


def test_skill_step_7_runs_every_run_with_the_bounded_search() -> None:
    text = SKILL.read_text(encoding="utf-8")
    step7 = text.index("## Step 7")
    section = text[step7 : text.index("## Draining")]
    assert text.index("## Step 6") < step7
    for line in BOUNDED_SEARCH:
        assert line in section
    assert section.index("$CORRECTION probe") < section.index("$CORRECTION worklist")
    assert section.index("$CORRECTION worklist") < section.index("$CORRECTION apply --worksheet")
    assert '$CORRECTION apply --aborted' in section
    assert "--limit" not in section.replace("--limit 10 --min-age-days 30", "")
    noop = text[text.index("## Step 1") : text.index("## Step 2")]
    assert "Step 7" in noop


def test_review_surface_header_names_both_kinds_of_hold(tmp_path: Path) -> None:
    header = MemoryStore(tmp_path).write_review_surface([]).read_text(encoding="utf-8")

    assert "`nathan-stated`" in header and "`CONFLICT:`" in header
    assert "— each\ncontradicts" not in header
