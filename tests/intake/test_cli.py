# ABOUTME: Tests for scripts/intake.py — the queue, displaced, backfill and labels verbs and exit codes.
# ABOUTME: GitHub is replaced by injected fakes; the setup shell is run end to end against a stub gh.

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from oversteward.board.config import RepoRef
from oversteward.intake.github import GhError

from .conftest import gh_row

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_cli():
    path = REPO_ROOT / "scripts" / "intake.py"
    spec = importlib.util.spec_from_file_location("oversteward_intake_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cli = _load_cli()

AG = RepoRef("aigranthelper", "NathanKrupa/aigranthelper")
OS = RepoRef("oversteward", "NathanKrupa/OverSteward")


class FakeGitHub:
    def __init__(self, issues: dict[str, list[dict]], *, broken: frozenset[str] = frozenset()):
        self.issues = issues
        self.broken = broken
        self.added: list[tuple] = []
        self.upserted: list[tuple] = []

    def list_issues(self, full_name):
        if full_name in self.broken:
            raise GhError(f"gh failed for {full_name}")
        return self.issues.get(full_name, [])

    def add_labels(self, full_name, number, labels):
        self.added.append((full_name, number, tuple(labels)))

    def upsert_label(self, full_name, spec):
        self.upserted.append((full_name, spec.name))


def _deps(fake, repos=(AG, OS)):
    return cli.Deps(
        repos=list(repos),
        list_issues=fake.list_issues,
        add_labels=fake.add_labels,
        upsert_label=fake.upsert_label,
    )


AG_ISSUES = [
    gh_row(10, title="Refactor settings", labels=("ready-for-agent",)),
    gh_row(11, title="Pantry user cannot save", labels=("ready-for-agent", "tribe")),
    gh_row(12, title="Checkout breaks", labels=("bug",)),
]


# --- displaced -------------------------------------------------------------


def test_displaced_prints_the_ready_tribe_issue_and_exits_zero(capsys):
    fake = FakeGitHub({AG.full_name: AG_ISSUES})
    assert cli.main(["displaced", "aigranthelper", "10"], deps=_deps(fake)) == 0
    out = capsys.readouterr().out
    assert "#11" in out and "Pantry user cannot save" in out


def test_displaced_for_a_tribe_target_names_nothing(capsys):
    fake = FakeGitHub({AG.full_name: AG_ISSUES})
    assert cli.main(["displaced", "aigranthelper", "11"], deps=_deps(fake)) == 0
    assert "0 ready tribe issues displaced" in capsys.readouterr().out


def test_displaced_exits_one_when_the_target_is_not_open(capsys):
    fake = FakeGitHub({AG.full_name: AG_ISSUES})
    assert cli.main(["displaced", "aigranthelper", "99"], deps=_deps(fake)) == 1
    assert "#99" in capsys.readouterr().err


def test_displaced_exits_one_when_github_cannot_be_read():
    fake = FakeGitHub({}, broken=frozenset({AG.full_name}))
    assert cli.main(["displaced", "aigranthelper", "10"], deps=_deps(fake)) == 1


def test_an_unknown_repo_exits_two(capsys):
    fake = FakeGitHub({})
    assert cli.main(["displaced", "nope", "1"], deps=_deps(fake)) == 2
    assert "nope" in capsys.readouterr().err


# --- queue -----------------------------------------------------------------


def test_queue_prints_tribe_first(capsys):
    fake = FakeGitHub({AG.full_name: AG_ISSUES})
    assert cli.main(["queue", "aigranthelper"], deps=_deps(fake)) == 0
    out = capsys.readouterr().out
    assert out.index("#11") < out.index("#10")
    assert "#12" not in out


def test_an_empty_queue_says_so_with_a_count(capsys):
    fake = FakeGitHub({AG.full_name: []})
    assert cli.main(["queue", "aigranthelper"], deps=_deps(fake)) == 0
    assert "0" in capsys.readouterr().out


# --- backfill --------------------------------------------------------------


def test_backfill_is_a_dry_run_by_default(tmp_path):
    fake = FakeGitHub({AG.full_name: AG_ISSUES, OS.full_name: [gh_row(1, labels=("kaizen",))]})
    out = tmp_path / "report.md"
    assert cli.main(["backfill", "--out", str(out)], deps=_deps(fake)) == 0
    assert fake.added == []
    text = out.read_text(encoding="utf-8")
    assert "Checkout breaks" in text and "oversteward" in text


def test_backfill_apply_adds_the_planned_labels(tmp_path):
    fake = FakeGitHub({AG.full_name: AG_ISSUES, OS.full_name: [gh_row(1, labels=("kaizen",))]})
    code = cli.main(["backfill", "--apply", "--out", str(tmp_path / "r.md")], deps=_deps(fake))
    assert code == 0
    assert (AG.full_name, 12, ("tribe",)) in fake.added
    assert (OS.full_name, 1, ("agent-finding",)) in fake.added


def test_backfill_refuses_a_partial_read(tmp_path):
    fake = FakeGitHub({AG.full_name: AG_ISSUES}, broken=frozenset({OS.full_name}))
    out = tmp_path / "r.md"
    assert cli.main(["backfill", "--apply", "--out", str(out)], deps=_deps(fake)) == 1
    assert fake.added == []
    assert not out.exists()


def test_backfill_with_no_targets_exits_two(tmp_path):
    fake = FakeGitHub({})
    assert cli.main(["backfill", "--out", str(tmp_path / "r.md")], deps=_deps(fake, repos=())) == 2


# --- labels ----------------------------------------------------------------


def test_labels_upserts_the_taxonomy_on_every_target():
    fake = FakeGitHub({})
    assert cli.main(["labels"], deps=_deps(fake)) == 0
    assert (OS.full_name, "tribe") in fake.upserted
    assert (AG.full_name, "shelved") in fake.upserted


def test_labels_exits_one_when_an_upsert_fails(capsys):
    fake = FakeGitHub({})

    def fail(full_name, spec):
        raise GhError("HTTP 403")

    deps = _deps(fake)
    deps = cli.Deps(deps.repos, deps.list_issues, deps.add_labels, fail)
    assert cli.main(["labels"], deps=deps) == 1
    assert "HTTP 403" in capsys.readouterr().err


# --- the setup shell, end to end against a stub gh --------------------------


def test_the_setup_shell_upserts_the_intake_labels_on_every_dispatch_target(tmp_path):
    log = tmp_path / "gh.log"
    stub = tmp_path / "gh"
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n', encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PYTHON": sys.executable,
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "orchestration" / "setup_dispatch_labels.sh")],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    for repo in cli.registry_repos():
        for name in ("tribe", "agent-finding", "shelved"):
            assert any(
                c.startswith(f"label create {name} ") and f"--repo {repo.full_name} " in c
                for c in calls
            ), (repo.full_name, name)


@pytest.mark.parametrize("repo_id", ["oversteward", "aigranthelper", "grantspider"])
def test_the_registry_repos_include_oversteward_and_the_product_repos(repo_id):
    assert repo_id in {repo.id for repo in cli.registry_repos()}


def test_oversteward_is_covered_even_when_it_is_not_a_dispatch_target():
    registry = {
        "contexts": [
            {"id": "oversteward", "repo": "https://github.com/NathanKrupa/OverSteward.git"},
            {"id": "fiscus", "repo": "https://github.com/NathanKrupa/fiscus.git",
             "dispatch_target": True},
        ]
    }
    assert [r.full_name for r in cli.repos_for(registry)] == [
        "NathanKrupa/fiscus", "NathanKrupa/OverSteward",
    ]


def test_oversteward_is_not_listed_twice_when_it_is_a_dispatch_target():
    registry = {
        "contexts": [
            {"id": "oversteward", "repo": "https://github.com/NathanKrupa/OverSteward.git",
             "dispatch_target": True},
        ]
    }
    assert [r.id for r in cli.repos_for(registry)] == ["oversteward"]
