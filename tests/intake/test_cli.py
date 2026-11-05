# ABOUTME: Tests for scripts/intake.py — the queue, displaced, backfill and labels verbs and exit codes.
# ABOUTME: GitHub is replaced by injected fakes; the setup shell is run end to end against a stub gh.

from __future__ import annotations

import dataclasses
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
    def __init__(
        self,
        issues: dict[str, list[dict]],
        *,
        broken: frozenset[str] = frozenset(),
        comments: dict[int, list[str]] | None = None,
        failing_comment: int | None = None,
    ):
        self.issues = issues
        self.broken = broken
        self.comments = comments or {}
        self.failing_comment = failing_comment
        self.added: list[tuple] = []
        self.upserted: list[tuple] = []
        self.posted: list[tuple] = []

    def list_issues(self, full_name):
        if full_name in self.broken:
            raise GhError(f"gh failed for {full_name}")
        return self.issues.get(full_name, [])

    def add_labels(self, full_name, number, labels):
        self.added.append((full_name, number, tuple(labels)))

    def upsert_label(self, full_name, spec):
        self.upserted.append((full_name, spec.name))

    def issue_comments(self, full_name, number):
        if full_name in self.broken:
            raise GhError(f"gh failed for {full_name}")
        return self.comments.get(number, [])

    def comment_issue(self, full_name, number, body):
        if number == self.failing_comment:
            raise GhError("HTTP 403")
        self.posted.append((full_name, number, body))


def _deps(fake, repos=(AG, OS)):
    return cli.Deps(
        repos=list(repos),
        list_issues=fake.list_issues,
        add_labels=fake.add_labels,
        upsert_label=fake.upsert_label,
        issue_comments=fake.issue_comments,
        comment_issue=fake.comment_issue,
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


# --- line ------------------------------------------------------------------

GS = RepoRef("grantspider", "NathanKrupa/grantspider")
RED_ROW = gh_row(9, title="ci is red on PR #120", labels=("ci-red", "agent-finding"))
PLAIN_ROW = gh_row(4, title="Tidy settings", labels=("ready-for-agent",))


def _line(argv, fake, capsys):
    code = cli.main(["line", *argv], deps=_deps(fake, repos=(GS,)))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_line_allows_a_plain_issue_on_a_clear_line(capsys):
    code, out = _line(["grantspider", "4"], FakeGitHub({GS.full_name: [PLAIN_ROW]}), capsys)
    assert code == 0
    assert "allowed" in out


def test_line_refuses_another_issue_while_ci_red_is_open_and_names_it(capsys):
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW]})
    code, out = _line(["grantspider", "4"], fake, capsys)
    assert code == 2
    assert "Line stopped: grantspider#9" in out
    assert "allowed" not in out


def test_line_allows_the_ci_red_issue_itself(capsys):
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW]})
    assert _line(["grantspider", "9"], fake, capsys)[0] == 0


def test_line_allows_an_issue_whose_comment_declares_the_fix(capsys):
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW]}, comments={4: ["Closes #9"]})
    assert _line(["grantspider", "4"], fake, capsys)[0] == 0


def test_line_refuses_a_false_fix(capsys):
    other = gh_row(5, title="not red")
    false_fix = gh_row(4, labels=("ready-for-agent",), body="Closes #5")
    fake = FakeGitHub({GS.full_name: [false_fix, other, RED_ROW]})
    code, out = _line(["grantspider", "4"], fake, capsys)
    assert code == 2 and "allowed" not in out


def test_line_exits_one_and_never_says_allowed_when_github_cannot_be_read(capsys):
    fake = FakeGitHub({}, broken=frozenset({GS.full_name}))
    code, out = _line(["grantspider", "4"], fake, capsys)
    assert code == 1
    assert "allowed" not in out


def test_line_exits_one_when_the_target_is_not_open(capsys):
    code, out = _line(["grantspider", "77"], FakeGitHub({GS.full_name: [RED_ROW]}), capsys)
    assert code == 1
    assert "#77" in out and "allowed" not in out


def test_line_exits_two_for_an_unknown_repo(capsys):
    code, out = _line(["nope", "4"], FakeGitHub({}), capsys)
    assert code == 2 and "allowed" not in out


def test_line_refuses_while_dispatch_paused_even_for_the_ci_red_issue(capsys):
    paused = gh_row(2, title="hold", labels=("dispatch-paused",))
    fake = FakeGitHub({GS.full_name: [RED_ROW, paused]})
    code, out = _line(["grantspider", "9"], fake, capsys)
    assert code == 2
    assert "grantspider#2" in out and "allowed" not in out


def test_line_override_records_a_comment_on_every_open_ci_red_issue_then_allows(capsys):
    red2 = gh_row(10, title="ci is red on PR #121", labels=("ci-red",))
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW, red2]})
    code, out = _line(["grantspider", "4", "--override", "flake on the runner"], fake, capsys)
    assert code == 0
    body = "LINE OVERRIDE: dispatching grantspider#4 \u2014 flake on the runner"
    assert fake.posted == [(GS.full_name, 9, body), (GS.full_name, 10, body)]


def test_line_override_refuses_when_its_comment_fails(capsys):
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW]}, failing_comment=9)
    code, out = _line(["grantspider", "4", "--override", "flake"], fake, capsys)
    assert code == 2
    assert "allowed" not in out
    assert "HTTP 403" in out


def test_line_override_refuses_a_blank_reason_and_posts_nothing(capsys):
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW]})
    code, out = _line(["grantspider", "4", "--override", "   "], fake, capsys)
    assert code == 2
    assert fake.posted == [] and "allowed" not in out


def test_line_override_does_not_lift_dispatch_paused(capsys):
    paused = gh_row(2, labels=("dispatch-paused",))
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW, paused]})
    code, out = _line(["grantspider", "4", "--override", "flake"], fake, capsys)
    assert code == 2
    assert fake.posted == [] and "allowed" not in out


def test_queue_prints_the_line_stopped_header_and_the_ci_red_issue_first(capsys):
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, RED_ROW]})
    assert cli.main(["queue", "grantspider"], deps=_deps(fake, repos=(GS,))) == 0
    out = capsys.readouterr().out
    assert out.startswith("LINE STOPPED")
    assert out.index("[ci-red] #9") < out.index("#4 ")


def test_queue_header_names_an_in_flight_ci_red_issue_the_queue_omits(capsys):
    in_flight = gh_row(9, title="ci is red on PR #120", labels=("ci-red", "agent-in-progress"))
    fake = FakeGitHub({GS.full_name: [PLAIN_ROW, in_flight]})
    assert cli.main(["queue", "grantspider"], deps=_deps(fake, repos=(GS,))) == 0
    out = capsys.readouterr().out
    assert out.startswith("LINE STOPPED")
    assert "#9 ci is red on PR #120" in out
    assert "[ci-red] #9" not in out


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


def test_backfill_only_tribe_applies_tribe_and_never_agent_finding(tmp_path):
    fake = FakeGitHub({AG.full_name: AG_ISSUES, OS.full_name: [gh_row(1, labels=("kaizen",))]})
    out = tmp_path / "r.md"
    code = cli.main(["backfill", "--only", "tribe", "--apply", "--out", str(out)], deps=_deps(fake))
    assert code == 0
    assert fake.added == [(AG.full_name, 12, ("tribe",))]
    assert "--only tribe" in out.read_text(encoding="utf-8")


def test_backfill_dry_run_hint_repeats_the_only_flags(tmp_path, capsys):
    fake = FakeGitHub({AG.full_name: AG_ISSUES})
    argv = ["backfill", "--only", "tribe", "--out", str(tmp_path / "r.md")]
    assert cli.main(argv, deps=_deps(fake)) == 0
    assert "Re-run with --only tribe --apply" in capsys.readouterr().out


def test_backfill_only_is_repeatable_and_both_classes_match_the_default(tmp_path):
    rows = {AG.full_name: AG_ISSUES, OS.full_name: [gh_row(1, labels=("kaizen",))]}
    both, default = FakeGitHub(rows), FakeGitHub(rows)
    argv = ["backfill", "--apply", "--out", str(tmp_path / "r.md")]
    assert cli.main([*argv, "--only", "tribe", "--only", "agent-finding"], deps=_deps(both)) == 0
    assert cli.main(argv, deps=_deps(default)) == 0
    assert both.added == default.added and default.added


def test_backfill_only_refuses_an_unknown_class(tmp_path, capsys):
    fake = FakeGitHub({})
    with pytest.raises(SystemExit):
        cli.main(["backfill", "--only", "bug", "--out", str(tmp_path / "r.md")], deps=_deps(fake))
    assert "invalid choice: 'bug'" in capsys.readouterr().err


def test_backfill_apply_exits_one_when_a_label_addition_fails(tmp_path, capsys):
    fake = FakeGitHub({AG.full_name: AG_ISSUES, OS.full_name: [gh_row(1, labels=("kaizen",))]})

    def add_labels(full_name, number, labels):
        fake.added.append((full_name, number, tuple(labels)))
        if number == 12:
            raise GhError("HTTP 422")

    deps = _deps(fake)
    deps = dataclasses.replace(deps, add_labels=add_labels)
    code = cli.main(["backfill", "--apply", "--out", str(tmp_path / "r.md")], deps=deps)
    assert code == 1
    assert "FAILED aigranthelper#12: HTTP 422" in capsys.readouterr().err
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
    deps = dataclasses.replace(deps, upsert_label=fail)
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
