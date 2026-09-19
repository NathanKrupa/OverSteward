# ABOUTME: Tests for scripts/estate_board.py — exit-code mapping and the page it writes.
# ABOUTME: The three exit codes are the contract: measured / could-not-look / misconfigured.

from __future__ import annotations

import importlib.util
from pathlib import Path

from oversteward.board.client import GhError
from oversteward.board.config import RepoRef, repos_from_registry

REPO_ROOT = Path(__file__).resolve().parents[2]

_EXIT_OK = 0
_EXIT_COULD_NOT_LOOK = 1
_EXIT_MISCONFIGURED = 2


def _module():
    spec = importlib.util.spec_from_file_location(
        "estate_board", REPO_ROOT / "scripts" / "estate_board.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_real_registry_declares_board_repos():
    module = _module()
    ids = [r.id for r in repos_from_registry(module.load_registry())]
    assert "grantspider" in ids and "aigranthelper" in ids and "oversteward" in ids


def test_misconfigured_when_no_repo_is_a_dispatch_target(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module, "repos_from_registry", lambda *_a, **_k: [])
    assert module.main(["--out", str(tmp_path / "b.html")]) == _EXIT_MISCONFIGURED
    assert not (tmp_path / "b.html").exists()


def test_could_not_look_when_gh_fails(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(
        module,
        "repos_from_registry",
        lambda *_a, **_k: [RepoRef("grantspider", "NathanKrupa/grantspider")],
    )

    def _explode(*_a, **_k):
        raise GhError("gh exited 1")

    monkeypatch.setattr(module, "read_estate", _explode)
    assert module.main(["--out", str(tmp_path / "b.html")]) == _EXIT_COULD_NOT_LOOK
    assert not (tmp_path / "b.html").exists()


def test_measured_answer_writes_the_page_and_names_what_it_read(monkeypatch, tmp_path, capsys):
    module = _module()
    from oversteward.board.models import Issue

    raw = {
        "number": 1,
        "title": "why?",
        "state": "OPEN",
        "body": "",
        "url": "https://github.com/NathanKrupa/grantspider/issues/1",
        "labels": [{"name": "needs-input"}],
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-10T00:00:00Z",
        "closedAt": None,
    }
    monkeypatch.setattr(
        module,
        "repos_from_registry",
        lambda *_a, **_k: [RepoRef("grantspider", "NathanKrupa/grantspider")],
    )
    monkeypatch.setattr(
        module,
        "read_estate",
        lambda *_a, **_k: {"grantspider": (Issue.from_gh("grantspider", raw),)},
    )
    out = tmp_path / "b.html"

    assert module.main(["--out", str(out)]) == _EXIT_OK

    assert "<title>Estate Board</title>" in out.read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    assert "1 repositories" in printed and "1 issues" in printed and "1 decisions" in printed
    assert "grantspider #1" in printed


def test_misconfigured_when_a_dispatch_target_has_no_github_url(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(
        module,
        "load_registry",
        lambda: {
            "contexts": [
                {"id": "x", "repo": "git@bitbucket.org:o/x.git", "dispatch_target": True},
            ]
        },
    )
    assert module.main(["--out", str(tmp_path / "b.html")]) == _EXIT_MISCONFIGURED
    assert not (tmp_path / "b.html").exists()
