# ABOUTME: Tests for src/oversteward/gather.py — read-only state extraction (H2-3).
# ABOUTME: Covers managed-block parsing, context gathering, shared-tree hashing, snapshot assembly.

from __future__ import annotations

import hashlib

from oversteward.gather import (
    extract_managed_block,
    gather_context,
    gather_shared_tree,
    gather_state,
)

MANAGED_CLAUDE_MD = """<!-- [oversteward:managed | synced: 2026-04-14] -->
@~/.claude/shared/souls/chestertron.md

<!-- [oversteward:managed:end] -->

# Project notes

<!-- [oversteward:local] -->
Nathan's own rules.
<!-- [oversteward:local:end] -->
"""

UNMANAGED_CLAUDE_MD = """@~/.claude/shared/souls/chestertron.md

# Working Guidelines
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestExtractManagedBlock:
    def test_present_block_yields_text_and_synced_date(self):
        block = extract_managed_block(MANAGED_CLAUDE_MD)
        assert block["present"] is True
        assert block["synced"] == "2026-04-14"
        assert "souls/chestertron.md" in block["text"]

    def test_absent_block(self):
        block = extract_managed_block(UNMANAGED_CLAUDE_MD)
        assert block == {"present": False, "synced": None, "text": None}


class TestGatherContext:
    def _ctx(self, tmp_path, **overrides):
        ctx = {
            "id": "demo",
            "type": "vscode",
            "local_path": str(tmp_path),
            "claude_md_path": "CLAUDE.md",
            "soul": "chestertron",
        }
        ctx.update(overrides)
        return ctx

    def test_no_local_path_is_unreachable(self):
        result = gather_context({"id": "remote", "type": "obsidian", "claude_md_path": "x.md"})
        assert result["id"] == "remote"
        assert result["reachable"] is False

    def test_collects_claude_md_and_managed_block(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(MANAGED_CLAUDE_MD, encoding="utf-8")
        result = gather_context(self._ctx(tmp_path))
        assert result["reachable"] is True
        assert result["claude_md"]["exists"] is True
        assert result["claude_md"]["managed"]["present"] is True
        assert result["claude_md"]["local_block_present"] is True
        assert result["soul"] == "chestertron"

    def test_missing_claude_md(self, tmp_path):
        result = gather_context(self._ctx(tmp_path))
        assert result["claude_md"]["exists"] is False

    def test_collects_settings_hook_and_dev_script_hashes(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(UNMANAGED_CLAUDE_MD, encoding="utf-8")
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_bytes(b"{}")
        hook = tmp_path / ".claude" / "hooks" / "guard_main_worktree.py"
        hook.parent.mkdir(parents=True)
        hook.write_bytes(b"hook-code")
        dev = tmp_path / "scripts" / "dev" / "new-session.sh"
        dev.parent.mkdir(parents=True)
        dev.write_bytes(b"dev-script")

        result = gather_context(self._ctx(tmp_path))
        assert result["settings_sha256"] == _sha(b"{}")
        assert result["hook_sha256"] == _sha(b"hook-code")
        assert result["new_session_sha256"] == _sha(b"dev-script")

    def test_absent_optional_files_are_none(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(UNMANAGED_CLAUDE_MD, encoding="utf-8")
        result = gather_context(self._ctx(tmp_path))
        assert result["settings_sha256"] is None
        assert result["hook_sha256"] is None
        assert result["new_session_sha256"] is None

    def test_registry_flags_carried_into_snapshot(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(UNMANAGED_CLAUDE_MD, encoding="utf-8")
        result = gather_context(self._ctx(tmp_path, skip_sow=True, soul_in_local=True))
        assert result["skip_sow"] is True
        assert result["soul_in_local"] is True


class TestGatherSharedTree:
    def test_hashes_files_recursively_with_relative_paths(self, tmp_path):
        (tmp_path / "souls").mkdir()
        (tmp_path / "souls" / "chestertron.md").write_bytes(b"soul")
        (tmp_path / "top.md").write_bytes(b"top")
        tree = gather_shared_tree(tmp_path)
        assert tree == {"souls/chestertron.md": _sha(b"soul"), "top.md": _sha(b"top")}

    def test_skips_pycache_and_mutable_files(self, tmp_path):
        pycache = tmp_path / "scripts" / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "m.cpython-312.pyc").write_bytes(b"x")
        (tmp_path / "inbox.md").write_bytes(b"note")
        assert gather_shared_tree(tmp_path) == {}

    def test_missing_root_returns_none(self, tmp_path):
        assert gather_shared_tree(tmp_path / "nope") is None


class TestGatherState:
    def test_assembles_contexts_canonical_and_targets(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text(MANAGED_CLAUDE_MD, encoding="utf-8")
        canonical = tmp_path / "shared"
        dev = canonical / "scripts" / "dev"
        dev.mkdir(parents=True)
        (dev / "guard_main_worktree.py").write_bytes(b"hook-code")
        (dev / "new-session.sh").write_bytes(b"dev-script")
        target = tmp_path / "deployed"
        target.mkdir()
        (target / "f.md").write_bytes(b"f")

        registry = {
            "contexts": [
                {
                    "id": "demo",
                    "type": "vscode",
                    "local_path": str(repo),
                    "claude_md_path": "CLAUDE.md",
                    "soul": "chestertron",
                }
            ]
        }
        snapshot = gather_state(
            registry,
            canonical_shared=canonical,
            deploy_targets={"wsl": target, "windows": tmp_path / "missing"},
        )
        assert [c["id"] for c in snapshot["contexts"]] == ["demo"]
        assert snapshot["canonical_dev"]["guard_main_worktree.py"] == _sha(b"hook-code")
        assert snapshot["canonical_dev"]["new-session.sh"] == _sha(b"dev-script")
        assert snapshot["deploy_targets"]["wsl"] == {"f.md": _sha(b"f")}
        assert snapshot["deploy_targets"]["windows"] is None
        assert "scripts/dev/guard_main_worktree.py" in snapshot["canonical_shared"]
