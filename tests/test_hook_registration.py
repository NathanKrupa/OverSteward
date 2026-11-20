# ABOUTME: Tests for src/oversteward/hook_registration.py — hook scripts vs their registrations.
# ABOUTME: Builds synthetic repos whose origin ref carries settings, cards and hooks, then audits.

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from oversteward.dev_family import GitRepo, gather_family_status
from oversteward.diff import diff_state, exit_code, format_report
from oversteward.hook_registration import (
    PRESENT_UNREGISTERED,
    REGISTERED,
    REGISTERED_ABSENT,
    format_hook_table,
    gather_hook_registration,
)
from tests.git_fixtures import _init_repo

SETTINGS = ".claude/settings.json"
SCRIPT = "# synthetic hook\n"


def _cmd(name):
    return f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{name}"'


def _settings(*commands, event="PreToolUse"):
    group = {"matcher": "Bash", "hooks": [{"type": "command", "command": c} for c in commands]}
    return json.dumps({"hooks": {event: [group]}})


def _card(*commands):
    hooks = "".join(f"        - type: command\n          command: {c}\n" for c in commands)
    block = f"hooks:\n  PreToolUse:\n    - matcher: Bash\n      hooks:\n{hooks}" if commands else ""
    return f"---\nname: synthetic\ndescription: a test card\n{block}---\n\n# card\n"


def _audit(tmp_path, repos, fetch=False):
    """Run the family audit then the hook audit over {context id: (root, branch)}."""
    registry = {
        "contexts": [
            {"id": cid, "branch": branch, "local_path": str(root), "claude_md_path": "CLAUDE.md"}
            for cid, (root, branch) in repos.items()
        ]
    }
    shared = tmp_path / "shared-canonical"
    shared.mkdir(exist_ok=True)
    family = gather_family_status(registry, shared, fetch=fetch)
    return gather_hook_registration(registry, family, fetch_requested=fetch)


def _one(tmp_path, files, links=None, fetch=False):
    root = _init_repo(tmp_path / "repo", files, links=links)
    (row,) = _audit(tmp_path, {"demo": (root, "main")}, fetch=fetch)
    return row


def _findings(rows):
    return [f for f in diff_state({"contexts": []}, hook_rows=rows) if f["surface"] == "hook-registration"]


def _severities(rows):
    return sorted(f["severity"] for f in _findings(rows) if f["severity"] != "info")


class TestRegisteredAbsent:
    def test_a_registration_with_no_script_is_one_missing_finding_naming_it(self, tmp_path):
        row = _one(tmp_path, {SETTINGS: _settings(_cmd("ghost.py"))})
        assert row.statuses() == {"ghost.py": REGISTERED_ABSENT}
        (missing,) = [f for f in _findings([row]) if f["severity"] == "missing"]
        assert "ghost.py" in missing["message"]
        assert SETTINGS in missing["message"]
        assert "PreToolUse" in missing["message"]
        assert exit_code(_findings([row])) == 1

    def test_adding_the_script_makes_it_clean(self, tmp_path):
        row = _one(
            tmp_path, {SETTINGS: _settings(_cmd("ghost.py")), ".claude/hooks/ghost.py": SCRIPT}
        )
        assert row.statuses() == {"ghost.py": REGISTERED}
        assert _severities([row]) == []
        assert exit_code(_findings([row])) == 0

    @pytest.mark.parametrize(
        ("event", "consequence"),
        [
            ("PreToolUse", "before every matching tool call, refusing each one"),
            ("Stop", "each time Stop fires"),
        ],
    )
    def test_the_message_names_what_exit_2_does_under_its_event(
        self, tmp_path, event, consequence
    ):
        row = _one(tmp_path, {SETTINGS: _settings(_cmd("ghost.py"), event=event)})
        (missing,) = [f for f in _findings([row]) if f["severity"] == "missing"]
        assert missing["message"].endswith(consequence)

    def test_the_interpreter_exits_2_on_an_absent_script(self, tmp_path):
        """2 is the code the family's guards return to refuse a tool call."""
        absent = tmp_path / ".claude" / "hooks" / "ghost.py"
        proc = subprocess.run([sys.executable, str(absent)], capture_output=True)
        assert proc.returncode == 2


class TestPresence:
    def test_a_dangling_link_is_not_present(self, tmp_path):
        row = _one(
            tmp_path,
            {SETTINGS: _settings(_cmd("x.py"))},
            links={".claude/hooks/x.py": "../../shared/scripts/dev/x.py"},
        )
        assert row.statuses() == {"x.py": REGISTERED_ABSENT}

    def test_a_link_escaping_the_tree_is_not_present(self, tmp_path):
        outside = tmp_path / "outside.py"
        outside.write_text(SCRIPT, encoding="utf-8")
        row = _one(
            tmp_path,
            {SETTINGS: _settings(_cmd("x.py"))},
            links={".claude/hooks/x.py": "../../../outside.py"},
        )
        assert row.statuses() == {"x.py": REGISTERED_ABSENT}

    def test_only_python_entries_are_subjects(self, tmp_path):
        row = _one(tmp_path, {".claude/hooks/README.md": "x\n", ".claude/hooks/run.sh": "x\n"})
        assert row.statuses() == {}

    def test_no_settings_and_no_hooks_directory_is_a_measured_zero(self, tmp_path):
        row = _one(tmp_path, {"README.md": "x\n"})
        assert row.unreadable is None
        assert (row.present, row.registrations) == (frozenset(), ())
        assert exit_code(_findings([row])) == 0


class TestEntries:
    def test_an_absent_directory_is_an_empty_listing(self, tmp_path):
        root = _init_repo(tmp_path / "repo", {"README.md": "x\n"})
        assert GitRepo(root).entries("origin/main", ".claude/hooks") == {}

    def test_a_ref_git_cannot_read_is_none_not_empty(self, tmp_path):
        root = _init_repo(tmp_path / "repo", {".claude/hooks/x.py": SCRIPT})
        assert GitRepo(root).entries("origin/nowhere", ".claude/hooks") is None


class TestPresentUnregistered:
    def test_a_script_nothing_registers_is_one_drift(self, tmp_path):
        row = _one(tmp_path, {".claude/hooks/lone.py": SCRIPT, SETTINGS: "{}"})
        assert row.statuses() == {"lone.py": PRESENT_UNREGISTERED}
        (drift,) = [f for f in _findings([row]) if f["severity"] == "drift"]
        assert "lone.py" in drift["message"]
        assert _severities([row]) == ["drift"]

    def test_registering_it_makes_it_clean(self, tmp_path):
        row = _one(
            tmp_path, {".claude/hooks/lone.py": SCRIPT, SETTINGS: _settings(_cmd("lone.py"))}
        )
        assert row.statuses() == {"lone.py": REGISTERED}
        assert _severities([row]) == []


class TestAgentCards:
    def test_a_script_registered_only_by_a_card_is_registered(self, tmp_path):
        row = _one(
            tmp_path,
            {".claude/hooks/card_only.py": SCRIPT, ".claude/agents/c.md": _card(_cmd("card_only.py"))},
        )
        assert row.statuses() == {"card_only.py": REGISTERED}
        (reg,) = row.registrations
        assert (reg.source, reg.event) == (".claude/agents/c.md", "PreToolUse")

    def test_a_card_without_hooks_registers_nothing(self, tmp_path):
        row = _one(
            tmp_path, {".claude/hooks/card_only.py": SCRIPT, ".claude/agents/c.md": _card()}
        )
        assert row.statuses() == {"card_only.py": PRESENT_UNREGISTERED}

    def test_links_to_regular_files_resolve_as_in_this_repo(self, tmp_path):
        row = _one(
            tmp_path,
            {
                "shared/scripts/dev/linked.py": SCRIPT,
                "shared/agents/c.md": _card(_cmd("linked.py")),
            },
            links={
                ".claude/hooks/linked.py": "../../shared/scripts/dev/linked.py",
                ".claude/agents/c.md": "../../shared/agents/c.md",
            },
        )
        assert row.statuses() == {"linked.py": REGISTERED}


class TestShapeBoundary:
    @pytest.mark.parametrize(
        "command",
        [
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/x.py"',
            "python3 $CLAUDE_PROJECT_DIR/.claude/hooks/x.py",
            'uv run --no-sync python "$CLAUDE_PROJECT_DIR"/.claude/hooks/x.py --strict',
        ],
    )
    def test_the_project_dir_shape_registers_behind_any_interpreter(self, tmp_path, command):
        row = _one(tmp_path, {".claude/hooks/x.py": SCRIPT, SETTINGS: _settings(command)})
        assert row.statuses() == {"x.py": REGISTERED}
        assert row.unshaped == ()

    @pytest.mark.parametrize(
        "command",
        [
            "python3 .claude/hooks/x.py",
            "python3 /srv/elsewhere/.claude/hooks/x.py",
            "python3 '$CLAUDE_PROJECT_DIR/.claude/hooks/x.py'",
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/x.py.bak"',
            "python3 $CLAUDE_PROJECT_DIR/.claude/hooks/x.py.bak",
            "python3 /opt$CLAUDE_PROJECT_DIR/.claude/hooks/x.py",
        ],
    )
    def test_any_other_mention_registers_nothing_and_is_an_info_line(self, tmp_path, command):
        row = _one(tmp_path, {".claude/hooks/x.py": SCRIPT, SETTINGS: _settings(command)})
        assert row.statuses() == {"x.py": PRESENT_UNREGISTERED}
        infos = [f for f in _findings([row]) if f["severity"] == "info" and f["context"]]
        assert len(infos) == 1
        assert command in infos[0]["message"]


class TestCouldNotRead:
    @pytest.mark.parametrize("text", ["{", "[]"])
    def test_settings_that_are_not_a_json_object_make_the_context_unreadable(
        self, tmp_path, text
    ):
        row = _one(tmp_path, {".claude/hooks/x.py": SCRIPT, SETTINGS: text})
        assert row.unreadable is not None
        assert row.statuses() == {}
        findings = _findings([row])
        unread = [f for f in findings if f["severity"] == "unreadable" and f["context"]]
        assert [f["context"] for f in unread] == ["demo"]
        assert "not" in unread[0]["message"] and SETTINGS in unread[0]["message"]
        assert not [f for f in findings if f["severity"] in ("missing", "drift")]
        assert not any("In lockstep" in line for line in format_report(findings))
        assert exit_code(findings) == 2

    @pytest.mark.parametrize(
        "card", ["---\nname: x\nhooks: [unclosed\n---\n", "---\n- a\n---\n"]
    )
    def test_card_frontmatter_that_is_not_a_yaml_mapping_makes_the_context_unreadable(
        self, tmp_path, card
    ):
        row = _one(tmp_path, {".claude/hooks/x.py": SCRIPT, ".claude/agents/c.md": card})
        assert row.unreadable is not None
        assert ".claude/agents/c.md" in row.unreadable
        assert row.statuses() == {}

    @pytest.mark.parametrize("directory", [".claude/hooks", ".claude/agents"])
    def test_a_directory_git_cannot_list_makes_the_context_unreadable(self, tmp_path, directory):
        class Unlistable(GitRepo):
            def entries(self, ref, path):
                return None if path == directory else super().entries(ref, path)

        root = _init_repo(tmp_path / "repo", {".claude/hooks/x.py": SCRIPT, SETTINGS: "{}"})
        registry = {"contexts": [{"id": "demo", "branch": "main", "local_path": str(root)}]}
        family = gather_family_status(registry, tmp_path / "no-canon", fetch=False)
        (row,) = gather_hook_registration(
            registry, family, fetch_requested=False, repo_factory=Unlistable
        )
        assert row.unreadable == f"could not list {directory}/ at origin/main"
        assert row.statuses() == {}

    def test_an_absent_ref_is_unreadable(self, tmp_path):
        root = _init_repo(tmp_path / "repo", {SETTINGS: "{}"})
        (row,) = _audit(tmp_path, {"demo": (root, "staging")})
        assert row.unreadable == "origin/staging absent"

    def test_a_requested_fetch_that_failed_is_unreadable(self, tmp_path):
        row = _one(tmp_path, {".claude/hooks/x.py": SCRIPT}, fetch=True)
        assert row.unreadable == "fetch of origin/main failed"

    def test_without_a_requested_fetch_the_local_ref_is_audited(self, tmp_path):
        row = _one(tmp_path, {".claude/hooks/x.py": SCRIPT}, fetch=False)
        assert row.unreadable is None
        assert row.statuses() == {"x.py": PRESENT_UNREGISTERED}


class TestWorkingTree:
    def test_the_working_tree_is_never_read(self, tmp_path):
        row_files = {".claude/hooks/x.py": SCRIPT, SETTINGS: _settings(_cmd("x.py"))}
        root = _init_repo(tmp_path / "repo", row_files)
        (root / ".claude/hooks/x.py").unlink()
        (root / SETTINGS).write_text("{", encoding="utf-8")
        (row,) = _audit(tmp_path, {"demo": (root, "main")})
        assert row.statuses() == {"x.py": REGISTERED}
        assert _severities([row]) == []


class TestMatrix:
    def test_the_matrix_counts_registered_against_present(self, tmp_path):
        row = _one(
            tmp_path,
            {
                ".claude/hooks/a.py": SCRIPT,
                ".claude/hooks/b.py": SCRIPT,
                SETTINGS: _settings(_cmd("a.py"), _cmd("ghost.py")),
            },
        )
        table = format_hook_table([row], fetch_requested=True)
        assert "demo (origin/main): 1 of 2 present scripts registered (2 registrations)" in table
        assert "NOT fetched" not in table[0]

    def test_a_no_fetch_matrix_says_the_refs_were_not_fetched(self, tmp_path):
        row = _one(tmp_path, {"README.md": "x\n"})
        assert "NOT fetched" in format_hook_table([row], fetch_requested=False)[0]

    def test_an_unread_context_prints_could_not_read(self, tmp_path):
        row = _one(tmp_path, {SETTINGS: "{"})
        (line,) = format_hook_table([row], fetch_requested=False)[1:]
        assert "COULD NOT READ" in line
