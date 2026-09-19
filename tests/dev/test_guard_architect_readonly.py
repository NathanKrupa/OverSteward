# ABOUTME: Tests guard_architect_readonly — the architect card's read-only contract as a hook (OS#492).
# ABOUTME: Every write shape refused with exit 2; every read shape passes; the scratchpad is exempt.

"""The architect card said of itself "the read-only restriction is instruction,
not enforcement" — the inert-controls rule from `pr-workflow.md` written as a
confession. This hook is the enforcement, and these are the fixtures that make
it fire and the ones that must not.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "shared" / "scripts" / "dev" / "guard_architect_readonly.py"
DEPLOYED = REPO_ROOT / ".claude" / "hooks" / "guard_architect_readonly.py"
ARCHITECT_CARD = REPO_ROOT / "shared" / "agents" / "architect.md"

#: The scratchpad root the fixtures write into. The hook resolves targets
#: against the *resolved* root, so a tmp dir behind a symlink still counts.
SCRATCHPAD = "/scratch/session-1234/scratchpad"


def _load():
    spec = importlib.util.spec_from_file_location("guard_architect_readonly", CANONICAL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


guard = _load()


def _refusal(command: str, *, cwd: str = "/repo", scratchpad: str | None = SCRATCHPAD):
    environ = {"CLAUDE_SCRATCHPAD": scratchpad} if scratchpad else {}
    return guard.refusal(command, cwd=cwd, environ=environ)


# ---------------------------------------------------------------------------
# Write shapes — the issue's list, each refused.
# ---------------------------------------------------------------------------

GIT_WRITES = [
    "git commit -m x",
    "git push origin feat/x",
    "git add -p",
    "git add .",
    "git checkout -b feat/x",
    "git checkout master",
    "git checkout -- README.md",
    "git switch -c feat/x",
    "git switch master",
    "git rebase master",
    "git merge --ff-only origin/master",
    "git stash",
    "git stash pop",
    "git worktree add /tmp/wt master",
    "git worktree remove /tmp/wt",
    "git reset --hard HEAD~1",
    "git restore README.md",
    "git clean -fd",
    "git rm README.md",
    "git mv a b",
    "git cherry-pick abc123",
    "git revert HEAD",
    "git branch feat/x",
    "git branch -D feat/x",
    "git branch -m old new",
    "git tag v1.0",
    "git tag -d v1.0",
    "git remote add up https://example.invalid/r.git",
    "git config user.email x@example.invalid",
    "git pull origin master",
    "git fetch origin",
    "git -C /home/natha/OverSteward commit -m x",
    "git --no-pager -c core.editor=true commit -m x",
    "git diff --output=/tmp/patch.diff",
    "git notes add -m x",
    "git apply fix.patch",
    "git am fix.mbox",
    "git submodule update --init",
    "git update-ref refs/heads/master abc123",
]

GH_WRITES = [
    "gh pr create --title x --body y",
    "gh pr edit 1 --body y",
    "gh pr close 1",
    "gh pr merge 1 --auto --merge",
    "gh pr comment 1 --body y",
    "gh pr ready 1",
    "gh pr review 1 --approve",
    "gh pr checkout 1",
    "gh issue create --title x",
    "gh issue edit 1 --add-label x",
    "gh issue close 1",
    "gh issue comment 1 --body y",
    "gh issue reopen 1",
    "gh api repos/o/r/issues -X POST -f title=x",
    "gh api --method PATCH repos/o/r/issues/1 -f state=closed",
    "gh api -X PUT repos/o/r/contents/x",
    "gh api -X DELETE repos/o/r/issues/comments/1",
    "gh api repos/o/r/issues -f title=x",
    "gh api repos/o/r/issues --input body.json",
    "gh api repos/o/r/issues -F title=@t.txt",
    # A GraphQL query is a POST with a body; the guard cannot tell it from a
    # mutation, and REST is the sanctioned read form.
    "gh api graphql -f query='query { viewer { login } }'",
    "gh label create x",
    "gh release create v1",
    "gh release download v1",
    "gh run download 1",
    "gh run cancel 1",
    "gh run rerun 1",
    "gh workflow run ci.yml",
    "gh repo clone o/r",
    "gh secret set X",
    "gh auth login",
]

FILE_WRITES = [
    "sed -i 's/a/b/' README.md",
    "sed -i.bak 's/a/b/' README.md",
    "sed --in-place 's/a/b/' README.md",
    "sed -ni 's/a/b/p' README.md",
    "sed -n 's/a/b/w out.txt' README.md",
    "sed 'w out.txt' README.md",
    "sed -e '1e rm x' README.md",
    "sed -f script.sed README.md",
    "awk '{print > \"out.txt\"}' README.md",
    "awk '{print | \"sh\"}' README.md",
    "awk 'BEGIN{system(\"rm x\")}'",
    "awk -f prog.awk README.md",
    "sort -o out.txt in.txt",
    "sort --output=out.txt in.txt",
    "rm README.md",
    "rm -rf build/",
    "mv a b",
    "cp README.md /home/natha/OverSteward/README.bak",
    "mkdir -p x",
    "touch x",
    "chmod +x x",
    "chown natha x",
    "ln -s a b",
    "patch -p1 < fix.patch",
    "truncate -s 0 x",
    "dd if=/dev/zero of=x",
    "install -m 755 a b",
    "rsync -a a/ b/",
    "tee out.txt",
    "cat x | tee /tmp/out.txt",
    "find . -name '*.pyc' -delete",
    "find . -name '*.py' -exec rm {} \\;",
    "find . -name '*.py' -execdir rm {} +",
    "find . -fprint out.txt",
    "ls | xargs rm",
    "ls | xargs -n 1 -I {} rm {}",
    "shred x",
    "unlink x",
]

BUILD_AND_RUN = [
    "uv sync",
    "uv sync --extra dev",
    "uv pip install requests",
    "uv run python x.py",
    "uv venv",
    "uv add requests",
    "pip install requests",
    "pip3 install requests",
    "make",
    "make verify",
    "pytest",
    "pytest -q tests/",
    ".venv/bin/pytest",
    ".venv/bin/python -m pytest",
    "alembic upgrade head",
    "python x.py",
    "python3 -c \"open('x','w').write('y')\"",
    ".venv/bin/python -c 'print(1)'",
    "perl -i -pe 's/a/b/' x",
    "node x.js",
    "ruby x.rb",
    "npm install",
    "npx prettier --write x",
    "tox",
    "nox",
    "poetry install",
    "bash script.sh",
    "sh script.sh",
    "source setup.sh",
    ". setup.sh",
    "sleep 30",
]

REDIRECTS = [
    "echo x > notes.md",
    "echo x >> notes.md",
    "echo x >| notes.md",
    "cat a b > /tmp/joined.txt",
    "git log > /home/natha/OverSteward/log.txt",
    "git log &> log.txt",
    "git log 2> err.txt",
    "git log 1>out.txt",
    "git log >&out.txt",
    "cat <<EOF > notes.md\nhello\nEOF",
    "echo x > ../outside.md",
    f"echo x > {SCRATCHPAD}/../escaped.md",
    "echo x > $(mktemp)",
    "echo x > $UNSET_VARIABLE_XYZ/notes.md",
    "echo x > \"$HOME/notes.md\"",
    "echo x > ~/notes.md",
    "echo x <> notes.md",
]

# The guard reads the whole command, not its first token: a write hidden after
# a read, inside a substitution, inside a nested shell, or inside a group.
COMPOUND = [
    "cat x; git commit -m y",
    "git log; git push",
    "git log && git push",
    "git log || git push",
    "cat x | tee y",
    "cat x & git commit -m y",
    "echo $(git commit -m y)",
    'echo "$(git commit -m y)"',
    "echo `git commit -m y`",
    "bash -c 'git commit -m y'",
    "sh -c \"git log; git commit -m y\"",
    "bash -c 'bash -c \"git commit -m y\"'",
    "eval git commit -m y",
    "eval 'git commit -m y'",
    "env git commit -m y",
    "command git commit -m y",
    "exec git commit -m y",
    "nohup git commit -m y",
    "time git commit -m y",
    "timeout 30 git commit -m y",
    "sudo rm x",
    "FOO=bar git commit -m y",
    "cd /repo && git commit -m y",
    "(git commit -m y)",
    "{ git commit -m y; }",
    "if true; then git commit -m y; fi",
    "for f in a b; do rm $f; done",
    "while true; do git push; done",
    "! git commit -m y",
    "git log\ngit commit -m y",
    "git log \\\n  ; git commit -m y",
    # A quoted mention in the *argument* of a write is still a write.
    'git commit -m "docs: never run git commit here"',
    # Unbalanced quoting is evaluated, never waved through.
    "git commit -m 'unclosed",
    "echo 'unclosed > notes.md",
    # A write behind an unsupported case statement is still found.
    "case x in x) git commit -m y;; esac",
    # A shell keyword does not launder the command after it.
    "then git commit -m y",
    "do git commit -m y",
]

# ---------------------------------------------------------------------------
# Read shapes — the card's sanctioned forms, each allowed.
# ---------------------------------------------------------------------------

GIT_READS = [
    "git log --oneline -3",
    "git -C /home/natha/OverSteward log --oneline -3",
    "git --no-pager log",
    "git -c color.ui=never log",
    "git show HEAD:README.md",
    "git show origin/master:registry.yaml",
    "git diff origin/master...HEAD --stat",
    "git diff",
    "git grep -n 'pattern' -- '*.py'",
    "git grep -n '>' -- '*.md'",
    "git ls-tree origin/master scripts/dev/",
    "git ls-files",
    "git ls-remote --heads origin",
    "git rev-parse --show-toplevel",
    "git rev-parse --abbrev-ref HEAD",
    "git status --porcelain",
    "git status",
    "git blame README.md",
    "git cat-file -p HEAD",
    "git describe --tags",
    "git shortlog -sn",
    "git rev-list --count HEAD",
    "git branch",
    "git branch -a",
    "git branch --list 'feat/*'",
    "git branch --show-current",
    "git branch -vv",
    "git branch --contains abc123",
    "git branch -r --merged master",
    "git tag",
    "git tag -l 'v*'",
    "git tag --list",
    "git stash list",
    "git stash show -p stash@{0}",
    "git worktree list",
    "git remote",
    "git remote -v",
    "git remote show origin",
    "git remote get-url origin",
    "git config --get user.email",
    "git config --get-all remote.origin.fetch",
    "git config -l",
    "git config --list",
    "git reflog",
    "git reflog show master",
    "git notes list",
    "git notes show HEAD",
    "git submodule status",
    "git merge-base master HEAD",
    "git for-each-ref refs/heads/",
    "git show-ref",
    "git check-ignore -q .venv",
    "git name-rev HEAD",
    "git range-diff a...b c...d",
    "git count-objects -v",
    "git version",
    "git --version",
    "git help log",
    "git log | head -5",
    "git log --oneline -3 2>&1",
    "git log 2>/dev/null",
    "git log > /dev/null",
    "git log 2>&1 >/dev/null",
]

GH_READS = [
    "gh issue view 492 --repo NathanKrupa/OverSteward --comments",
    "gh pr view 1 --repo NathanKrupa/OverSteward",
    "gh pr diff 1 --repo NathanKrupa/OverSteward",
    "gh pr list --state open --json number,title",
    "gh pr checks 1",
    "gh pr status",
    "gh issue list --label ready-for-agent",
    "gh issue status",
    "gh run list --limit 5",
    "gh run view 1 --log",
    "gh workflow list",
    "gh workflow view ci.yml",
    "gh label list",
    "gh release list",
    "gh release view v1",
    "gh repo view NathanKrupa/OverSteward",
    "gh secret list",
    "gh variable list",
    "gh cache list",
    "gh auth status",
    "gh status",
    "gh search issues 'hook' --repo NathanKrupa/OverSteward",
    "gh search prs 'hook'",
    "gh api repos/NathanKrupa/OverSteward/issues/492",
    "gh api repos/NathanKrupa/OverSteward/issues/492 --jq .title",
    "gh api -X GET repos/NathanKrupa/OverSteward/issues/492",
    "gh api --method GET repos/NathanKrupa/OverSteward/issues/492",
    "gh api --method=GET repos/NathanKrupa/OverSteward/issues/492",
    "gh api -X HEAD repos/NathanKrupa/OverSteward",
    "gh api --paginate repos/NathanKrupa/OverSteward/issues",
    "gh --version",
    "gh version",
    "gh help pr",
    "gh pr --help",
    "gh pr",
    "gh pr view 1 2>&1 | tail -20",
    # An argument that merely mentions a write verb is not a write.
    "gh issue view 492 --repo NathanKrupa/OverSteward --json title --jq '.title' | grep create",
]

TEXT_READS = [
    "cat README.md",
    "cat a b",
    "head -20 README.md",
    "tail -n 40 README.md",
    "tail -f /var/log/syslog",
    "sed -n '1,40p' README.md",
    "sed -n '/^## Scope/,/^## /p' README.md",
    "sed -n 's/^version: //p' pyproject.toml",
    "sed -e '1,5p' -n README.md",
    "sed 's/a/b/g' README.md",
    "sed -n '/we /p' README.md",
    "grep -n 'pattern' README.md",
    "grep -rn --include='*.py' 'def main' src/",
    "grep '>' README.md",
    "grep '>>' README.md",
    "grep -c '2>&1' README.md",
    "grep -n 'git commit' documentation/",
    "rg -n 'pattern' src/",
    "rg --files",
    "find . -name '*.py'",
    "find . -name '*.py' -exec grep -l main {} +",
    "find . -name '*.py' -exec cat {} \\;",
    "find . -type f -newer README.md -print",
    "ls -la",
    "ls .claude/hooks/",
    "tree -L 2 src/",
    "wc -l README.md",
    "cat plan.md | wc -l",
    "echo \"$plan\" | wc -l",
    "sort README.md | uniq -c",
    "cut -d: -f1 /etc/hosts",
    "tr a-z A-Z",
    "diff a b",
    "cmp a b",
    "file README.md",
    "stat README.md",
    "du -sh .",
    "df -h",
    "pwd",
    "echo hello",
    "printf '%s\\n' hello",
    "true",
    "test -f README.md",
    "[ -f README.md ] && echo yes",
    "[[ -f README.md ]] && echo yes",
    "basename /a/b",
    "dirname /a/b",
    "realpath .",
    "readlink -f .venv",
    "which python3",
    "type git",
    "date",
    "jq '.title' issue.json",
    "jq -r '.[] | .name' < issues.json",
    "cat README.md | jq -R .",
    "awk '{print $1}' README.md",
    "awk -F: '{print $1}' /etc/passwd",
    "awk -F'|' '{print $2}' table.md",
    "awk '$3 > 100 {print $1}' data.txt",
    "awk 'NR==5' README.md",
    "awk -v n=5 'NR==n' README.md",
    "uv pip list",
    "uv pip show requests",
    "uv pip freeze",
    "pip list",
    "pip show requests",
    "pip freeze",
    "nl README.md",
    "tac README.md",
    "sha256sum README.md",
    "uname -a",
    "whoami",
    "ps aux",
    "cd /home/natha/OverSteward && git log --oneline -3",
    "cd /home/natha/OverSteward; git status",
    "FOO=bar git log",
    "FOO=bar",
    "export FOO=bar",
    "cat <<'EOF'\ngit commit -m x\nEOF",
    "cat <<EOF | wc -l\nline\nEOF",
    "x=$(git log --oneline -3); echo \"$x\"",
    "echo `git rev-parse HEAD`",
    "echo \"$(git rev-parse HEAD)\"",
    "bash -c 'git log --oneline -3'",
    "sh -c \"cat README.md | wc -l\"",
    "eval git log",
    "env git log",
    "timeout 30 git log",
    "time git log",
    "if [ -f x ]; then cat x; fi",
    "for f in a b; do cat $f; done",
    "while read -r line; do echo \"$line\"; done < README.md",
    "case x in x) echo x;; esac",
    "! grep -q pattern README.md",
    "git log # git commit -m x",
    "ls | xargs wc -l",
    "ls | xargs -n 1 -I {} cat {}",
    "ls | xargs",
    "cat README.md | tee /dev/stderr",
    "cat README.md | tee /dev/null",
    "echo x > /dev/null",
    "echo x >/dev/stderr",
    "echo x 2>&1",
    "echo x 1>&2",
    "echo x >&2",
    "cat README.md 2>&-",
    "cat < README.md",
    "wc -l <<< \"$plan\"",
    "grep -n 'print > \"out\"' README.md",
]

SCRATCHPAD_WRITES = [
    "echo x > $CLAUDE_SCRATCHPAD/notes.md",
    "echo x >> $CLAUDE_SCRATCHPAD/notes.md",
    "echo x > \"$CLAUDE_SCRATCHPAD/notes.md\"",
    "echo x > ${CLAUDE_SCRATCHPAD}/notes.md",
    f"echo x > {SCRATCHPAD}/notes.md",
    f"echo x >> {SCRATCHPAD}/plan.md",
    f"git log &> {SCRATCHPAD}/log.txt",
    f"git log 2> {SCRATCHPAD}/err.txt",
    f"cat plan.md | tee {SCRATCHPAD}/plan.md",
    f"cat <<'EOF' > {SCRATCHPAD}/plan.md\nplan\nEOF",
    f"cd {SCRATCHPAD} && echo x > notes.md",
    f"sort -o {SCRATCHPAD}/sorted.txt in.txt",
]


class TestWriteShapesAreRefused:
    @pytest.mark.parametrize("command", GIT_WRITES)
    def test_a_git_mutation_is_refused(self, command):
        assert _refusal(command), command

    @pytest.mark.parametrize("command", GH_WRITES)
    def test_a_gh_mutation_is_refused(self, command):
        assert _refusal(command), command

    @pytest.mark.parametrize("command", FILE_WRITES)
    def test_a_file_write_is_refused(self, command):
        assert _refusal(command), command

    @pytest.mark.parametrize("command", BUILD_AND_RUN)
    def test_a_build_run_or_interpreter_is_refused(self, command):
        assert _refusal(command), command

    @pytest.mark.parametrize("command", REDIRECTS)
    def test_a_redirection_outside_the_scratchpad_is_refused(self, command):
        assert _refusal(command), command

    @pytest.mark.parametrize("command", COMPOUND)
    def test_a_write_anywhere_in_a_compound_command_is_refused(self, command):
        assert _refusal(command), command

    def test_the_reason_is_one_line_and_names_the_act(self):
        reason = _refusal("cat x; git commit -m y")
        assert reason and "\n" not in reason
        assert "git commit" in reason


class TestReadShapesPass:
    @pytest.mark.parametrize("command", GIT_READS)
    def test_a_git_read_passes(self, command):
        assert _refusal(command) is None, _refusal(command)

    @pytest.mark.parametrize("command", GH_READS)
    def test_a_gh_read_passes(self, command):
        assert _refusal(command) is None, _refusal(command)

    @pytest.mark.parametrize("command", TEXT_READS)
    def test_a_text_read_passes(self, command):
        assert _refusal(command) is None, _refusal(command)

    def test_the_allowed_lists_are_not_trivially_satisfied(self):
        """A guard that never fires would pass every read fixture."""
        assert all(_refusal(c) for c in GIT_WRITES + GH_WRITES + FILE_WRITES)


class TestScratchpadExemption:
    @pytest.mark.parametrize("command", SCRATCHPAD_WRITES)
    def test_a_write_into_the_scratchpad_passes(self, command):
        assert _refusal(command, cwd=SCRATCHPAD) is None, _refusal(command, cwd=SCRATCHPAD)

    def test_the_exemption_is_the_scratchpad_not_every_redirect(self):
        """The mutant: every `>` refused, so the card cannot count its own output."""
        assert _refusal("echo x > $CLAUDE_SCRATCHPAD/notes.md") is None
        assert _refusal("echo x > /home/natha/notes.md")

    def test_a_relative_target_resolves_against_the_commands_cwd(self):
        assert _refusal("echo x > notes.md", cwd=SCRATCHPAD) is None
        assert _refusal("echo x > notes.md", cwd="/home/natha/OverSteward")

    def test_the_harness_tmpdir_is_the_fallback_root(self):
        """No harness variable names the scratchpad; every session's lives under CLAUDE_CODE_TMPDIR."""
        environ = {"CLAUDE_CODE_TMPDIR": "/home/natha/.claude/tmp"}
        under = "/home/natha/.claude/tmp/claude-1000/-home-natha-OverSteward/s/scratchpad/n.md"
        assert guard.refusal(f"echo x > {under}", cwd="/repo", environ=environ) is None
        assert guard.refusal("echo x > /home/natha/n.md", cwd="/repo", environ=environ)

    def test_with_no_root_configured_the_home_tmp_is_used(self):
        home_tmp = Path.home() / ".claude" / "tmp" / "s" / "scratchpad" / "n.md"
        assert guard.refusal(f"echo x > {home_tmp}", cwd="/repo", environ={}) is None
        assert guard.refusal("echo x > /home/natha/n.md", cwd="/repo", environ={})

    def test_an_unset_scratchpad_variable_is_not_expanded_to_anything_safe(self):
        assert _refusal("echo x > $CLAUDE_SCRATCHPAD/notes.md", scratchpad=None)

    def test_a_symlinked_scratchpad_is_resolved(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        environ = {"CLAUDE_SCRATCHPAD": str(link)}
        assert guard.refusal(f"echo x > {real}/n.md", cwd="/repo", environ=environ) is None
        assert guard.refusal(f"echo x > {link}/n.md", cwd="/repo", environ=environ) is None


class TestHookProtocol:
    def _run(self, payload, env_extra=None):
        return subprocess.run(
            [sys.executable, str(DEPLOYED)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **(env_extra or {})},
        )

    def test_a_write_exits_two_with_a_one_line_reason(self):
        result = self._run({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}})
        assert result.returncode == 2
        assert result.stderr.count("\n") == 1
        assert "read-only" in result.stderr and "git commit" in result.stderr

    def test_a_compound_command_is_read_whole(self):
        result = self._run({"tool_name": "Bash", "tool_input": {"command": "cat x; git commit -m y"}})
        assert result.returncode == 2

    def test_a_read_exits_zero(self):
        result = self._run({"tool_name": "Bash", "tool_input": {"command": "git log --oneline -3"}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_a_scratchpad_redirect_exits_zero(self, tmp_path):
        result = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "echo x > $CLAUDE_SCRATCHPAD/notes.md"}},
            env_extra={"CLAUDE_SCRATCHPAD": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr

    def test_the_events_cwd_is_what_a_relative_target_resolves_against(self, tmp_path):
        result = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "echo x > notes.md"}, "cwd": str(tmp_path)},
            env_extra={"CLAUDE_SCRATCHPAD": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr

    def test_a_non_bash_tool_is_ignored(self):
        result = self._run({"tool_name": "Read", "tool_input": {"command": "git commit -m x"}})
        assert result.returncode == 0

    def test_unparseable_input_does_not_block(self):
        result = subprocess.run(
            [sys.executable, str(DEPLOYED)], input="not json",
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0

    def test_there_is_no_override_variable(self):
        """A read-only card with an escape hatch is a dispatch agent with extra steps."""
        source = CANONICAL.read_text(encoding="utf-8")
        assert "CLAUDE_ALLOW" not in source


class TestWiring:
    def test_canonical_and_deployed_are_byte_identical(self):
        assert CANONICAL.read_bytes() == DEPLOYED.read_bytes()

    def test_the_architect_card_names_the_hook_for_pretooluse_bash(self):
        """A hook script that exists but is not named in the card's frontmatter enforces nothing.

        The frontmatter is parsed, not grepped: the settings.json hook shape
        nests a second ``hooks:`` key under every matcher, so a substring check
        stays green when the top-level key is renamed away (mutation pass).
        """
        text = ARCHITECT_CARD.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(text.split("---\n", 2)[1])
        matchers = frontmatter["hooks"]["PreToolUse"]
        bash = [entry for entry in matchers if entry.get("matcher") == "Bash"]
        assert bash, f"no PreToolUse matcher for Bash in {matchers!r}"
        commands = [hook["command"] for entry in bash for hook in entry["hooks"]]
        assert any(
            hook.get("type") == "command" for entry in bash for hook in entry["hooks"]
        )
        assert any(".claude/hooks/guard_architect_readonly.py" in command for command in commands), (
            commands
        )

    def test_the_card_no_longer_calls_its_rule_unenforced(self):
        text = ARCHITECT_CARD.read_text(encoding="utf-8")
        assert "instruction, not enforcement" not in text
        assert "no hook refuses a write under this card" not in text
