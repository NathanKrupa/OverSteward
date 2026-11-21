# ABOUTME: Tests for the Tier-1 secret-scan gate (scripts/dev/secret_scan.py).
# ABOUTME: Covers report reduction, secret non-leakage, docker-mode command shape, and exit codes.

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# A gitleaks report row carrying a (masked) secret — the test proves the
# reducer never surfaces the value even when the field is present.
SECRET_MARKER = "sk_live_SHOULD_NEVER_APPEAR_ABCDEF123456"


def _load_scanner():
    """Load the deployed gate by file path (no package install needed)."""
    rel = Path("scripts") / "dev" / "secret_scan.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("secret_scan", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(f"could not locate {rel} above {__file__}")


def _scrub_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every inherited ``GIT_*`` variable from this test's environment.

    A git hook passes its location variables to the suite it runs, and each one
    re-points git away from the ``cwd`` tree: every scratch-repo command would
    read and write the hook's repository instead of ``tmp_path`` (OS#809).
    """
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _no_inherited_git_env(monkeypatch):
    """The one place this file's git calls are isolated from a hook's environment."""
    _scrub_git_env(monkeypatch)


@pytest.fixture(scope="module")
def scan():
    return _load_scanner()


# --- report reduction -------------------------------------------------------


def test_empty_report_is_no_findings(scan):
    assert scan.parse_report("") == []
    assert scan.parse_report("[]") == []


def test_parse_reduces_to_rule_file_line(scan):
    report = json.dumps(
        [
            {"RuleID": "stripe-access-token", "File": "a.py", "StartLine": 12},
            {"RuleID": "generic-api-key", "File": "b/c.py", "StartLine": 3},
        ]
    )
    findings = scan.parse_report(report)
    assert [(f.rule, f.file, f.line) for f in findings] == [
        ("stripe-access-token", "a.py", 12),
        ("generic-api-key", "b/c.py", 3),
    ]


def test_finding_never_carries_the_secret_value(scan):
    """Even with Secret/Match populated, the reduced finding cannot leak them."""
    report = json.dumps(
        [{"RuleID": "r", "File": "f", "StartLine": 1, "Secret": SECRET_MARKER, "Match": SECRET_MARKER}]
    )
    findings = scan.parse_report(report)
    rendered = findings[0].render()
    assert SECRET_MARKER not in rendered
    assert not hasattr(findings[0], "secret")


# --- docker command shape ---------------------------------------------------


def test_staged_command_is_protect_redacted_readonly(scan):
    cmd = scan.build_gitleaks_cmd(
        Path("/repo"), Path("/out/report.json"), scan.DEFAULT_IMAGE, staged=True, rev_range=None
    )
    assert "protect" in cmd
    assert "--staged" in cmd
    assert "--redact" in cmd
    assert any(a.endswith(":ro") for a in cmd), "repo must mount read-only"


def test_range_command_is_detect_with_log_opts(scan):
    cmd = scan.build_gitleaks_cmd(
        Path("/repo"), Path("/out/report.json"), scan.DEFAULT_IMAGE, staged=False, rev_range="a..b"
    )
    assert "detect" in cmd
    assert "--log-opts=a..b" in cmd
    assert "--redact" in cmd
    assert "--staged" not in cmd


def _git(*args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_normal_repo_mounts_itself_at_host_path(scan, tmp_path):
    """A plain repo mounts once, at its own absolute path, and --source points there."""
    repo = tmp_path / "main"
    repo.mkdir()
    _git("init", cwd=repo)
    cmd = scan.build_gitleaks_cmd(
        repo, Path("/out/report.json"), scan.DEFAULT_IMAGE, staged=True, rev_range=None
    )
    assert f"{repo}:{repo}:ro" in cmd
    assert f"--source={repo}" in cmd
    assert sum(1 for a in cmd if a.endswith(":ro")) == 1


def test_worktree_mounts_common_git_dir(scan, tmp_path):
    """A linked worktree must also mount the main .git dir, else gitleaks sees no repo.

    Regression: the estate's worktree-per-session discipline means commits happen
    in linked worktrees, where `.git` is a pointer file — with only the worktree
    mounted, gitleaks logged `fatal: not a git repository`, wrote an empty
    report, and the gate passed green on a staged secret.
    """
    repo = tmp_path / "main"
    repo.mkdir()
    _git("init", cwd=repo)
    # A throwaway repo has no committer identity, and CI runners carry no global
    # one — so the commit below exits 128 there while passing on any developer
    # machine. Set it locally rather than depending on ambient config.
    _git("config", "user.email", "secret-scan@example.test", cwd=repo)
    _git("config", "user.name", "Secret Scan Test", cwd=repo)
    _git("commit", "--allow-empty", "-m", "init", cwd=repo)
    wt = tmp_path / "wt"
    _git("worktree", "add", str(wt), cwd=repo)
    cmd = scan.build_gitleaks_cmd(
        wt, Path("/out/report.json"), scan.DEFAULT_IMAGE, staged=True, rev_range=None
    )
    common = (repo / ".git").resolve()
    assert f"{wt}:{wt}:ro" in cmd
    assert f"{common}:{common}:ro" in cmd
    assert f"--source={wt}" in cmd


# --- a git hook's GIT_DIR must not reach the scratch repos (OS#809) ----------

#: The location variables a git hook can export, each of which overrides ``cwd``.
GIT_LOCATION_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
)


def test_the_scrub_removes_every_git_location_variable(tmp_path, monkeypatch):
    for name in GIT_LOCATION_VARIABLES:
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv("KEEP_ME", "1")

    _scrub_git_env(monkeypatch)

    assert [name for name in GIT_LOCATION_VARIABLES if name in os.environ] == []
    assert os.environ["KEEP_ME"] == "1"


def _run_tests_under_git_dir(git_dir: Path, basetemp: Path, *tests: str):
    """Run the named tests of this file in a child pytest that inherits ``GIT_DIR``."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", *(f"{__file__}::{t}" for t in tests)]
        + ["-q", "-p", "no:cacheprovider", f"--basetemp={basetemp}"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_DIR": str(git_dir)},
    )


def test_a_hooks_git_dir_does_not_reach_the_scratch_repos(tmp_path):
    """Run this file's git tests the way a hook would, with GIT_DIR inherited.

    The decoy is a repository of its own, so a test that leaked to it fails on
    the decoy's state, and the decoy's config shows any write that leaked.
    """
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    _git("init", "-q", cwd=decoy)
    config = decoy / ".git" / "config"
    before = config.read_bytes()

    result = _run_tests_under_git_dir(
        decoy / ".git",
        tmp_path / "child",
        "test_normal_repo_mounts_itself_at_host_path",
        "test_worktree_mounts_common_git_dir",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    assert config.read_bytes() == before


# --- exit-code / fail-open-vs-closed logic ----------------------------------


def test_docker_absent_is_could_not_look_not_clean(scan, monkeypatch):
    # Was 0 — byte-for-byte identical to a scan that ran and found nothing, so a
    # commit on a machine without docker was certified by a scanner that never
    # started (OS#384).
    monkeypatch.setattr(scan, "docker_available", lambda: False)
    monkeypatch.delenv("SECRET_SCAN_REQUIRED", raising=False)
    monkeypatch.delenv("SECRET_SCAN_ALLOW_UNAVAILABLE", raising=False)
    assert scan.main(["--staged"]) == 2


def test_the_gap_can_be_accepted_deliberately_on_a_machine_without_docker(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: False)
    monkeypatch.delenv("SECRET_SCAN_REQUIRED", raising=False)
    monkeypatch.setenv("SECRET_SCAN_ALLOW_UNAVAILABLE", "1")
    assert scan.main(["--staged"]) == 0


def test_the_escape_hatch_cannot_switch_off_the_required_mode(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: False)
    monkeypatch.setenv("SECRET_SCAN_REQUIRED", "1")
    monkeypatch.setenv("SECRET_SCAN_ALLOW_UNAVAILABLE", "1")
    assert scan.main(["--staged"]) == 2


def test_docker_absent_fails_closed_when_required(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: False)
    monkeypatch.setenv("SECRET_SCAN_REQUIRED", "1")
    assert scan.main(["--staged"]) == 2


def test_findings_fail_the_gate(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: True)
    monkeypatch.setattr(
        scan, "run_scan", lambda *a, **k: [scan.Finding("generic-api-key", "x.py", 9)]
    )
    assert scan.main(["--staged"]) == 1


def test_clean_scan_passes(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: True)
    monkeypatch.setattr(scan, "run_scan", lambda *a, **k: [])
    assert scan.main(["--staged"]) == 0


def test_partial_scan_markers_detected(scan):
    assert scan.scan_incomplete("8:31PM WRN partial scan completed in 2.82ms")
    assert scan.scan_incomplete("ERR [git] fatal: not a git repository: /x/.git/worktrees/y")
    assert not scan.scan_incomplete("8:31PM INF no leaks found")
    assert not scan.scan_incomplete("")


def test_partial_scan_always_fails_closed(scan, monkeypatch):
    """A scan that ran but could not see the diff must never read as clean."""

    def _partial(*a, **k):
        raise scan.PartialScanError("gitleaks partial scan: git dir not visible")

    monkeypatch.setattr(scan, "docker_available", lambda: True)
    monkeypatch.setattr(scan, "run_scan", _partial)
    monkeypatch.delenv("SECRET_SCAN_REQUIRED", raising=False)
    assert scan.main(["--staged"]) == 2


# --- gitleaks config (.gitleaks.toml) — WP application-password rule ---------
#
# The rule's behavioural proof is the end-to-end docker run (a config-only change
# is exercised by gitleaks, not by importable Python). These tests guard the two
# invariants that a docker run does NOT catch: the canonical source and its
# byte-copied root deployment stay identical, and the rule stays keyword-anchored
# (so it never degrades into a bare 4x4 matcher that fires on prose).


_GITLEAKS_TOML = ".gitleaks.toml"
_CANONICAL_DIR = ("shared", "scripts", "dev")
_WP_RULE_ID = "wordpress-application-password"


def _repo_root_for(start: Path) -> Path:
    """The checkout root above ``start`` — the tree holding ``.git``.

    Keyed on ``.git`` rather than on ``shared/scripts/dev``, because only
    OverSteward has that directory: a pickup repo holds the deployed copy and no
    canonical tree, so the old marker could not find the root there at all and
    raised (OS#281). ``.git`` is a FILE in a linked worktree and a directory in a
    primary checkout, so ``exists()`` covers both.
    """
    for parent in start.resolve().parents:
        if (parent / ".git").exists():
            return parent
    raise FileNotFoundError(f"could not locate a checkout root above {start}")


def _repo_root() -> Path:
    return _repo_root_for(Path(__file__))


def _canonical_config_path() -> Path | None:
    """The canonical config, or None where there is no ``shared/`` tree."""
    canonical = _repo_root().joinpath(*_CANONICAL_DIR, _GITLEAKS_TOML)
    return canonical if canonical.is_file() else None


def _deployed_config_path() -> Path:
    """The root ``.gitleaks.toml`` — the copy that actually gates commits."""
    return _repo_root() / _GITLEAKS_TOML


def test_repo_root_is_found_without_a_canonical_tree(tmp_path):
    """A pickup repo has the deployed config and no ``shared/`` tree (OS#281)."""
    root = tmp_path / "repo"
    (root / "tests" / "dev").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / _GITLEAKS_TOML).write_text("", encoding="utf-8")

    assert _repo_root_for(root / "tests" / "dev" / "test_secret_scan.py") == root


def test_repo_root_is_found_from_a_linked_worktree(tmp_path):
    """``.git`` is a FILE in a worktree, not a directory."""
    root = tmp_path / "wt"
    (root / "tests" / "dev").mkdir(parents=True)
    (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")

    assert _repo_root_for(root / "tests" / "dev" / "test_secret_scan.py") == root


@pytest.mark.skipif(
    _canonical_config_path() is None, reason="no shared/ tree — this is a pickup repo"
)
def test_gitleaks_config_canonical_and_root_are_byte_identical():
    canonical = _canonical_config_path()
    assert canonical is not None
    deployed = _deployed_config_path().read_bytes()
    assert canonical.read_bytes() == deployed, (
        "root .gitleaks.toml must be a byte-copy of the canonical source"
    )


def test_gitleaks_config_extends_default_and_defines_wp_rule():
    """Read the DEPLOYED config — it exists in every repo, and it is the one
    gitleaks actually loads."""
    conf = tomllib.loads(_deployed_config_path().read_text())
    assert conf["extend"]["useDefault"] is True, "must keep built-in rules (AWS, etc.)"
    ids = [r["id"] for r in conf.get("rules", [])]
    assert _WP_RULE_ID in ids


def test_wp_rule_is_keyword_anchored():
    """The rule matches a WP-app-password assignment but NOT a bare 4x4 shape.

    A four-group synthetic value is fake by construction; the point is that the
    regex requires an app-password key in context, so prose containing four short
    tokens can never trip it.
    """
    conf = tomllib.loads(_deployed_config_path().read_text())
    rule = next(r for r in conf["rules"] if r["id"] == _WP_RULE_ID)
    pattern = re.compile(rule["regex"])
    assert pattern.search('WP_APP_PASSWORD="abcd 1234 wxyz 7890"')
    assert pattern.search("application_password: wxyz 7890 abcd 1234")
    # bare shape with no app-password key → must NOT match (no false positive)
    assert not pattern.search("code abcd 1234 wxyz 7890 four groups but no key")
    assert not pattern.search("The quick brown fox jumps over lazy dogs today.")


def test_scan_error_skips_unless_required(scan, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("gitleaks produced no report: boom")

    monkeypatch.setattr(scan, "docker_available", lambda: True)
    monkeypatch.setattr(scan, "run_scan", _boom)
    monkeypatch.delenv("SECRET_SCAN_REQUIRED", raising=False)
    assert scan.main(["--staged"]) == 0
    monkeypatch.setenv("SECRET_SCAN_REQUIRED", "1")
    assert scan.main(["--staged"]) == 2
