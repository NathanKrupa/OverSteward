# ABOUTME: Tests for the correction pass's read-only worklist and its `dream.py correction worklist` CLI.
# ABOUTME: Temp stores, fake tree readers and fake issue-state callables only; nothing live is read or written.

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from oversteward.dream import correction
from oversteward.dream.consolidate import MemoryStore
from oversteward.estate_map.checkouts import CouldNotLook
from oversteward.stage_health.sources import IssueStateUnavailableError

REPO_ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 11)
OS_REPO = "NathanKrupa/OverSteward"
GS_REPO = "NathanKrupa/grantspider"
AG_REPO = "NathanKrupa/aigranthelper"


# ---- helpers ----------------------------------------------------------------


def _note(
    root: Path,
    filename: str,
    *,
    type_: str = "user",
    provenance: str | None = None,
    last_reinforced: str | None = None,
    created: str | None = None,
    description: str = "A standing order.",
    body: str = "Body.\n",
    extra: str = "",
) -> Path:
    """Write one note as raw text, so each date is exactly the YAML the test names."""
    root.mkdir(parents=True, exist_ok=True)
    lines = [f"  type: {type_}"]
    if provenance is not None:
        lines.append(f"  provenance: {provenance}")
    if last_reinforced is not None:
        lines.append(f"  last_reinforced: {last_reinforced}")
    if created is not None:
        lines.append(f"  created: {created}")
    if extra:
        lines.append(extra)
    metadata = "\n".join(lines)
    path = root / filename
    path.write_text(
        f"---\nname: {Path(filename).stem}\ndescription: {description}\nmetadata:\n{metadata}\n---\n\n{body}",
        encoding="utf-8",
    )
    return path


def _days_ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


class FakeTrees:
    """Lists a fixed map of repo -> tracked files, recording each repo listed."""

    def __init__(self, held: dict[str, set[str]] | None = None, *, canary: bool = True) -> None:
        self.held = {repo: set(paths) for repo, paths in (held or {}).items()}
        if canary:
            self.held.setdefault(correction.HOME_REPO, set()).add(correction.CANARY_PATH)
        self.calls: list[str] = []

    def files(self, repo: str, roots) -> list[str]:
        assert list(roots) == [], "the worklist lists whole trees"
        self.calls.append(repo)
        return sorted(self.held.get(repo, set()))


class BlindTrees(FakeTrees):
    """A reader that sees nothing at all, the canary included."""

    def __init__(self) -> None:
        super().__init__(canary=False)


class FailingTrees(FakeTrees):
    def files(self, repo: str, roots) -> list[str]:
        raise CouldNotLook(f"{repo}: checkout /nowhere is absent")


class FakeIssues:
    def __init__(self, states: dict[tuple[str, int], str] | None = None) -> None:
        self.states = states or {}
        self.calls: list[tuple[str, int]] = []

    def __call__(self, repo: str, number: int) -> str:
        self.calls.append((repo, number))
        return self.states.get((repo, number), "missing")


class FailingIssues(FakeIssues):
    def __call__(self, repo: str, number: int) -> str:
        raise IssueStateUnavailableError(f"{repo}#{number}: gh exited 1")


def _sources(trees=None, issues=None, repos=(correction.HOME_REPO,)) -> correction.Sources:
    return correction.Sources(
        trees=trees if trees is not None else FakeTrees(),
        repos=tuple(repos),
        issue_states=issues if issues is not None else FakeIssues(),
    )


def _worklist(root: Path, sources=None, **kwargs) -> dict:
    kwargs.setdefault("today", TODAY)
    return correction.build_worklist(MemoryStore(root), sources or _sources(), **kwargs).to_dict()


def _names(result: dict) -> list[str]:
    return [row["filename"] for row in result["worklist"]]


def _dream_cli():
    """The `scripts/dream.py` CLI, loaded by path — `scripts/` is not a package."""
    path = REPO_ROOT / "scripts" / "dream.py"
    spec = importlib.util.spec_from_file_location("dream_cli_correction_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cli(store: Path, sources: correction.Sources, *extra: str) -> int:
    argv = ["correction", "worklist", "--store", str(store), "--today", TODAY.isoformat(), *extra]
    return _dream_cli().main(argv, correction_sources=sources)


def _assert_could_not_look(capsys, code: int, reason: str) -> None:
    out, err = capsys.readouterr()
    assert code == 2
    assert reason in err
    assert "Traceback" not in err
    assert out == ""


# ---- ranking ----------------------------------------------------------------


def test_oldest_law_is_offered_first(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "a_fresh.md", last_reinforced="'2026-11-01'")
    _note(store, "z_stale.md", last_reinforced="'2026-01-01'", body="Run `scripts/gone.py` first.\n")

    result = _worklist(store, min_age_days=0, limit=1)

    assert _names(result) == ["z_stale.md"]
    assert result["counts"]["due"] == 2


def test_dates_normalise_across_yaml_forms_and_undated_ranks_first(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "a_bare.md", last_reinforced="2026-03-01")
    _note(store, "b_quoted.md", last_reinforced="'2026-02-01'")
    _note(store, "c_undated.md")

    result = _worklist(store)

    assert _names(result) == ["c_undated.md", "b_quoted.md", "a_bare.md"]
    assert result["counts"]["undated"] == 1
    assert [row["effective_date"] for row in result["worklist"]] == [None, "2026-02-01", "2026-03-01"]


def test_created_stands_in_when_last_reinforced_is_absent(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "a_reinforced.md", last_reinforced="'2026-05-01'", created="'2025-01-01'")
    _note(store, "b_created_only.md", created="'2026-06-01'")

    result = _worklist(store)

    assert _names(result) == ["a_reinforced.md", "b_created_only.md"]
    assert [row["effective_date"] for row in result["worklist"]] == ["2026-05-01", "2026-06-01"]


def test_modified_stands_in_when_neither_earlier_date_is_present(tmp_path: Path) -> None:
    """Notes dated only by `modified` rank by it, in the `T…Z` and space-offset forms the store holds."""
    store = tmp_path / "memory"
    _note(store, "a_space.md", extra="  modified: 2026-11-04 23:10:00+00:00")
    _note(store, "b_zulu.md", extra="  modified: 2026-10-01T12:00:00.123Z")
    _note(store, "c_undated.md")

    result = _worklist(store, min_age_days=0)

    assert _names(result) == ["c_undated.md", "b_zulu.md", "a_space.md"]
    assert [row["effective_date"] for row in result["worklist"]] == [None, "2026-10-01", "2026-11-04"]
    assert result["counts"]["undated"] == 1


def test_population_is_laws_and_habits_only(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "a_project_fact.md", type_="project", last_reinforced="'2025-01-01'")
    _note(
        store,
        "b_graveyard.md",
        last_reinforced="'2025-01-01'",
        extra="  superseded_by: the replacement",
    )
    _note(store, "c_law.md", last_reinforced="'2026-01-01'")
    _note(
        store,
        "d_habit.md",
        type_="project",
        last_reinforced="'2026-02-01'",
        body="Always run the gate before pushing.\n",
    )

    result = _worklist(store)

    assert _names(result) == ["c_law.md", "d_habit.md"]
    assert [row["kind"] for row in result["worklist"]] == ["law", "habit"]
    assert result["counts"]["standing"] == 2


def test_min_age_floor_is_inclusive(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "a_29.md", last_reinforced=f"'{_days_ago(29)}'")
    _note(store, "b_30.md", last_reinforced=f"'{_days_ago(30)}'")
    _note(store, "c_31.md", last_reinforced=f"'{_days_ago(31)}'")

    result = _worklist(store, min_age_days=30)

    assert _names(result) == ["c_31.md", "b_30.md"]
    assert result["counts"]["due"] == 2


# ---- evidence ----------------------------------------------------------------


def test_path_evidence_reads_tracked_and_untracked(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="Use `scripts/gone.py` or `scripts/dream.py`.\n")
    trees = FakeTrees({correction.HOME_REPO: {"scripts/dream.py"}, "grantspider": set()})

    result = _worklist(store, _sources(trees=trees, repos=(correction.HOME_REPO, "grantspider")))

    paths = {entry["path"]: entry for entry in result["worklist"][0]["references"]["paths"]}
    assert paths["scripts/gone.py"]["status"] == "untracked"
    assert paths["scripts/gone.py"]["repos"] == []
    assert paths["scripts/dream.py"]["status"] == "tracked"
    assert paths["scripts/dream.py"]["repos"] == [correction.HOME_REPO]


def test_paths_come_from_code_spans_only(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(
        store,
        "law.md",
        last_reinforced="'2026-01-01'",
        description="Read and/or write aigranthelper.com pages.",
        body="Prose names and/or aigranthelper.com and scripts/prose.py outside backticks.\n",
    )

    refs = _worklist(store)["worklist"][0]["references"]

    assert refs["paths"] == []
    assert refs["named"] == []


def test_unrooted_tokens_and_bare_spans_are_sorted_apart(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(
        store,
        "law.md",
        last_reinforced="'2026-01-01'",
        body=(
            "See `/home/natha/x.py`, `~/.claude/y.md`, `src/**/dream/correction.py`, "
            "`--severity error` and `/dream`.\n"
        ),
    )

    refs = _worklist(store)["worklist"][0]["references"]

    assert refs["paths"] == []
    assert sorted(refs["unchecked"]) == ["/home/natha/x.py", "src/**/dream/correction.py", "~/.claude/y.md"]
    assert refs["named"] == ["--severity error", "/dream"]


def test_parent_relative_paths_and_git_refs_are_unchecked(tmp_path: Path) -> None:
    """`git ls-tree` refuses a path above the repo, and a ref is no path; neither may read untracked."""
    store = tmp_path / "memory"
    _note(
        store,
        "law.md",
        last_reinforced="'2026-01-01'",
        body="`uv pip install ../grantspider`, `git diff HEAD..origin/main` and `origin/staging`.\n",
    )

    refs = _worklist(store)["worklist"][0]["references"]

    assert refs["paths"] == []
    assert refs["unchecked"] == ["../grantspider", "HEAD..origin/main", "origin/staging"]


def test_a_path_tail_resolves_to_the_tracked_path_it_ends(tmp_path: Path) -> None:
    """A note names `services/x.py` for `src/pkg/services/x.py`, in whichever repo holds it."""
    store = tmp_path / "memory"
    _note(
        store,
        "law.md",
        last_reinforced="'2026-01-01'",
        body="`services/enrichment.py`, `scripts/dev`, `ices/enrichment.py` and `services/enrich.py`.\n",
    )
    trees = FakeTrees(
        {
            correction.HOME_REPO: {"scripts/dev/new-session.sh"},
            "grantspider": {"src/grantspider/services/enrichment.py"},
        }
    )

    result = _worklist(store, _sources(trees=trees, repos=(correction.HOME_REPO, "grantspider")))

    paths = {e["path"]: (e["status"], e["repos"]) for e in result["worklist"][0]["references"]["paths"]}
    assert paths == {
        "services/enrichment.py": ("tracked", ["grantspider"]),
        "scripts/dev": ("tracked", [correction.HOME_REPO]),
        "ices/enrichment.py": ("untracked", []),
        "services/enrich.py": ("untracked", []),
    }


def test_description_and_digest_spans_are_read(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(
        store,
        "a_law.md",
        last_reinforced="'2026-01-01'",
        description="Use `scripts/a.py` first.",
        body="No spans here.\n",
        extra='  digest: "Per `OS#7`, run it"',
    )
    _note(
        store,
        "b_law.md",
        last_reinforced="'2026-02-01'",
        body="No spans here.\n",
        extra="  digest:\n  - '`scripts/listed.py`'",
    )
    issues = FakeIssues({(OS_REPO, 7): "open"})

    rows = _worklist(store, _sources(issues=issues))["worklist"]

    assert [e["path"] for e in rows[0]["references"]["paths"]] == ["scripts/a.py"]
    assert rows[0]["references"]["issues"] == [{"ref": "OS#7", "state": "open"}]
    assert rows[1]["references"]["paths"] == []


def test_tokens_naming_no_directory_are_unchecked(tmp_path: Path) -> None:
    """A bare filename or domain cannot be located, so it must not read as untracked; a URL is no path."""
    store = tmp_path / "memory"
    _note(
        store,
        "law.md",
        last_reinforced="'2026-01-01'",
        body="`_alembic_guards.py`, `aigranthelper.com`, `https://example.org/a/b.py` and `scripts/dream.py`.\n",
    )
    trees = FakeTrees({correction.HOME_REPO: {"scripts/dream.py"}})

    refs = _worklist(store, _sources(trees=trees))["worklist"][0]["references"]

    assert [entry["path"] for entry in refs["paths"]] == ["scripts/dream.py"]
    assert refs["unchecked"] == ["_alembic_guards.py", "aigranthelper.com"]
    assert refs["named"] == ["https://example.org/a/b.py"]


def test_fenced_blocks_are_not_inline_spans(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="```\nrun `scripts/fenced.py`\n```\n")

    assert _worklist(store)["worklist"][0]["references"]["paths"] == []


def test_issue_refs_read_open_closed_and_unchecked(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="Per `OS#134`, `GS#9` and `WP#3`.\n")
    issues = FakeIssues({(OS_REPO, 134): "closed", (GS_REPO, 9): "open"})

    refs = _worklist(store, _sources(issues=issues))["worklist"][0]["references"]

    assert refs["issues"] == [{"ref": "OS#134", "state": "closed"}, {"ref": "GS#9", "state": "open"}]
    assert refs["unchecked"] == ["WP#3"]
    assert sorted(issues.calls) == sorted([(GS_REPO, 9), (OS_REPO, 134)])


def test_known_issue_refs_are_read_from_prose_once_each(tmp_path: Path) -> None:
    """Prose refs of a known prefix count beside span refs; fenced text and unknown prose prefixes do not."""
    store = tmp_path / "memory"
    _note(
        store,
        "law.md",
        last_reinforced="'2026-01-01'",
        description="Settled in OS#134.",
        extra='  digest: "Per GS#9 and OS#134"',
        body="Per OS#134, GS#9, WP#3 and `AG#5`; see `OS#134` too.\n```\nsee OS#7 and `GS#8`\n```\n",
    )
    issues = FakeIssues({(OS_REPO, 134): "closed", (GS_REPO, 9): "open", (AG_REPO, 5): "open"})

    refs = _worklist(store, _sources(issues=issues))["worklist"][0]["references"]

    assert refs["issues"] == [
        {"ref": "OS#134", "state": "closed"},
        {"ref": "GS#9", "state": "open"},
        {"ref": "AG#5", "state": "open"},
    ]
    assert refs["unchecked"] == []
    assert sorted(issues.calls) == sorted([(OS_REPO, 134), (GS_REPO, 9), (AG_REPO, 5)])


def test_prose_refs_are_read_from_a_spanless_line_and_before_a_span(tmp_path: Path) -> None:
    """Each ref sits in one position only: alone on a line with no span, and only before a span."""
    store = tmp_path / "memory"
    _note(
        store,
        "law.md",
        last_reinforced="'2026-01-01'",
        description="Settled in OS#134.",
        body="GS#9 first, then `scripts/a.py`.\n",
    )
    issues = FakeIssues({(OS_REPO, 134): "closed", (GS_REPO, 9): "open"})

    refs = _worklist(store, _sources(issues=issues))["worklist"][0]["references"]

    assert refs["issues"] == [{"ref": "OS#134", "state": "closed"}, {"ref": "GS#9", "state": "open"}]


def test_references_are_read_for_offered_notes_only(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "a_offered.md", last_reinforced="'2026-01-01'", body="`OS#1` `scripts/a.py`\n")
    _note(store, "b_not_offered.md", last_reinforced="'2026-02-01'", body="`OS#2` `scripts/b.py`\n")
    trees, issues = FakeTrees(), FakeIssues()

    _worklist(store, _sources(trees=trees, issues=issues), limit=1)

    assert issues.calls == [(OS_REPO, 1)]
    assert trees.calls == [correction.HOME_REPO]


def test_row_carries_identity_fields(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    path = _note(store, "law.md", provenance="nathan-stated", last_reinforced="'2026-01-01'")

    row = _worklist(store)["worklist"][0]

    assert row["provenance"] == "nathan-stated"
    assert row["description"] == "A standing order."
    assert row["undated"] is False
    assert row["content_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


# ---- could not look (the CLI) ------------------------------------------------


def test_reader_failure_is_could_not_look(tmp_path: Path, capsys) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="`scripts/dream.py`\n")

    code = _cli(store, _sources(trees=FailingTrees()))

    _assert_could_not_look(capsys, code, "checkout /nowhere is absent")


def test_zero_due_store_is_a_measured_exit_0(tmp_path: Path, capsys) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced=f"'{_days_ago(1)}'")

    code = _cli(store, _sources())

    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out)["counts"] == {"standing": 1, "due": 0, "offered": 0, "undated": 0}


def test_blind_reader_trips_the_canary(tmp_path: Path, capsys) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'")

    code = _cli(store, _sources(trees=BlindTrees()))

    _assert_could_not_look(capsys, code, "instrument blind")


def test_home_repo_absent_from_the_trees_is_blind(tmp_path: Path, capsys) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'")

    code = _cli(store, _sources(repos=("grantspider",)))

    _assert_could_not_look(capsys, code, "instrument blind")


def test_unrecognised_issue_state_is_could_not_look(tmp_path: Path, capsys) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="`OS#5`\n")

    code = _cli(store, _sources(issues=FakeIssues({(OS_REPO, 5): ""})))

    _assert_could_not_look(capsys, code, "unrecognised issue state")


def test_issue_read_failure_is_could_not_look(tmp_path: Path, capsys) -> None:
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="`OS#5`\n")

    code = _cli(store, _sources(issues=FailingIssues()))

    _assert_could_not_look(capsys, code, "gh exited 1")


def test_a_missing_gh_is_could_not_look(tmp_path: Path, capsys, monkeypatch) -> None:
    """`gh` absent from PATH reaches the real issue-state reader and exits 2, never a crash."""
    from oversteward.board import client
    from oversteward.stage_health.sources import GithubIssueStates

    def no_gh(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "gh")

    monkeypatch.setattr(client.subprocess, "run", no_gh)
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="`OS#5`\n")

    try:
        code = _cli(store, _sources(issues=GithubIssueStates()))
    except OSError as exc:
        pytest.fail(f"a missing gh crashed the worklist: {exc!r}")

    _assert_could_not_look(capsys, code, "gh could not be run")


@pytest.mark.parametrize("make_root", ["absent", "empty"])
def test_absent_or_empty_store_is_could_not_look(tmp_path: Path, capsys, make_root: str) -> None:
    store = tmp_path / "memory"
    if make_root == "empty":
        store.mkdir()
        (store / "MEMORY.md").write_text("# index only\n", encoding="utf-8")

    code = _cli(store, _sources())

    _assert_could_not_look(capsys, code, str(store))


def test_unparseable_note_is_could_not_look(tmp_path: Path, capsys) -> None:
    store = tmp_path / "memory"
    store.mkdir()
    (store / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")

    code = _cli(store, _sources())

    _assert_could_not_look(capsys, code, "broken.md")


# ---- the registry wiring -----------------------------------------------------


def test_tree_checkouts_keep_contexts_with_a_local_path(tmp_path: Path) -> None:
    registry = {
        "contexts": [
            {"id": "oversteward", "local_path": "/somewhere/OverSteward"},
            {"id": "home-obsidian"},
            {"id": "grantspider", "local_path": "/somewhere/grantspider", "branch": "staging",
             "primary_branch": "main"},
        ]
    }

    found = correction.tree_checkouts(registry, home_root=tmp_path)

    assert sorted(found) == ["grantspider", "oversteward"]
    assert found["oversteward"].root == tmp_path
    assert found["grantspider"].ref == "origin/main"


# ---- invariant pin -----------------------------------------------------------


def _tree_bytes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_worklist_run_leaves_store_bytes_unchanged(tmp_path: Path, capsys) -> None:
    """Invariant pin: the worklist writes nothing to the store."""
    store = tmp_path / "memory"
    _note(store, "law.md", last_reinforced="'2026-01-01'", body="`scripts/gone.py` `OS#1`\n")
    _note(store, "fresh.md", last_reinforced=f"'{_days_ago(1)}'")
    before = _tree_bytes(tmp_path)

    code = _cli(store, _sources())

    capsys.readouterr()
    assert code == 0
    assert _tree_bytes(tmp_path) == before
