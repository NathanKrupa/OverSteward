# ABOUTME: Tests for src/oversteward/dev_family.py — canonical shared/scripts/dev/ byte-copy audit.
# ABOUTME: Covers deploy-path mapping, status classification, and origin-ref reads on temp git repos.

from __future__ import annotations

import hashlib
import subprocess

import pytest

from oversteward.dev_family import (
    ABSENT,
    ABSENT_REFERENCED,
    DRIFTED,
    PRESENT,
    canonical_family,
    classify_member,
    classify_repo_family,
    deployed_relpath,
    format_family_table,
    gather_family_status,
    read_origin_family,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _init_repo(root, files, branch="main"):
    """Create a git repo whose origin/<branch> ref carries `files`."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(root, "update-ref", f"refs/remotes/origin/{branch}", head)
    return root


CANONICAL_FILES = {
    "new-session.sh": "#!/usr/bin/env bash\necho canonical\n",
    "with_test_env.py": "# canonical runner\n",
    "guard_main_worktree.py": "# canonical guard\n",
}


def _canonical_shared(tmp_path):
    shared = tmp_path / "shared"
    dev = shared / "scripts" / "dev"
    dev.mkdir(parents=True)
    for name, text in CANONICAL_FILES.items():
        (dev / name).write_text(text, encoding="utf-8")
    (dev / "__pycache__").mkdir()
    (dev / "__pycache__" / "junk.pyc").write_bytes(b"\x00")
    return shared


class TestDeployedRelpath:
    def test_hook_members_deploy_into_claude_hooks(self):
        assert deployed_relpath("guard_main_worktree.py") == ".claude/hooks/guard_main_worktree.py"
        assert deployed_relpath("guard_neon.py") == ".claude/hooks/guard_neon.py"
        assert deployed_relpath("guard_shared_venv.py") == ".claude/hooks/guard_shared_venv.py"
        assert deployed_relpath("guard_metered_api.py") == ".claude/hooks/guard_metered_api.py"

    def test_test_members_deploy_into_tests_dev(self):
        assert deployed_relpath("test_worktree_guard.py") == "tests/dev/test_worktree_guard.py"

    def test_dotfile_members_deploy_at_the_repo_root(self):
        assert deployed_relpath(".gitleaks.toml") == ".gitleaks.toml"

    def test_other_members_deploy_into_scripts_dev(self):
        assert deployed_relpath("with_test_env.py") == "scripts/dev/with_test_env.py"
        assert deployed_relpath("new-session.sh") == "scripts/dev/new-session.sh"


class TestCanonicalFamily:
    def test_hashes_every_member_and_skips_bytecode(self, tmp_path):
        family = canonical_family(_canonical_shared(tmp_path))
        assert set(family) == set(CANONICAL_FILES)
        assert family["new-session.sh"] == _sha(CANONICAL_FILES["new-session.sh"].encode())

    def test_missing_canonical_dir_yields_empty_family(self, tmp_path):
        assert canonical_family(tmp_path / "nope") == {}


class TestClassifyMember:
    def test_matching_sha_is_present_identical(self):
        assert classify_member("aaa", "aaa", doctrine_referenced=False) == PRESENT

    def test_differing_sha_is_drifted(self):
        assert classify_member("aaa", "bbb", doctrine_referenced=False) == DRIFTED

    def test_differing_sha_is_drifted_even_when_doctrine_referenced(self):
        assert classify_member("aaa", "bbb", doctrine_referenced=True) == DRIFTED

    def test_absent_without_doctrine_reference_is_plain_absent(self):
        assert classify_member("aaa", None, doctrine_referenced=False) == ABSENT

    def test_absent_with_doctrine_reference_is_flagged_distinctly(self):
        assert classify_member("aaa", None, doctrine_referenced=True) == ABSENT_REFERENCED


class TestClassifyRepoFamily:
    def test_doctrine_reference_is_matched_on_the_member_filename(self):
        statuses = classify_repo_family(
            {"with_test_env.py": "aaa", "new-session.sh": "bbb"},
            {"with_test_env.py": None, "new-session.sh": None},
            "Use scripts/dev/with_test_env.py for env-needing gates.",
        )
        assert statuses["with_test_env.py"] == ABSENT_REFERENCED
        assert statuses["new-session.sh"] == ABSENT


class TestReadOriginFamily:
    def test_reports_present_drifted_and_absent_from_the_origin_ref(self, tmp_path):
        repo = _init_repo(
            tmp_path / "repo",
            {
                "scripts/dev/new-session.sh": CANONICAL_FILES["new-session.sh"],
                "scripts/dev/with_test_env.py": "# drifted runner\n",
                "CLAUDE.md": "Run scripts/dev/with_test_env.py before the gates.\n",
            },
        )
        observed = read_origin_family(
            repo,
            "main",
            list(CANONICAL_FILES),
            claude_md_path="CLAUDE.md",
            fetch=False,
        )
        assert observed.available is True
        deployed = observed.deployed
        assert deployed["new-session.sh"] == _sha(CANONICAL_FILES["new-session.sh"].encode())
        assert deployed["with_test_env.py"] == _sha(b"# drifted runner\n")
        assert deployed["guard_main_worktree.py"] is None
        assert "with_test_env.py" in observed.doctrine_text

    def test_reads_the_origin_ref_not_the_stale_working_tree(self, tmp_path):
        repo = _init_repo(
            tmp_path / "repo",
            {"scripts/dev/new-session.sh": CANONICAL_FILES["new-session.sh"]},
        )
        (repo / "scripts" / "dev" / "new-session.sh").write_text("# local hack\n", encoding="utf-8")
        observed = read_origin_family(
            repo, "main", ["new-session.sh"], claude_md_path="CLAUDE.md", fetch=False
        )
        assert observed.deployed["new-session.sh"] == _sha(
            CANONICAL_FILES["new-session.sh"].encode()
        )

    def test_missing_origin_ref_is_reported_unavailable(self, tmp_path):
        repo = _init_repo(tmp_path / "repo", {"README.md": "x\n"})
        observed = read_origin_family(
            repo, "staging", ["new-session.sh"], claude_md_path="CLAUDE.md", fetch=False
        )
        assert observed.available is False
        assert observed.deployed == {}

    def test_unreachable_fetch_still_classifies_from_the_existing_ref(self, tmp_path):
        repo = _init_repo(
            tmp_path / "repo",
            {"scripts/dev/new-session.sh": CANONICAL_FILES["new-session.sh"]},
        )
        observed = read_origin_family(
            repo, "main", ["new-session.sh"], claude_md_path="CLAUDE.md", fetch=True
        )
        assert observed.fetched is False
        assert observed.available is True


class TestGatherFamilyStatus:
    @pytest.fixture
    def estate(self, tmp_path):
        shared = _canonical_shared(tmp_path)
        _init_repo(
            tmp_path / "good",
            {
                "scripts/dev/new-session.sh": CANONICAL_FILES["new-session.sh"],
                "scripts/dev/with_test_env.py": CANONICAL_FILES["with_test_env.py"],
                ".claude/hooks/guard_main_worktree.py": CANONICAL_FILES["guard_main_worktree.py"],
                "CLAUDE.md": "nothing to see\n",
            },
        )
        _init_repo(
            tmp_path / "bad",
            {
                "scripts/dev/new-session.sh": "#!/usr/bin/env bash\necho stale\n",
                "CLAUDE.md": "Always use scripts/dev/with_test_env.py.\n",
            },
            branch="staging",
        )
        registry = {
            "contexts": [
                {
                    "id": "good",
                    "branch": "main",
                    "local_path": str(tmp_path / "good"),
                    "claude_md_path": "CLAUDE.md",
                },
                {
                    "id": "bad",
                    "branch": "staging",
                    "local_path": str(tmp_path / "bad"),
                    "claude_md_path": "CLAUDE.md",
                },
                {"id": "no-clone", "branch": "main", "claude_md_path": "CLAUDE.md"},
            ]
        }
        return registry, shared

    def test_rows_carry_every_member_status_per_repo(self, estate):
        registry, shared = estate
        rows = gather_family_status(registry, shared, fetch=False)
        by_id = {row.context_id: row for row in rows}
        assert set(by_id) == {"good", "bad"}
        assert set(by_id["good"].members.values()) == {PRESENT}
        assert by_id["bad"].members == {
            "new-session.sh": DRIFTED,
            "with_test_env.py": ABSENT_REFERENCED,
            "guard_main_worktree.py": ABSENT,
        }

    def test_contexts_without_a_local_clone_are_skipped(self, estate):
        registry, shared = estate
        rows = gather_family_status(registry, shared, fetch=False)
        assert all(row.context_id != "no-clone" for row in rows)

    def test_table_lists_one_line_per_repo_and_member(self, estate):
        registry, shared = estate
        table = format_family_table(gather_family_status(registry, shared, fetch=False))
        assert any("new-session.sh" in line for line in table)
        assert any(DRIFTED in line for line in table)
        assert any(ABSENT_REFERENCED in line for line in table)
