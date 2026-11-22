# ABOUTME: Tests for the destructive-command gate's scratchpad exception (OS#821).
# ABOUTME: Every path and session id is synthetic, built under pytest's tmp_path.
"""A delete confined to the session's own scratchpad stands down; every other form asks.

The scratchpad is ``<CLAUDE_CODE_TMPDIR>/claude-<uid>/<project>/<session id>/scratchpad``,
computed by the hook from its own environment and the event's ``session_id``.
Each negative fixture asserts the verdict the hook gives with no scratchpad
known at all, which is today's verdict, so the exception adds no pass there.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.dev.test_check_destructive_command import _hook_path, _load_hook

SESSION = "11111111-2222-4333-8444-555555555555"
OTHER_SESSION = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
PROJECT = "-work-alpha"
SEARCH_PATH = "/usr/local/bin:/usr/bin:/bin"
TMPDIR_VARIABLE = "CLAUDE_CODE_TMPDIR"


@pytest.fixture(scope="module")
def hook():
    return _load_hook()


class Tree:
    """A harness temp tree: the per-user directory, this session's scratchpad, and an outside."""

    def __init__(self, base) -> None:
        self.tmpdir = base / "ctmp"
        self.user_dir = self.tmpdir / f"claude-{os.getuid()}"
        self.project_dir = self.user_dir / PROJECT
        self.root = self.project_dir / SESSION / "scratchpad"
        self.other_root = self.project_dir / OTHER_SESSION / "scratchpad"
        self.outside = base / "outside"
        for directory in (self.root, self.other_root, self.outside):
            directory.mkdir(parents=True)
        self.environ = {TMPDIR_VARIABLE: str(self.tmpdir)}
        self.event = {"session_id": SESSION}


@pytest.fixture
def tree(tmp_path) -> Tree:
    return Tree(tmp_path)


def _verdict(hook, tree: Tree, command: str, *, event=None, environ=None, search_path=SEARCH_PATH):
    scope = hook._scratch_scope(
        tree.event if event is None else event, tree.environ if environ is None else environ
    )
    return hook._match(command, scope, search_path)


def _asks_as_today(hook, tree: Tree, command: str, **kwargs) -> None:
    today = hook._match(command)
    assert today is not None, "the fixture must be a command the gate holds today"
    assert _verdict(hook, tree, command, **kwargs) == today


# ---------------------------------------------------------------------------
# The forms that stand down.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [
        "rm -rf {root}/a",
        "rm -r {root}/a",
        "rm -fr {root}/a",
        "rm -R -f -v {root}/a",
        "rm --recursive --force {root}/a",
        "rm -rf -- {root}/a",
        "rm -rf {root}/a {root}/b",
        "rm -rf {root}/a/b/c",
        "rm -f {root}/after/*.json",
        "rm -rf {root}/*",
        "rm -rf {root}/a && echo removed",
        "rm -rf {root}/a; git status",
        "rm -rf {root}/a || echo failed",
        "cd /work/alpha && rm -rf {root}/a; git status --short",
        "ls -A {root} | head; rm -rf {root}/a",
        "rm -rf {root}/a; rm -rf {root}/b",
        "rm -rf {root}/a\necho done",
        "cd /work/alpha\nrm -rf {root}/a",
        "rm -rf {root}/a # cleanup",
    ],
)
def test_a_delete_confined_to_the_scratchpad_stands_down(hook, tree, template):
    command = template.format(root=tree.root)

    assert hook._match(command) is not None
    assert _verdict(hook, tree, command) is None


def test_a_link_as_the_last_segment_stands_down_because_rm_removes_the_link(hook, tree):
    (tree.root / "link").symlink_to(tree.outside, target_is_directory=True)

    assert _verdict(hook, tree, f"rm -rf {tree.root}/link") is None


def test_a_temp_root_that_is_itself_a_link_still_stands_down(hook, tmp_path):
    real = Tree(tmp_path / "disk")
    linked = tmp_path / "linked-tmp"
    linked.symlink_to(real.tmpdir, target_is_directory=True)
    environ = {TMPDIR_VARIABLE: str(linked)}
    root = linked / f"claude-{os.getuid()}" / PROJECT / SESSION / "scratchpad"
    scope = hook._scratch_scope(real.event, environ)

    assert hook._match(f"rm -rf {root}/a", scope, SEARCH_PATH) is None


# ---------------------------------------------------------------------------
# The negative fixtures the issue names, one per form.
# ---------------------------------------------------------------------------


def test_the_system_temp_directory_asks(hook, tree):
    _asks_as_today(hook, tree, "rm -rf /tmp/build-probe")


def test_the_harness_temp_directory_outside_any_scratchpad_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.tmpdir}/notes")
    _asks_as_today(hook, tree, f"rm -rf {tree.user_dir}/{PROJECT}")


def test_a_variable_asks(hook, tree):
    _asks_as_today(hook, tree, f"S={tree.root}; rm -rf $S/a")


def test_a_braced_variable_asks(hook, tree):
    _asks_as_today(hook, tree, "rm -rf ${S}/a")


def test_a_parent_segment_escape_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a/../../../../outside")


def test_a_parent_segment_as_the_last_segment_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a/..")


def test_a_glob_reaching_outside_the_scratchpad_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.project_dir}/*/scratchpad/a")


def test_a_glob_in_a_middle_segment_asks_because_a_match_may_be_a_link_out(hook, tree):
    (tree.root / "link").symlink_to(tree.outside, target_is_directory=True)

    _asks_as_today(hook, tree, f"rm -rf {tree.root}/*/data")


def test_a_glob_on_the_scratchpad_segment_itself_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}*")


def test_a_dot_glob_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/.*")


def test_a_second_target_outside_the_scratchpad_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a {tree.outside}/data")


def test_a_relative_second_target_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a src")


def test_a_sibling_sessions_scratchpad_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.other_root}/a")


def test_a_link_out_of_the_scratchpad_asks(hook, tree):
    (tree.root / "out").symlink_to(tree.outside, target_is_directory=True)

    _asks_as_today(hook, tree, f"rm -rf {tree.root}/out/data")


def test_a_link_into_a_sibling_whose_name_begins_with_scratchpad_asks(hook, tree):
    keep = tree.project_dir / SESSION / "scratchpad-keep"
    keep.mkdir()
    (tree.root / "link").symlink_to(keep, target_is_directory=True)

    _asks_as_today(hook, tree, f"rm -rf {tree.root}/link/data")


def test_a_scratchpad_that_is_itself_a_link_out_asks(hook, tmp_path):
    tree = Tree(tmp_path)
    tree.root.rmdir()
    tree.root.symlink_to(tree.outside, target_is_directory=True)

    _asks_as_today(hook, tree, f"rm -rf {tree.root}/data")


def test_the_scratchpad_itself_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}")


def test_a_trailing_slash_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a/")


def test_the_session_directory_beside_the_scratchpad_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.project_dir}/{SESSION}/tasks")


def test_a_name_that_only_begins_with_the_scratchpads_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}2/a")


def test_a_quoted_target_asks(hook, tree):
    _asks_as_today(hook, tree, f'rm -rf "{tree.root}/a"')


def test_an_escaped_character_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a\\ b")


def test_a_relative_target_after_a_change_into_the_scratchpad_asks(hook, tree):
    _asks_as_today(hook, tree, f"cd {tree.root} && rm -rf a")


# ---------------------------------------------------------------------------
# The scratchpad cannot be determined: the exception does not apply.
# ---------------------------------------------------------------------------


def test_no_session_id_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a", event={})


def test_a_malformed_session_id_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a", event={"session_id": "../" + SESSION})


def test_another_sessions_id_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a", event={"session_id": OTHER_SESSION})


def test_no_temp_directory_variable_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a", environ={})


def test_a_relative_temp_directory_variable_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a", environ={TMPDIR_VARIABLE: "ctmp"})


def test_a_relative_search_path_entry_asks(hook, tree):
    _asks_as_today(hook, tree, f"rm -rf {tree.root}/a", search_path="bin:/usr/bin")


# ---------------------------------------------------------------------------
# The argv the hook reads must be the argv the shell runs, before anything else.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [
        # a command before the delete that could change what its path names
        "ln -s {outside} {root}/w; rm -rf {root}/w/x",
        "mv {root}/a {root}/b && rm -rf {root}/b/c",
        "X=1; rm -rf {root}/a",
        # how the delete is run
        "sudo rm -rf {root}/a",
        "env -S 'rm -rf {outside}' rm -rf {root}/a",
        "X=1 rm -rf {root}/a",
        "/bin/rm -rf {root}/a",
        "echo $(rm -rf {root}/a)",
        "(rm -rf {root}/a)",
        "rm -rf {root}/a &",
        # what follows the delete's own words
        "rm -rf {root}/a 2>/dev/null",
        "rm -rf {root}/a > {outside}/log",
        "rm -rf {root}/a | tee {outside}/log",
        "rm -rf {root}/a |\ntee {outside}/log",
        "rm -rf {root}/a \\\n{outside}",
        "rm -rf {root}/a\r{outside}",
        "rm -rf {root}/a; bash -c 'rm -rf {root}/a'",
        # options outside the closed set
        "rm -rf --no-preserve-root {root}/a",
        "rm -rfi {root}/a",
        "rm -rf -- {root}/a -- {outside}",
        "rm -rf -- -x {root}/a",
    ],
)
def test_a_delete_the_hook_cannot_read_as_the_shell_runs_it_asks(hook, tree, template):
    command = template.format(root=tree.root, outside=tree.outside)

    _asks_as_today(hook, tree, command)


def test_a_confined_delete_beside_a_hard_reset_still_names_the_reset(hook, tree):
    command = f"rm -rf {tree.root}/a && git reset --hard HEAD~1"

    assert _verdict(hook, tree, command) == hook._match("git reset --hard HEAD~1")


def test_a_confined_delete_leaves_the_other_rules_their_whole_command(hook, tree):
    # The delete names a database client, so the SQL rules read the echo as run, not printed.
    command = f"echo 'DROP TABLE t'; rm -rf {tree.root}/psql"

    assert hook._match(command)[0] == "rm -rf"
    assert _verdict(hook, tree, command)[0] == "DROP/TRUNCATE"


@pytest.mark.parametrize(
    "kept",
    [
        "rm -rf /work/alpha/.scratch",
        "rm -rf /work/alpha/.venv",
        "rm -rf /work/alpha/src",
        "rm -f /work/alpha/*.py",
        "rm -f /var/log/app/*.log",
        "rm -rf /work/alpha/build/lib",
    ],
)
def test_the_kept_classes_ask_as_today(hook, tree, kept):
    _asks_as_today(hook, tree, kept)


# ---------------------------------------------------------------------------
# A generated sweep: no construct crossed into a confined delete earns a pass.
# ---------------------------------------------------------------------------

_CONSTRUCTS = (
    "X=1", "$X", "${X}", "$(pwd)", "`pwd`", "$((1))", "~", "{a,b}", "/work/*/x", "a=(1)",
    "(", ")", "{", "}", "&", ">", ">>", "<", "2>&1", "<<EOF", "sudo", "env", "';'", "\\;",
    "\\\n", "\r", "\x01", "é", "/work/alpha/src", "-i", "--interactive",
)


def _crossed(root: str) -> list[str]:
    deletes = [f"rm -rf {root}/a", f"rm -r {root}/a {root}/b", f"rm -f {root}/o/*.txt"]
    crossed = []
    for delete in deletes:
        words = delete.split(" ")
        for position in range(len(words) + 1):
            for construct in _CONSTRUCTS:
                crossed.append(" ".join(words[:position] + [construct] + words[position:]))
    return crossed


def test_no_crossed_form_passes_where_the_gate_holds_it_today(hook, tree):
    passed = [
        command for command in _crossed(str(tree.root))
        if hook._match(command) is not None and _verdict(hook, tree, command) is None
    ]

    assert len(_crossed(str(tree.root))) > 300
    assert passed == []


# ---------------------------------------------------------------------------
# End to end: the hook reads its scratchpad from the event and its environment.
# ---------------------------------------------------------------------------


def _run(tree: Tree, command: str, event: dict | None = None) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    payload.update(tree.event if event is None else event)
    environ = {**os.environ, **tree.environ, "PATH": SEARCH_PATH}
    return subprocess.run(
        [sys.executable, str(_hook_path())],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=environ,
    )


def test_end_to_end_a_confined_delete_gives_no_decision(tree):
    done = _run(tree, f"rm -rf {tree.root}/a")

    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_end_to_end_a_sibling_sessions_scratchpad_asks_naming_the_pattern(tree):
    done = _run(tree, f"rm -rf {tree.other_root}/a")

    assert done.returncode == 0 and done.stderr == ""
    decision = json.loads(done.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert "Pattern: rm -rf" in decision["permissionDecisionReason"]


def test_end_to_end_a_confined_delete_beside_a_hook_skip_is_still_denied(tree):
    done = _run(tree, f"rm -rf {tree.root}/a && git commit --no-verify -m wip")

    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
