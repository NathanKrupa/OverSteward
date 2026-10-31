# ABOUTME: Tests for the locations check — every claimed path must exist on the tree that is read.
# ABOUTME: "Could not look" (absent checkout, failed fetch, bad ref, nothing claimed) must never exit 0.

from __future__ import annotations

from pathlib import Path
from typing import Any

from oversteward.estate_map.checkouts import TreeReader, checkouts
from oversteward.estate_map.locations import check_locations
from oversteward.estate_map.model import parse
from oversteward.estate_map.outcome import EXIT_CLEAN, EXIT_COULD_NOT_LOOK, EXIT_FINDINGS

from .fake_git import FakeGit

OS_FILES = frozenset(
    {
        "src/oversteward/sow/plan.py",
        "src/oversteward/dev_family.py",
        "src/oversteward/estate_map/model.py",
    }
)
GS_FILES = frozenset({"src/grantspider/services/website_resolver.py"})


def _registry(gs_path: str | None) -> dict[str, Any]:
    gs: dict[str, Any] = {"id": "grantspider", "branch": "staging", "primary_branch": "main"}
    if gs_path is not None:
        gs["local_path"] = gs_path
    return {
        "contexts": [
            {"id": "oversteward", "branch": "master", "local_path": "/elsewhere/OverSteward"},
            gs,
            {"id": "aigranthelper", "branch": "staging", "local_path": "/nowhere/ag"},
        ]
    }


def _run(raw: dict[str, Any], tmp_path: Path, git: FakeGit, *, gs_path: str | None = "gs"):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    gs_root = tmp_path / "gs"
    gs_root.mkdir(exist_ok=True)
    resolved = None if gs_path is None else str(tmp_path / gs_path)
    found = checkouts(_registry(resolved), home_repo="oversteward", home_root=home)
    return check_locations(parse(raw), TreeReader(git, found))


def _git(**extra: set[str]) -> FakeGit:
    return FakeGit({"HEAD": OS_FILES, "origin/main": GS_FILES, **extra})


def test_every_claim_present_is_clean(raw, tmp_path):
    outcome = _run(raw, tmp_path, _git())
    assert outcome.exit_code == EXIT_CLEAN, outcome


def test_missing_claim_exits_1_naming_the_path(raw, tmp_path):
    raw["capabilities"][2]["claims"]["oversteward"].append("src/oversteward/nope.py")
    outcome = _run(raw, tmp_path, _git())
    assert outcome.exit_code == EXIT_FINDINGS
    assert [(f.check, f.subject) for f in outcome.findings] == [("missing-path", "os.sow")]
    assert "oversteward:src/oversteward/nope.py" in outcome.findings[0].message


def test_home_repo_reads_its_own_head_without_fetching(raw, tmp_path):
    git = _git()
    _run(raw, tmp_path, git)
    home_calls = [c for c in git.calls if c[0] == str(tmp_path / "home")]
    assert home_calls and all(c[1] == "ls-tree" and "HEAD" in c for c in home_calls)


def test_sibling_repo_fetches_its_primary_branch_then_reads_origin(raw, tmp_path):
    git = _git()
    _run(raw, tmp_path, git)
    gs_calls = [c[1:] for c in git.calls if c[0] == str(tmp_path / "gs")]
    assert gs_calls[0] == ("fetch", "--quiet", "origin", "main")
    assert gs_calls[1][0] == "ls-tree" and "origin/main" in gs_calls[1]


def test_a_path_on_staging_only_is_missing_on_the_primary_branch(raw, tmp_path):
    # GS's checkout ships `main`; a claim present only on staging is not live yet.
    raw["capabilities"][1]["claims"]["grantspider"] = ["src/grantspider/services/new.py"]
    git = _git(**{"origin/staging": GS_FILES | {"src/grantspider/services/new.py"}})
    outcome = _run(raw, tmp_path, git)
    assert [(f.check, f.subject) for f in outcome.findings] == [("missing-path", "gs.website-resolution")]


def test_absent_checkout_exits_2_not_0(raw, tmp_path):
    outcome = _run(raw, tmp_path, _git(), gs_path="not-there")
    assert outcome.exit_code == EXIT_COULD_NOT_LOOK
    assert any("grantspider" in reason for reason in outcome.could_not_look)


def test_registry_without_a_local_path_exits_2(raw, tmp_path):
    outcome = _run(raw, tmp_path, _git(), gs_path=None)
    assert outcome.exit_code == EXIT_COULD_NOT_LOOK
    assert any("local_path" in reason for reason in outcome.could_not_look)


def test_failed_fetch_exits_2(raw, tmp_path):
    outcome = _run(raw, tmp_path, FakeGit({"HEAD": OS_FILES, "origin/main": GS_FILES}, fetch_ok=False))
    assert outcome.exit_code == EXIT_COULD_NOT_LOOK
    assert any("fetch" in reason for reason in outcome.could_not_look)


def test_unreadable_ref_exits_2(raw, tmp_path):
    outcome = _run(raw, tmp_path, FakeGit({"HEAD": OS_FILES}))
    assert outcome.exit_code == EXIT_COULD_NOT_LOOK


def test_could_not_look_outranks_a_finding(raw, tmp_path):
    raw["capabilities"][2]["claims"]["oversteward"].append("src/oversteward/nope.py")
    outcome = _run(raw, tmp_path, _git(), gs_path="not-there")
    assert outcome.findings and outcome.exit_code == EXIT_COULD_NOT_LOOK


def test_nothing_claimed_exits_2(raw, tmp_path):
    for cap in raw["capabilities"]:
        cap.pop("claims", None)
    outcome = _run(raw, tmp_path, _git())
    assert outcome.exit_code == EXIT_COULD_NOT_LOOK


def test_repo_location_is_checked_and_unverified_is_counted_not_read(raw, tmp_path):
    raw["capabilities"][2]["locations"] = [
        {"type": "report", "ref": "oversteward:reports/gone.md"},
        {"type": "timer", "ref": "aigranthelper:x.timer", "unverified": True},
        {"type": "vault", "ref": "GTD/x.md", "unverified": True},
    ]
    git = _git()
    outcome = _run(raw, tmp_path, git)
    assert [f.subject for f in outcome.findings] == ["os.sow"]
    assert "oversteward:reports/gone.md" in outcome.findings[0].message
    # Reading the unverified AG timer would send the check to AG's absent checkout.
    assert outcome.could_not_look == ()
    assert outcome.exit_code == EXIT_FINDINGS
    # The unverified AG timer must not send the check to AG's (absent) checkout.
    assert not [c for c in git.calls if c[0] == "/nowhere/ag"]
    assert any("2 unverified" in note for note in outcome.notes)


def test_directory_claim_is_matched_without_its_trailing_slash(raw, tmp_path):
    git = _git()
    outcome = _run(raw, tmp_path, git)
    ls = [c for c in git.calls if c[1] == "ls-tree" and c[0] == str(tmp_path / "home")][0]
    assert "src/oversteward/sow" in ls and "src/oversteward/sow/" not in ls
    assert outcome.exit_code == EXIT_CLEAN


def test_a_directory_claim_survives_a_path_named_inside_it(raw, tmp_path):
    # `git ls-tree` without `-r` descends into a directory when another pathspec names a
    # file inside it, and then never prints the directory: the claim read as missing.
    raw["capabilities"][1]["locations"] = [{"type": "path", "ref": "oversteward:src/oversteward/sow/plan.py"}]
    outcome = _run(raw, tmp_path, _git())
    assert outcome.findings == ()
    assert outcome.exit_code == EXIT_CLEAN


def test_a_directory_with_nothing_tracked_under_it_is_still_missing(raw, tmp_path):
    raw["capabilities"][2]["claims"]["oversteward"].append("src/oversteward/nowhere/")
    outcome = _run(raw, tmp_path, _git())
    assert [(f.check, f.subject) for f in outcome.findings] == [("missing-path", "os.sow")]
    assert "oversteward:src/oversteward/nowhere/" in outcome.findings[0].message
