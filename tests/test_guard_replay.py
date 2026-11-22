# ABOUTME: Tests for oversteward.guard_replay — replaying the destructive-command gate over transcripts.
# ABOUTME: Every transcript and command here is synthetic; one test per row of OS#768's fixture table.

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path, PurePosixPath

import pytest

from oversteward import dispatch_run, guard_replay

REPO = Path(__file__).resolve().parents[1]
CANON_HOOK = REPO / "shared" / "scripts" / "dev" / "check_destructive_command.py"
HOOK_COMMAND = 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/check_destructive_command.py"'
DAY = 86400

# Synthetic commands, one per side of each tier.
FLUSH = "python manage.py flush --noinput"
ARTIFACT_DELETE = "rm -rf node_modules"
TREE_DELETE = "rm -rf /srv/appdata"
HARD_RESET = "git reset --hard HEAD~1"
SKIP_HOOKS = "git commit --no-verify -m wip"
ADMIN_MERGE = "gh pr merge 5 --admin"
LISTING = "ls -la /srv"
BOTH_TIERS = "git add -A && rm -rf /srv/appdata"

REGISTRY = """\
contexts:
  - id: alpha
    local_path: "/work/alpha"
  - id: beta
    local_path: "/work/beta"
  - id: nowhere
"""


def _load_cli():
    path = REPO / "scripts" / "guard_replay.py"
    spec = importlib.util.spec_from_file_location("guard_replay_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLI = _load_cli()


def bash(
    command: str,
    tool_id: str,
    *,
    cwd: str = "/work/alpha",
    sidechain: object = False,
    entrypoint: str = "claude-vscode",
    session: str | None = None,
) -> dict:
    entry = {
        "type": "assistant",
        "cwd": cwd,
        "entrypoint": entrypoint,
        "message": {
            "content": [
                {"type": "text", "text": "running it"},
                {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}},
            ]
        },
    }
    if sidechain is not None:
        entry["isSidechain"] = sidechain
    if session is not None:
        entry["sessionId"] = session
    return entry


def recorded(tool_id: str, decision: str, hook_command: str = HOOK_COMMAND) -> dict:
    reason = f"HEADER\n\nCommand: x\nPattern: something\nRisk: it."
    stdout = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }
    )
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_success",
            "hookEvent": "PreToolUse",
            "hookName": "PreToolUse:Bash",
            "toolUseID": tool_id,
            "command": hook_command,
            "stdout": stdout,
        },
    }


def hook_error(tool_id: str, text: str) -> dict:
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "is_error": True,
                    "content": f"PreToolUse:Bash hook error: {text}",
                }
            ]
        },
    }


def write(path: Path, entries: list[dict], *, age_days: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    return projects


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(REGISTRY, encoding="utf-8")
    return path


def run(capsys, root: Path, registry: Path, *extra: str) -> tuple[int, str, str]:
    code = CLI.main(["--root", str(root), "--registry", str(registry), *extra])
    out, err = capsys.readouterr()
    return code, out, err


def line(out: str, prefix: str) -> str:
    found = [text for text in out.splitlines() if text.startswith(prefix)]
    assert len(found) == 1, f"expected one line starting {prefix!r} in:\n{out}"
    return found[0]


def rows(path: Path) -> list[dict]:
    return [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]


def stub_hook(tmp_path: Path, body: str, name: str = "stub_hook.py") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


PASSING_STUB = "def main():\n    return 0\n"

CRASHING_STUB = """\
import json, sys

def main():
    event = json.load(sys.stdin)
    if "CRASHMARK" in event["tool_input"]["command"]:
        raise RuntimeError("stub crash")
    return 0
"""


# --- nested transcripts are read ----------------------------------------------


def test_an_ask_in_a_nested_workflow_subagent_is_read(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [bash(LISTING, "t1")])
    nested = root / "-work-alpha" / "s1" / "subagents" / "workflows" / "wf_1" / "agent-x.jsonl"
    write(nested, [bash(FLUSH, "t2", sidechain=True)])

    code, out, _ = run(capsys, root, registry)

    assert code == 0
    assert line(out, "transcripts:") == "transcripts: 2 read, 0 unreadable"
    assert line(out, "outcomes:") == "outcomes: ask 1, deny 0, pass 1, error 0"


# --- both sides of the ask line ------------------------------------------------


def test_a_flush_asks_and_a_build_artifact_delete_passes(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [bash(FLUSH, "t1"), bash(ARTIFACT_DELETE, "t2")])

    code, out, _ = run(capsys, root, registry)

    assert code == 0
    assert line(out, "commands:").startswith("commands: 2 ")
    assert line(out, "outcomes:") == "outcomes: ask 1, deny 0, pass 1, error 0"
    assert line(out, "asks by pattern:") == "asks by pattern: manage.py flush 1"


# --- tiers stay apart ------------------------------------------------------------


def test_a_commit_that_skips_its_hooks_is_a_deny_not_an_ask(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [bash(SKIP_HOOKS, "t1")])

    code, out, _ = run(capsys, root, registry)

    assert code == 0
    assert line(out, "outcomes:") == "outcomes: ask 0, deny 1, pass 0, error 0"
    assert line(out, "denies by pattern:") == "denies by pattern: git --no-verify 1"
    assert line(out, "asks by pattern:") == "asks by pattern: none"


# --- in-process equals the real hook ---------------------------------------------


def _subprocess_decision(command: str) -> guard_replay.Decision:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    done = subprocess.run(
        [sys.executable, str(CANON_HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
    )
    return guard_replay.read_output(done.stdout, done.returncode)


def test_the_in_process_hook_decides_as_the_hook_run_as_a_process():
    hook = guard_replay.load_hook(CANON_HOOK)
    commands = [LISTING, ARTIFACT_DELETE, FLUSH, TREE_DELETE, HARD_RESET, SKIP_HOOKS, ADMIN_MERGE,
                BOTH_TIERS]

    in_process = [(hook(c).outcome, hook(c).pattern) for c in commands]
    as_process = [(_subprocess_decision(c).outcome, _subprocess_decision(c).pattern) for c in commands]

    assert in_process == as_process
    assert {outcome for outcome, _ in in_process} == {"pass", "ask", "deny"}
    assert in_process[-1] == ("deny", "git add -A / .")


# --- could not look is not zero ----------------------------------------------------


def test_an_empty_root_is_nothing_to_look_at(capsys, root, registry):
    code, out, _ = run(capsys, root, registry)

    assert code == 2
    assert line(out, "transcripts:") == "transcripts: 0 read, 0 unreadable"


def test_a_missing_root_could_not_look(capsys, tmp_path, registry):
    code, out, err = run(capsys, tmp_path / "absent", registry)

    assert code == 1
    assert out == ""
    assert "could not look: projects root" in err


def test_transcripts_with_no_bash_command_are_nothing_to_look_at(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [{"type": "user", "message": {"content": "hi"}}])

    code, out, _ = run(capsys, root, registry)

    assert code == 2
    assert line(out, "transcripts:") == "transcripts: 1 read, 0 unreadable"
    assert line(out, "commands:").startswith("commands: 0 ")


def test_commands_with_no_ask_are_measured_and_counted(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [bash(LISTING, f"t{n}") for n in range(3)])

    code, out, _ = run(capsys, root, registry)

    assert code == 0
    assert line(out, "commands:").startswith("commands: 3 ")
    assert line(out, "outcomes:") == "outcomes: ask 0, deny 0, pass 3, error 0"


def test_a_corrupt_middle_line_is_named_and_the_rest_measured(capsys, root, registry):
    bad = root / "-work-alpha" / "bad.jsonl"
    bad.parent.mkdir(parents=True)
    bad.write_text(json.dumps(bash(FLUSH, "t1")) + "\n{not json\n" + json.dumps(bash(FLUSH, "t2")) + "\n")
    write(root / "-work-alpha" / "good.jsonl", [bash(LISTING, "t3")])

    code, out, err = run(capsys, root, registry)

    assert code == 1
    assert "unreadable transcript:" in err and "bad.jsonl:2:" in err
    assert line(out, "transcripts:") == "transcripts: 1 read, 1 unreadable"
    assert line(out, "outcomes:") == "outcomes: ask 0, deny 0, pass 1, error 0"


# --- a hook crash is not a pass -------------------------------------------------------


def test_a_hook_that_raises_is_an_error_row_and_exit_1(capsys, root, registry, tmp_path):
    hook = stub_hook(tmp_path, CRASHING_STUB)
    write(root / "-work-alpha" / "s1.jsonl", [bash("echo CRASHMARK", "t1"), bash(LISTING, "t2")])
    out_rows = tmp_path / "rows.jsonl"

    code, out, _ = run(capsys, root, registry, "--hook", str(hook), "--rows", str(out_rows))

    assert code == 1
    assert line(out, "outcomes:") == "outcomes: ask 0, deny 0, pass 1, error 1"
    [row] = rows(out_rows)
    assert row["outcome"] == "error"
    assert "RuntimeError: stub crash" in row["detail"]


def test_a_hook_that_exits_non_zero_is_an_error():
    def main():
        raise SystemExit(2)

    assert guard_replay.run_hook(main, "anything").outcome == "error"


def test_hook_output_that_is_not_a_decision_is_an_error():
    assert guard_replay.read_output("not json", 0).outcome == "error"
    assert guard_replay.read_output(json.dumps({"other": 1}), 0).outcome == "error"


def test_an_unknown_permission_decision_is_an_error():
    output = json.dumps({"hookSpecificOutput": {"permissionDecision": "maybe"}})

    assert guard_replay.read_output(output, 0).outcome == "error"


def test_the_hook_sees_the_command_and_the_streams_are_restored():
    seen = []

    def main():
        seen.append(json.load(sys.stdin)["tool_input"]["command"])
        print('{"hookSpecificOutput": {"permissionDecision": "ask", '
              '"permissionDecisionReason": "Pattern: p"}}')
        return 0

    stdin, stdout = sys.stdin, sys.stdout
    decision = guard_replay.run_hook(main, "echo hi")

    assert decision == guard_replay.Decision("ask", pattern="p")
    assert seen == ["echo hi"]
    assert (sys.stdin, sys.stdout) == (stdin, stdout)


# --- attribution has an edge -----------------------------------------------------------


SESSION_STUB = """\
import json, sys

def main():
    event = json.load(sys.stdin)
    session = event.get("session_id", "none")
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "ask",
                      "permissionDecisionReason": "Pattern: session " + session}}))
    return 0
"""


def test_the_hook_sees_each_calls_session_and_decides_per_session(capsys, root, registry, tmp_path):
    hook = stub_hook(tmp_path, SESSION_STUB)
    write(
        root / "-work-alpha" / "s1.jsonl",
        [
            bash(LISTING, "t1", session="s-one"),
            bash(LISTING, "t2", session="s-two"),
            bash(LISTING, "t3", session="s-one"),
            bash(LISTING, "t4"),
        ],
    )

    code, out, _ = run(capsys, root, registry, "--hook", str(hook))

    assert code == 0
    assert line(out, "asks by pattern:") == (
        "asks by pattern: session s-one 2, session none 1, session s-two 1"
    )

def test_cwd_and_named_paths_attribute_and_a_sibling_name_is_other(capsys, root, registry, tmp_path):
    write(
        root / "-work-alpha" / "s1.jsonl",
        [
            bash("rm -rf /work/beta/cache", "t1", cwd="/work/alpha/sub"),
            bash("rm -rf /work/alphabet/cache", "t2", cwd="/work/alpha-old"),
            bash("rm -rf /mnt/work/beta/cache", "t3", cwd="/elsewhere"),
        ],
    )
    out_rows = tmp_path / "rows.jsonl"

    code, out, _ = run(capsys, root, registry, "--rows", str(out_rows))

    assert code == 0
    assert line(out, "asks by context:") == "asks by context: other 2, alpha 1, beta 1"
    contexts = {row["command"]: row["contexts"] for row in rows(out_rows)}
    assert contexts == {
        "rm -rf /work/beta/cache": ["alpha", "beta"],
        "rm -rf /work/alphabet/cache": ["other"],
        "rm -rf /mnt/work/beta/cache": ["other"],
    }


def test_a_launch_directory_is_its_longest_matching_root_at_a_dash_boundary():
    alpha = guard_replay.Context("alpha", PurePosixPath("/work/alpha"))
    nested = guard_replay.Context("nested", PurePosixPath("/work/alpha/bet"))
    contexts = [alpha, nested]

    assert guard_replay.launch_context("-work-alpha", contexts) == "alpha"
    assert guard_replay.launch_context("-work-alpha--claude-worktrees-x", contexts) == "alpha"
    assert guard_replay.launch_context("-work-alphabet", contexts) == "other"
    assert guard_replay.launch_context("-work-alpha-bet-x", contexts) == "nested"
    assert guard_replay.launch_context("-work-alpha-bet-x", [nested, alpha]) == "nested"


# --- unattended split -------------------------------------------------------------------


def test_the_same_ask_in_a_sidechain_and_a_main_entry_splits_one_and_one(capsys, root, registry):
    write(
        root / "-work-alpha" / "s1.jsonl",
        [bash(FLUSH, "t1", sidechain=False), bash(FLUSH, "t2", sidechain=True)],
    )

    code, out, _ = run(capsys, root, registry)

    assert code == 0
    assert line(out, "asks by attendance:") == "asks by attendance: attended 1, unattended 1, unknown 0"


def test_a_headless_main_chain_session_is_unattended(capsys, root, registry):
    write(
        root / "-work-alpha" / "s1.jsonl",
        [
            bash(FLUSH, "t1", sidechain=False, entrypoint="sdk-cli"),
            bash(FLUSH, "t2", sidechain=False, entrypoint="claude-vscode"),
        ],
    )

    _, out, _ = run(capsys, root, registry)

    assert line(out, "asks by attendance:") == "asks by attendance: attended 1, unattended 1, unknown 0"


def test_an_entry_without_a_sidechain_flag_is_unknown(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [bash(FLUSH, "t1", sidechain=None)])

    _, out, _ = run(capsys, root, registry)

    assert line(out, "asks by attendance:") == "asks by attendance: attended 0, unattended 0, unknown 1"


# --- unlabelled is neither class ----------------------------------------------------------


def _two_asks(root: Path) -> None:
    write(root / "-work-alpha" / "s1.jsonl", [bash(FLUSH, "t1"), bash(TREE_DELETE, "t2")])


def test_an_unlabelled_ask_is_neither_warranted_nor_false(capsys, root, registry, tmp_path):
    _two_asks(root)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps({"key": guard_replay.command_key(FLUSH), "verdict": "warranted", "class": "db"})
        + "\n"
    )

    code, out, _ = run(capsys, root, registry, "--labels", str(labels))

    assert code == 0
    assert line(out, "labels over") == (
        "labels over 2 distinct flagged commands: warranted 1, false 0, unlabelled 1, misread 0"
    )
    assert line(out, "warranted by class:") == "warranted by class: db 1"
    assert line(out, "false by class:") == "false by class: none"


def test_an_unknown_verdict_could_not_look(capsys, root, registry, tmp_path):
    _two_asks(root)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"key": "abc", "verdict": "maybe", "class": "db"}) + "\n")

    code, out, err = run(capsys, root, registry, "--labels", str(labels))

    assert code == 1
    assert out == ""
    assert "labels.jsonl:1: needs a key, a verdict" in err


def test_an_unknown_verdict_names_the_file_and_its_line(capsys, root, registry, tmp_path):
    _two_asks(root)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps({"key": "abc", "verdict": "misread", "class": "quoted"})
        + "\n"
        + json.dumps({"key": "def", "verdict": "harmless", "class": "quoted"})
        + "\n"
    )

    code, out, err = run(capsys, root, registry, "--labels", str(labels))

    assert code == 1
    assert out == ""
    assert err == (
        f"could not look: labels {labels}:2: needs a key, "
        "a verdict in ('warranted', 'false', 'misread') and a class\n"
    )


# --- three verdicts and the readiness line --------------------------------------------------

MARKING_STUB = """\
import json, sys

def main():
    command = json.load(sys.stdin)["tool_input"]["command"]
    for outcome in ("ask", "deny"):
        if outcome.upper() + "MARK" in command:
            reason = "Pattern: stub " + outcome
            decision = {"permissionDecision": outcome, "permissionDecisionReason": reason}
            print(json.dumps({"hookSpecificOutput": decision}))
    return 0
"""

#: Distinct commands of each kind under each outcome, in counts that differ wherever a
#: dropped or swapped term would otherwise go unseen.
KINDS = {
    "ask": {"warranted": 1, "false": 1, "misread": 2, "unlabelled": 3},
    "deny": {"warranted": 1, "false": 3, "misread": 1, "unlabelled": 4},
}
CLASSES = {
    ("ask", "warranted"): "db",
    ("deny", "warranted"): "db",
    ("ask", "false"): "grep",
    ("deny", "false"): "grep",
    ("ask", "misread"): "quoted",
    ("deny", "misread"): "dry-run",
}


def _every_kind(root: Path, tmp_path: Path) -> tuple[Path, Path]:
    """A stub hook and a labels file over KINDS, plus a labelled command the hook passes."""
    entries, labels = [bash("echo PASSMARK", "t0")], []
    labels.append({"key": guard_replay.command_key("echo PASSMARK"), "verdict": "misread", "class": "x"})
    for outcome, kinds in KINDS.items():
        for kind, count in kinds.items():
            for n in range(count):
                text = f"echo {outcome.upper()}MARK {kind} {n}"
                entries.append(bash(text, f"t-{outcome}-{kind}-{n}"))
                if kind != "unlabelled":
                    cls = CLASSES[(outcome, kind)]
                    labels.append({"key": guard_replay.command_key(text), "verdict": kind, "class": cls})
    write(root / "-work-alpha" / "s1.jsonl", entries)
    path = tmp_path / "labels.jsonl"
    path.write_text("".join(json.dumps(label) + "\n" for label in labels))
    return stub_hook(tmp_path, MARKING_STUB), path


def test_a_three_verdict_labels_file_prints_each_count_and_class(capsys, root, registry, tmp_path):
    hook, labels = _every_kind(root, tmp_path)
    out_rows = tmp_path / "rows.jsonl"

    code, out, err = run(
        capsys, root, registry, "--hook", str(hook), "--labels", str(labels), "--rows", str(out_rows)
    )

    assert (code, err) == (0, "")
    assert line(out, "outcomes:") == "outcomes: ask 7, deny 9, pass 1, error 0"
    assert line(out, "labels over") == (
        "labels over 16 distinct flagged commands: warranted 2, false 4, unlabelled 7, misread 3"
    )
    assert line(out, "warranted by class:") == "warranted by class: db 2"
    assert line(out, "false by class:") == "false by class: grep 4"
    assert line(out, "misread by class:") == "misread by class: quoted 2, dry-run 1"
    verdicts = Counter((row["outcome"], row["verdict"]) for row in rows(out_rows))
    assert verdicts[("ask", "misread")] == 2 and verdicts[("deny", "misread")] == 1
    assert verdicts[("deny", None)] == 4


def test_the_readiness_line_counts_every_flagged_command_not_warranted(
    capsys, root, registry, tmp_path
):
    hook, labels = _every_kind(root, tmp_path)

    _, out, _ = run(capsys, root, registry, "--hook", str(hook), "--labels", str(labels))

    assert line(out, "ask not warranted:") == (
        "ask not warranted: 6 of 7 distinct flagged commands (false 1, misread 2, unlabelled 3)"
    )
    assert line(out, "deny not warranted:") == (
        "deny not warranted: 8 of 9 distinct flagged commands (false 3, misread 1, unlabelled 4)"
    )


def test_a_two_verdict_labels_file_loads_and_prints_as_before(capsys, root, registry, tmp_path):
    write(
        root / "-work-alpha" / "s1.jsonl",
        [bash(FLUSH, "t1"), bash(TREE_DELETE, "t2"), bash(HARD_RESET, "t3")],
    )
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps({"key": guard_replay.command_key(FLUSH), "verdict": "warranted", "class": "db"})
        + "\n\n"
        + json.dumps({"key": guard_replay.command_key(TREE_DELETE), "verdict": "false", "class": "x"})
        + "\n"
    )

    loaded = guard_replay.load_labels(labels)
    code, out, _ = run(capsys, root, registry, "--labels", str(labels))

    assert loaded == {
        guard_replay.command_key(FLUSH): guard_replay.Label("warranted", "db"),
        guard_replay.command_key(TREE_DELETE): guard_replay.Label("false", "x"),
    }
    assert code == 0
    assert line(out, "labels over") == (
        "labels over 3 distinct flagged commands: warranted 1, false 1, unlabelled 1, misread 0"
    )
    assert line(out, "warranted by class:") == "warranted by class: db 1"
    assert line(out, "false by class:") == "false by class: x 1"
    assert line(out, "misread by class:") == "misread by class: none"
    assert line(out, "ask not warranted:") == (
        "ask not warranted: 2 of 3 distinct flagged commands (false 1, misread 0, unlabelled 1)"
    )
    assert line(out, "deny not warranted:") == (
        "deny not warranted: 0 of 0 distinct flagged commands (false 0, misread 0, unlabelled 0)"
    )


def test_a_missing_labels_file_could_not_look(capsys, root, registry, tmp_path):
    _two_asks(root)

    code, out, err = run(capsys, root, registry, "--labels", str(tmp_path / "absent.jsonl"))

    assert code == 1
    assert out == ""
    assert "could not look: labels" in err


# --- recorded means this hook ---------------------------------------------------------------


def test_only_this_hooks_recorded_decision_is_compared(capsys, root, registry, tmp_path):
    hook = stub_hook(tmp_path, PASSING_STUB)
    write(
        root / "-work-alpha" / "s1.jsonl",
        [
            bash(LISTING, "t1"),
            recorded("t1", "ask", hook_command=f'python3 "/hooks/{hook.name}"'),
            recorded("t1", "deny", hook_command='python3 "/hooks/other_guard.py"'),
        ],
    )

    code, out, _ = run(capsys, root, registry, "--hook", str(hook))

    assert code == 0
    assert line(out, "agreement:") == "agreement: 0 of 1 recorded decisions of this hook"
    key = guard_replay.command_key(LISTING)
    assert line(out, "  disagreement") == f"  disagreement {key}: replay pass, recorded ask"
    assert line(out, "recorded decisions of other hooks:") == "recorded decisions of other hooks: 1"


def test_a_recorded_decision_whose_call_was_not_replayed_is_not_in_the_total(
    capsys, root, registry
):
    write(root / "-work-alpha" / "s1.jsonl", [bash(LISTING, "t1"), recorded("gone", "ask")])

    _, out, _ = run(capsys, root, registry)

    assert line(out, "agreement:") == "agreement: 0 of 0 recorded decisions of this hook"
    assert line(out, "recorded decisions with no replayed call:") == (
        "recorded decisions with no replayed call: 1"
    )


def test_only_a_pretooluse_attachment_or_an_error_result_is_a_recorded_decision(
    capsys, root, registry
):
    post = recorded("t1", "deny")
    post["attachment"]["hookEvent"] = "PostToolUse"
    quoted = hook_error("t2", f"[{HOOK_COMMAND}]: blocked")
    quoted["message"]["content"][0]["is_error"] = False
    write(
        root / "-work-alpha" / "s1.jsonl",
        [bash(SKIP_HOOKS, "t1"), post, bash(SKIP_HOOKS + " ", "t2"), quoted],
    )

    _, out, _ = run(capsys, root, registry)

    assert line(out, "agreement:") == "agreement: 0 of 0 recorded decisions of this hook"
    assert line(out, "recorded decisions of other hooks:") == "recorded decisions of other hooks: 0"
    assert line(out, "recorded decisions naming no hook:").startswith("recorded decisions naming no hook: 0 ")


def test_a_recorded_ask_the_replay_repeats_agrees(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [bash(FLUSH, "t1"), recorded("t1", "ask")])

    _, out, _ = run(capsys, root, registry)

    assert line(out, "agreement:") == "agreement: 1 of 1 recorded decisions of this hook"


def test_a_deny_is_recorded_as_a_hook_error_tool_result(capsys, root, registry):
    write(
        root / "-work-alpha" / "s1.jsonl",
        [
            bash(SKIP_HOOKS, "t1"),
            hook_error("t1", f"[{HOOK_COMMAND}]: blocked"),
            bash(ADMIN_MERGE, "t2"),
            hook_error("t2", "HEADER of a JSON deny, which names no hook"),
            bash(LISTING, "t3"),
            hook_error("t3", "[command hook 4]: blocked"),
        ],
    )

    _, out, _ = run(capsys, root, registry)

    assert line(out, "agreement:") == "agreement: 1 of 1 recorded decisions of this hook"
    assert line(out, "recorded decisions naming no hook:") == (
        "recorded decisions naming no hook: 2 (ask 0, deny 2); "
        "the replay gives the same outcome on 1 of the 2 it replayed"
    )
    assert line(out, "deny with no recorded decision") == (
        "deny with no recorded decision of this hook: 1 "
        "(none recorded 0, naming no hook 1, another hook's 0)"
    )


# --- the summary is public-safe ----------------------------------------------------------------


def test_the_summary_never_prints_a_command_a_path_or_a_project(capsys, root, registry, tmp_path):
    write(
        root / "-work-ZQXPROJ" / "s1.jsonl",
        [bash("rm -rf /srv/ZQXMARK", "t1", cwd="/work/ZQXCWD"), recorded("t1", "deny")],
    )
    out_rows = tmp_path / "rows.jsonl"

    code, out, _ = run(capsys, root, registry, "--rows", str(out_rows))

    assert code == 0
    assert line(out, "outcomes:") == "outcomes: ask 1, deny 0, pass 0, error 0"
    assert "disagreement" in out
    assert "ZQX" not in out
    written = out_rows.read_text(encoding="utf-8")
    assert "ZQXMARK" in written and "ZQXCWD" in written


# --- the window cuts ---------------------------------------------------------------------------


def test_a_transcript_older_than_the_window_is_not_read(capsys, root, registry):
    write(root / "-work-alpha" / "new.jsonl", [bash(FLUSH, "t1")], age_days=29)
    write(root / "-work-alpha" / "old.jsonl", [bash(FLUSH, "t2")], age_days=31)

    code, out, _ = run(capsys, root, registry, "--since-days", "30")

    assert code == 0
    assert line(out, "transcripts:") == "transcripts: 1 read, 0 unreadable"
    assert line(out, "outcomes:") == "outcomes: ask 1, deny 0, pass 0, error 0"


# --- a resumed session's copied history ---------------------------------------------------------


def test_a_tool_call_copied_into_a_second_transcript_counts_once(capsys, root, registry):
    write(root / "-work-alpha" / "s1.jsonl", [bash(FLUSH, "t1")])
    write(root / "-work-alpha" / "s2.jsonl", [bash(FLUSH, "t1"), bash(FLUSH, "t2")])

    _, out, _ = run(capsys, root, registry)

    assert line(out, "commands:") == "commands: 2 (2 with a tool_use id, 1 duplicate calls skipped)"
    assert line(out, "sessions by launch context:") == (
        "sessions by launch context: alpha 2 (1 project dirs)"
    )


# --- the line reader ------------------------------------------------------------------------------


def test_iter_entries_yields_the_lines_before_a_bad_one(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"n": 1}\nnot json\n{"n": 3}\n', encoding="utf-8")

    entries = dispatch_run.iter_entries(path)

    assert next(entries) == {"n": 1}
    with pytest.raises(dispatch_run.TranscriptUnreadable, match=r"t\.jsonl:2: "):
        next(entries)
