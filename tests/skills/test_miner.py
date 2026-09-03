# ABOUTME: Tests for the skill miner — repeated Bash sequences across session transcripts become SKILL.md drafts.
# ABOUTME: Builds fake transcripts under tmp_path; never reads the live ~/.claude/projects dir.

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from oversteward.skills.miner import (
    SkillCandidate,
    covering_skills,
    extract_runs,
    mine_candidates,
    mine_projects_root,
    render_draft,
    signature_of,
    write_drafts,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "skill_miner.py"


def _cli_env() -> dict[str, str]:
    """The CLI subprocess must import the tree under test, not whichever checkout
    the shared venv's editable .pth names — else a worktree's CLI tests measure master."""
    return {**os.environ, "PYTHONPATH": str(SCRIPT.parents[1] / "src")}


# ---- record builders -----------------------------------------------------------


def _assistant_bash(command: str, description: str = "") -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_x",
                    "name": "Bash",
                    "input": {"command": command, "description": description},
                }
            ],
        },
        "timestamp": "2026-09-02T10:00:00.000Z",
    }


def _tool_result() -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
    }


def _user_text(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _session(commands: list[str]) -> list[dict]:
    records: list[dict] = [_user_text("go")]
    for command in commands:
        records.append(_assistant_bash(command, f"run {command.split()[0]}"))
        records.append(_tool_result())
    return records


def _write_session(project_dir: Path, session_id: str, records: list[dict]) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    with (project_dir / f"{session_id}.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


SWEEP = [
    ".venv/bin/python scripts/sentry_triage.py sweep",
    ".venv/bin/python scripts/service_liveness.py",
    ".venv/bin/python scripts/operator_steps.py list",
]


# ---- signatures ------------------------------------------------------------------


def test_signature_python_script_keeps_basename_and_subcommand() -> None:
    assert signature_of(".venv/bin/python scripts/sentry_triage.py sweep") == "sentry_triage.py sweep"


def test_signature_uv_run_recurses_into_target() -> None:
    assert signature_of("uv run pytest -q tests/") == "pytest"


def test_signature_git_and_gh_keep_subcommands() -> None:
    assert signature_of("git status --short") == "git status"
    assert signature_of("gh pr view 443 --json state") == "gh pr view"


def test_signature_drops_env_prefix_cd_and_filters() -> None:
    cmd = "cd /home/x && PYTHONPATH=/x/src .venv/bin/python scripts/foo.py run | head -20"
    assert signature_of(cmd) == "foo.py run"


def test_signature_of_pure_noise_is_empty() -> None:
    assert signature_of("echo hi; cd /tmp") == ""
    assert signature_of("grep -rn foo src | sed 's/a/b/'") == ""


def test_signature_unwraps_timeout_nohup_and_trailing_ampersand() -> None:
    assert signature_of("timeout 600 .venv/bin/python scripts/x.py run") == "x.py run"
    assert signature_of("timeout -k 5 10m uv run pytest") == "pytest"
    assert signature_of("nohup railway up --detach &") == "railway up"


def test_signature_does_not_split_inside_quotes() -> None:
    assert signature_of('python -c "import x; import y\nprint(x.y())" && git push') == "git push"
    assert signature_of("git commit -m 'a; b | c' && git push") == "git commit ; git push"


def test_signature_inline_python_snippet_is_not_a_step() -> None:
    assert signature_of(".venv/bin/python -c 'print(1)'") == ""
    assert signature_of("python3 -m pytest") == ""


def test_signature_stops_at_heredoc_body() -> None:
    cmd = ".venv/bin/python scripts/a.py <<'EOF'\ngit status\nrailway up\nEOF"
    assert signature_of(cmd) == "a.py"


def test_signature_drops_shell_keywords_and_leaked_fragments() -> None:
    assert signature_of("for s in a b; do git fetch $s; done") == "git fetch"
    assert signature_of('print(EXTRACTION_PROMPT)"') == ""


def test_signature_collapses_repeated_segments_within_one_command() -> None:
    cmd = "grantspider db scratch --sql a; grantspider db scratch --sql b; git status"
    assert signature_of(cmd) == "grantspider db scratch ; git status"


def test_signature_keeps_subcommands_of_any_cli_but_not_plain_utilities() -> None:
    assert signature_of("grantspider db scratch --sql 'select 1'") == "grantspider db scratch"
    assert signature_of("ruff check src") == "ruff check"
    assert signature_of("mkdir foo") == "mkdir"
    assert signature_of("rm -rf build") == "rm"


# ---- runs ------------------------------------------------------------------------


def test_extract_runs_splits_on_user_text_not_tool_results() -> None:
    records = _session(["git status", "git diff"]) + _session(["pytest -q"])
    runs = extract_runs(records, session_id="s1", repo="r")
    assert [[call.signature for call in run] for run in runs] == [
        ["git status", "git diff"],
        ["pytest"],
    ]
    assert runs[0][0].command == "git status"
    assert runs[0][0].description == "run git"


def test_extract_runs_ignores_non_bash_tools() -> None:
    records = _session(["git status"])
    other = _assistant_bash("git diff", "not a shell call")
    other["message"]["content"][0]["name"] = "Other"
    records.insert(1, other)
    runs = extract_runs(records, session_id="s1", repo="r")
    assert [[c.signature for c in run] for run in runs] == [["git status"]]


def test_extract_runs_collapses_consecutive_repeats_of_one_signature() -> None:
    records = _session(["gh pr view 1 --json state", "gh pr view 1 --json state", "gh pr view 1", "git push"])
    runs = extract_runs(records, session_id="s1", repo="r")
    assert [[c.signature for c in run] for run in runs] == [["gh pr view", "git push"]]


def test_extract_runs_drops_noise_only_commands() -> None:
    records = _session(["git status", "grep -rn foo src", "git diff"])
    runs = extract_runs(records, session_id="s1", repo="r")
    assert [[c.signature for c in run] for run in runs] == [["git status", "git diff"]]


# ---- mining ----------------------------------------------------------------------


def _runs_for(sessions: dict[str, list[list[str]]]):
    """sessions: session_id → list of runs (each a list of commands)."""
    out = []
    for session_id, runs in sessions.items():
        records: list[dict] = []
        for run in runs:
            records.extend(_session(run))
        out.extend(extract_runs(records, session_id=session_id, repo="r"))
    return out


def test_mine_counts_distinct_sessions_not_occurrences() -> None:
    runs = _runs_for({"a": [SWEEP, SWEEP, SWEEP], "b": [SWEEP]})
    found = mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)
    assert len(found) == 1
    assert found[0].sessions == ("a", "b")
    assert found[0].signatures == (
        "sentry_triage.py sweep",
        "service_liveness.py",
        "operator_steps.py list",
    )


def test_mine_respects_min_sessions() -> None:
    runs = _runs_for({"a": [SWEEP], "b": [SWEEP]})
    assert mine_candidates(runs, min_sessions=3, min_len=2, max_len=5) == []


def test_mine_drops_subsumed_shorter_sequences() -> None:
    runs = _runs_for({"a": [SWEEP], "b": [SWEEP], "c": [SWEEP]})
    found = mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)
    lengths = sorted(len(c.signatures) for c in found)
    assert lengths == [3], [c.signatures for c in found]


def test_mine_keeps_shorter_sequence_with_wider_support() -> None:
    prefix = SWEEP[:2]
    runs = _runs_for({"a": [SWEEP], "b": [SWEEP], "c": [prefix], "d": [prefix]})
    found = mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)
    by_len = {len(c.signatures): c for c in found}
    assert set(by_len) == {2, 3}
    assert by_len[2].sessions == ("a", "b", "c", "d")
    assert by_len[3].sessions == ("a", "b")


def test_mine_ranks_by_support_then_length() -> None:
    other = ["git fetch origin", "git merge --ff-only origin/master"]
    runs = _runs_for({"a": [SWEEP, other], "b": [SWEEP, other], "c": [other]})
    found = mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)
    assert [len(c.sessions) for c in found] == [3, 2]


def test_candidate_examples_take_the_most_common_concrete_command() -> None:
    runs = _runs_for(
        {
            "a": [["git status --short", "git diff"]],
            "b": [["git status --short", "git diff"]],
            "c": [["git status", "git diff"]],
        }
    )
    found = mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)
    assert found[0].examples[0].command == "git status --short"
    assert found[0].examples[0].description == "run git"


SECRET_CMD = 'PGPASSWORD=hunter2xyz psql "postgresql://owner:npg_S3cr3tPw@ep-fake.neon.tech/db" -c "select 1"'


def test_candidate_examples_skip_commands_that_match_a_credential_pattern() -> None:
    runs = _runs_for(
        {
            "a": [[SECRET_CMD, "git status"]],
            "b": [[SECRET_CMD, "git status"]],
            "c": [["psql -c 'select 1'", "git status"]],
        }
    )
    found = mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)
    step = found[0].examples[0]
    assert step.command == "psql -c 'select 1'"
    assert step.withheld is False


def test_candidate_step_is_withheld_when_every_form_carries_a_secret() -> None:
    runs = _runs_for({"a": [[SECRET_CMD, "git status"]], "b": [[SECRET_CMD, "git status"]]})
    found = mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)
    step = found[0].examples[0]
    assert step.withheld is True
    assert step.command == ""
    text = render_draft(found[0])
    assert "withheld" in text
    assert "hunter2" not in text
    assert "npg_S3cr3tPw" not in text
    assert "git status" in text


# ---- coverage by existing skills -------------------------------------------------


def _candidate(*sigs: str) -> SkillCandidate:
    runs = _runs_for({"a": [list(sigs)], "b": [list(sigs)]})
    return mine_candidates(runs, min_sessions=2, min_len=2, max_len=5)[0]


def test_covering_skills_names_skill_mentioning_every_step(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    (skills / "sweeps").mkdir(parents=True)
    (skills / "sweeps" / "SKILL.md").write_text(
        "---\nname: sweeps\n---\nRun sentry_triage.py sweep then service_liveness.py\n"
    )
    (skills / "unrelated").mkdir()
    (skills / "unrelated" / "SKILL.md").write_text("---\nname: unrelated\n---\ngit status only\n")
    candidate = _candidate(SWEEP[0], SWEEP[1])
    assert covering_skills(candidate, [skills]) == ("sweeps",)


def test_covering_skills_requires_all_steps(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    (skills / "partial").mkdir(parents=True)
    (skills / "partial" / "SKILL.md").write_text("---\nname: partial\n---\nsentry_triage.py sweep\n")
    candidate = _candidate(SWEEP[0], SWEEP[1])
    assert covering_skills(candidate, [skills]) == ()


# ---- rendering and writing -------------------------------------------------------


def test_render_draft_carries_steps_provenance_and_draft_marker() -> None:
    candidate = _candidate(SWEEP[0], SWEEP[1])
    text = render_draft(candidate, covered_by=("sweeps",))
    assert text.startswith("---\nname: ")
    assert "DRAFT" in text
    assert ".venv/bin/python scripts/sentry_triage.py sweep" in text
    assert ".venv/bin/python scripts/service_liveness.py" in text
    assert "sessions: 2" in text
    assert "sweeps" in text


def test_write_drafts_creates_one_dir_per_candidate_and_an_index(tmp_path: Path) -> None:
    a = _candidate(SWEEP[0], SWEEP[1])
    b = _candidate("git fetch origin", "git merge --ff-only origin/master")
    out = tmp_path / "drafts"
    paths = write_drafts([a, b], out, skills_dirs=[])
    assert len(paths) == 2
    assert all(p.name == "SKILL.md" and p.parent.parent == out for p in paths)
    assert len({p.parent.name for p in paths}) == 2
    index = (out / "INDEX.md").read_text()
    assert paths[0].parent.name in index
    assert paths[1].parent.name in index


def test_write_drafts_slugs_do_not_collide(tmp_path: Path) -> None:
    a = _candidate("git status", "git diff")
    b = _candidate("git status", "git diff --cached")
    paths = write_drafts([a, b], tmp_path / "d", skills_dirs=[])
    assert paths[0].parent != paths[1].parent


# ---- end to end over a projects root --------------------------------------------


def _projects_root(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    os_dir = root / "-home-natha-OverSteward"
    gs_dir = root / "-home-natha-grantspider"
    _write_session(os_dir, "s1", _session(SWEEP))
    _write_session(os_dir, "s2", _session(SWEEP))
    _write_session(gs_dir, "s3", _session(SWEEP))
    return root


def test_mine_projects_root_filters_by_repo(tmp_path: Path) -> None:
    root = _projects_root(tmp_path)
    result = mine_projects_root(root, repo=None, min_sessions=2, min_len=2, max_len=5)
    assert result.sessions_scanned == 3
    assert result.candidates[0].sessions == ("s1", "s2", "s3")
    only_gs = mine_projects_root(root, repo="grantspider", min_sessions=1, min_len=2, max_len=5)
    assert only_gs.sessions_scanned == 1
    assert only_gs.candidates[0].sessions == ("s3",)


def test_mine_projects_root_counts_undecodable_transcript_as_unreadable(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "-home-natha-OverSteward"
    project.mkdir(parents=True)
    (project / "bad.jsonl").write_bytes(b'\xff\xfe{"a":1}\n')
    _write_session(project, "good", _session(SWEEP))
    result = mine_projects_root(root, repo=None, min_sessions=1, min_len=2, max_len=5)
    assert result.sessions_scanned == 2
    assert result.sessions_unreadable == 1
    assert result.candidates[0].sessions == ("good",)


def test_mine_projects_root_since_mtime_skips_older_transcripts(tmp_path: Path) -> None:
    root = _projects_root(tmp_path)
    old = root / "-home-natha-OverSteward" / "s1.jsonl"
    os.utime(old, (1_000_000, 1_000_000))
    result = mine_projects_root(root, repo=None, min_sessions=1, min_len=2, max_len=5, since_mtime=2_000_000)
    assert result.sessions_scanned == 2
    assert result.candidates[0].sessions == ("s2", "s3")


def test_mine_projects_root_counts_unreadable_transcripts(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "-home-natha-OverSteward"
    project.mkdir(parents=True)
    (project / "broken.jsonl").write_text('{"broken\n')
    _write_session(project, "good", _session(SWEEP))
    result = mine_projects_root(root, repo=None, min_sessions=1, min_len=2, max_len=5)
    assert result.sessions_scanned == 2
    assert result.sessions_unreadable == 1
    assert result.candidates[0].sessions == ("good",)


def test_cli_exits_1_when_no_transcript_could_be_read(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "-home-natha-OverSteward"
    project.mkdir(parents=True)
    (project / "a.jsonl").write_text('{"broken\n')
    (project / "b.jsonl").write_text("not json at all\n")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-root", str(tmp_path / "projects"), "--out", str(tmp_path / "o"), "--dry-run"],
        capture_output=True,
        env=_cli_env(),
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "could not read any of 2" in proc.stderr


def test_cli_limit_caps_the_drafts_written(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "-home-natha-OverSteward"
    other = ["git fetch origin", "git merge --ff-only origin/master"]
    for sid in ("s1", "s2"):
        _write_session(project, sid, _session(SWEEP) + _session(other))
    out = tmp_path / "drafts"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-root", str(root), "--out", str(out), "--min-sessions", "2", "--limit", "1"],
        capture_output=True,
        env=_cli_env(),
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "candidates: 2 (writing 1)" in proc.stdout
    assert len(list(out.glob("*/SKILL.md"))) == 1


def test_cli_never_writes_a_secret_into_a_draft(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "-home-natha-OverSteward"
    for sid in ("s1", "s2"):
        _write_session(project, sid, _session([SECRET_CMD, "git status"]))
    out = tmp_path / "drafts"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-root", str(root), "--out", str(out), "--min-sessions", "2"],
        capture_output=True,
        env=_cli_env(),
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    written = "\n".join(p.read_text() for p in out.rglob("*.md"))
    assert "hunter2" not in written
    assert "npg_S3cr3tPw" not in written
    assert "withheld" in written


def test_cli_exits_2_when_nothing_to_look_at(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-root", str(tmp_path / "missing"), "--out", str(tmp_path / "o")],
        capture_output=True,
        env=_cli_env(),
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "no transcripts" in (proc.stdout + proc.stderr).lower()


def test_cli_writes_drafts_and_reports_counts(tmp_path: Path) -> None:
    root = _projects_root(tmp_path)
    out = tmp_path / "drafts"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-root", str(root), "--out", str(out), "--min-sessions", "2"],
        capture_output=True,
        env=_cli_env(),
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "sessions scanned: 3" in proc.stdout
    assert "candidates: 1" in proc.stdout
    assert (out / "INDEX.md").exists()
