# ABOUTME: Tests for the sanctioned with_test_env runner (scripts/dev/with_test_env.py).
# ABOUTME: Covers .env parsing, env merge precedence, arg split, exec seam, and secret non-leakage.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SECRET = "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"


def _load_runner():
    """Load the deployed runner by file path (no package install needed).

    Walks up from this test file to the repo root (the dir containing
    ``scripts/dev/with_test_env.py``), so it works regardless of how deep the
    test sits.
    """
    rel = Path("scripts") / "dev" / "with_test_env.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("with_test_env", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(f"could not locate {rel} above {__file__}")


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


class _Exec:
    """Injectable executor that records the call instead of replacing the process."""

    def __init__(self):
        self.calls: list[tuple[str, list[str], dict[str, str]]] = []

    def __call__(self, file, args, env):
        self.calls.append((file, list(args), dict(env)))


# ---------------------------------------------------------------------------
# parse_env_file — pure string work, preserves secret-bearing values
# ---------------------------------------------------------------------------


def test_parse_basic_pairs(runner):
    assert runner.parse_env_file("A=1\nB=two\n") == {"A": "1", "B": "two"}


def test_parse_strips_export_prefix(runner):
    assert runner.parse_env_file("export TOKEN=abc\n") == {"TOKEN": "abc"}


def test_parse_keeps_equals_and_ampersand_in_value(runner):
    assert runner.parse_env_file(f"DATABASE_URL={SECRET}\n") == {"DATABASE_URL": SECRET}


def test_parse_strips_matching_quotes(runner):
    assert runner.parse_env_file('A="quoted"\nB=\'single\'\n') == {"A": "quoted", "B": "single"}


def test_parse_skips_comments_and_blanks(runner):
    assert runner.parse_env_file("# comment\n\n  \nA=1\n") == {"A": "1"}


def test_parse_skips_lines_without_equals_or_key(runner):
    assert runner.parse_env_file("noequals\n=novalue\nA=1\n") == {"A": "1"}


# ---------------------------------------------------------------------------
# parse_env_file — python-dotenv quote/comment semantics (issue #175)
# ---------------------------------------------------------------------------


def test_parse_strips_unquoted_inline_comment(runner):
    # KEY=val # note -> val (python-dotenv drops a whitespace-preceded # comment)
    assert runner.parse_env_file("KEY=val # note\n") == {"KEY": "val"}


def test_parse_keeps_hash_inside_double_quotes(runner):
    # A # inside quotes is part of the value, not a comment.
    assert runner.parse_env_file('KEY="val # keep"\n') == {"KEY": "val # keep"}


def test_parse_keeps_hash_inside_single_quotes(runner):
    assert runner.parse_env_file("KEY='val # keep'\n") == {"KEY": "val # keep"}


def test_parse_keeps_unquoted_hash_without_preceding_space(runner):
    # No whitespace before the # means it is not an inline comment.
    assert runner.parse_env_file("URL=http://x#frag\n") == {"URL": "http://x#frag"}


def test_parse_keeps_leading_hash_value(runner):
    # A value that is only a #token (no whitespace before it) is kept verbatim.
    assert runner.parse_env_file("A=#allcomment\n") == {"A": "#allcomment"}


def test_parse_embedded_quote_value_dropped_not_mangled(runner):
    # "abc"def" is malformed for python-dotenv; the line is dropped, never
    # silently truncated to "abc". The key must not carry a mangled value.
    assert runner.parse_env_file('PW="abc"def"\n') == {}


def test_parse_unterminated_quote_dropped_not_mangled(runner):
    assert runner.parse_env_file('A="starts_quote\n') == {}


def test_parse_value_ending_with_quote_preserved(runner):
    # A bare value that merely ends with a quote char is not a quoted string.
    assert runner.parse_env_file('A=ends_quote"\n') == {"A": 'ends_quote"'}


def test_parse_double_quote_decodes_escapes(runner):
    assert runner.parse_env_file('A="line\\nbreak"\n') == {"A": "line\nbreak"}


def test_parse_single_quote_decodes_apostrophe_escape(runner):
    assert runner.parse_env_file("A='it\\'s'\n") == {"A": "it's"}


def test_parse_trailing_comment_after_closing_quote(runner):
    assert runner.parse_env_file('A="closed" # trailing comment\n') == {"A": "closed"}


def test_parse_normal_value_unaffected(runner):
    assert runner.parse_env_file("A=value\n") == {"A": "value"}


def test_parse_secret_with_ampersand_unaffected(runner):
    assert runner.parse_env_file(f"CONN={SECRET}\n") == {"CONN": SECRET}


# ---------------------------------------------------------------------------
# build_environment — merge precedence (existing env wins)
# ---------------------------------------------------------------------------


def test_build_environment_merges_and_base_wins(runner, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=from_env\nNEW=added\n", encoding="utf-8")
    merged = runner.build_environment(env_file, {"A": "from_base", "KEEP": "yes"})
    assert merged["A"] == "from_base"  # existing env wins, matching load_dotenv default
    assert merged["NEW"] == "added"
    assert merged["KEEP"] == "yes"


# ---------------------------------------------------------------------------
# run — exec seam, exit codes, no secret leakage
# ---------------------------------------------------------------------------


def test_run_execs_command_with_loaded_env(runner, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={SECRET}\n", encoding="utf-8")
    fake = _Exec()
    rc = runner.run(
        ["--env-file", str(env_file), "--", "make", "verify"],
        base_env={"PATH": "/usr/bin"},
        executor=fake,
    )
    assert rc == 0
    file, args, env = fake.calls[0]
    assert file == "make"
    assert args == ["make", "verify"]
    assert env["DATABASE_URL"] == SECRET


def test_run_usage_error_when_no_command(runner, tmp_path):
    rc = runner.run(["--env-file", str(tmp_path / ".env")], executor=_Exec())
    assert rc == 2


def test_run_missing_env_file(runner, tmp_path):
    rc = runner.run(["--env-file", str(tmp_path / "absent.env"), "echo", "hi"], executor=_Exec())
    assert rc == 1


def test_run_command_not_found(runner, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n", encoding="utf-8")

    def boom(file, args, env):
        raise FileNotFoundError(file)

    rc = runner.run(["--env-file", str(env_file), "definitely-not-a-real-cmd"], executor=boom)
    assert rc == 127


def test_run_never_prints_secret_value(runner, tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={SECRET}\n", encoding="utf-8")
    runner.run(["--env-file", str(env_file), "make", "verify"], base_env={}, executor=_Exec())
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err
