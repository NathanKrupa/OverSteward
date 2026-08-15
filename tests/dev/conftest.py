# ABOUTME: Fixtures for the canonical format gates — a throwaway git repo and a stand-in formatter.
# ABOUTME: The stand-in keeps the gates testable in OverSteward, which installs no ruff.

from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

CANONICAL_DEV = Path(__file__).resolve().parents[2] / "shared" / "scripts" / "dev"

UNFORMATTED = "x  =  1\n"
FORMATTED = "x = 1\n"

# Normalises "  =  " to " = ", the same way ruff format normalises spacing, and
# records the files it was handed so a test can assert what was passed to it.
STAND_IN_FORMATTER = '''\
import json
import sys
from pathlib import Path

targets = []
for arg in sys.argv[1:]:
    if arg.startswith("-"):
        continue
    path = Path(arg)
    targets.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])

log = Path(__file__).with_suffix(".calls")
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps([str(target) for target in targets]) + "\\n")

for target in targets:
    target.write_text(
        target.read_text(encoding="utf-8").replace("  =  ", " = "), encoding="utf-8"
    )
'''


def load_dev_script(name: str):
    """Load a canonical ``shared/scripts/dev`` member by path, as deployed repos run it."""
    path = CANONICAL_DEV / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )


class Repo:
    """A disposable git repo, isolated from the developer's global git config."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, relpath: str, text: str) -> str:
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return relpath

    def read(self, relpath: str) -> str:
        return (self.root / relpath).read_text(encoding="utf-8")

    def stage(self, *relpaths: str) -> None:
        _git(self.root, "add", *relpaths)

    def commit(self, message: str = "test commit") -> None:
        _git(self.root, "commit", "--quiet", "-m", message)

    def commit_all(self, message: str = "test commit") -> None:
        _git(self.root, "add", "-A")
        self.commit(message)


class StandInFormatter:
    """The formatter seam under test control — no ruff, and every call is recorded."""

    def __init__(self, script: Path) -> None:
        self._script = script

    @property
    def command(self) -> str:
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(self._script))}"

    @property
    def calls(self) -> list[list[str]]:
        log = self._script.with_suffix(".calls")
        if not log.is_file():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    @property
    def formatted_paths(self) -> set[str]:
        return {path for call in self.calls for path in call}


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "config", "user.email", "gate@example.test")
    _git(root, "config", "user.name", "Format Gate Test")
    # Point hooks at a path that cannot exist, so a developer's global
    # core.hooksPath never runs against this throwaway repo.
    _git(root, "config", "core.hooksPath", str(root / ".no-hooks"))
    return Repo(root)


@pytest.fixture
def formatter(tmp_path: Path) -> StandInFormatter:
    # Lives outside the repo, so a whole-tree run never formats the tool itself.
    tools = tmp_path / "tools"
    tools.mkdir()
    script = tools / "stand_in_formatter.py"
    script.write_text(STAND_IN_FORMATTER, encoding="utf-8")
    return StandInFormatter(script)


def run_gate(script: str, repo: Repo, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a canonical gate against ``repo`` exactly as a deployed copy is run."""
    return subprocess.run(
        [sys.executable, str(CANONICAL_DEV / script), "--root", str(repo.root), *args],
        capture_output=True,
        text=True,
        cwd=str(repo.root),
    )
