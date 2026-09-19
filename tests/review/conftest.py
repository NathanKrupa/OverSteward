# ABOUTME: Throwaway git repositories the review probes and the assembler are exercised against.
# ABOUTME: A deleting branch is the flagship case, so it is a shared fixture rather than a copy.

from __future__ import annotations

import subprocess

import pytest


def _git(root, *args) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo_deleting_a_test(tmp_path):
    """A repo whose branch deletes a test module — the GS `b14cb9b4` shape.

    The deleted test is the reviewable material: it is the thing that could
    have failed, and the diff removed it. A probe that can only read the
    working tree cannot see it at all.
    """
    root = tmp_path / "deleting"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "CLAUDE.md").write_text("# doctrine\n", encoding="utf-8")
    (root / "safe_http.py").write_text(
        "def safe_get(url):\n    return check(url)\n", encoding="utf-8"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_safe_http.py").write_text(
        "def test_a_blocked_url_never_reaches_httpx():\n    assert False\n", encoding="utf-8"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    _git(root, "checkout", "-qb", "feature")
    _git(root, "rm", "-q", "tests/test_safe_http.py")
    (root / "safe_http.py").write_text(
        "def safe_get(url):\n    return fetch(url)\n", encoding="utf-8"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "drop the sink and its tests")
    return root
