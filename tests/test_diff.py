# ABOUTME: Tests for src/oversteward/diff.py — pure snapshot-vs-expectation comparison (H2-4).
# ABOUTME: Covers managed-block, soul, canonical-family statuses, shared deploy, freshness.

from __future__ import annotations

from oversteward.dev_family import (
    ABSENT,
    ABSENT_REFERENCED,
    DRIFTED,
    PRESENT,
    RepoFamilyStatus,
)
from oversteward.diff import diff_state


def _context(**overrides):
    ctx = {
        "id": "demo",
        "type": "vscode",
        "reachable": True,
        "skip_sow": False,
        "soul": "chestertron",
        "soul_in_local": False,
        "claude_md": {
            "exists": True,
            "sha256": "abc",
            "managed": {
                "present": True,
                "synced": "2026-04-14",
                "text": "@~/.claude/shared/souls/chestertron.md\n",
            },
            "local_block_present": True,
        },
        "settings_sha256": "s1",
        "gitleaksignore_present": True,
    }
    ctx.update(overrides)
    return ctx


def _snapshot(contexts=None, **overrides):
    snap = {
        "contexts": contexts if contexts is not None else [_context()],
        "canonical_shared": {"souls/chestertron.md": "soul-sha"},
        "deploy_targets": {"wsl": {"souls/chestertron.md": "soul-sha"}},
    }
    snap.update(overrides)
    return snap


def _by_surface(findings, surface):
    return [f for f in findings if f["surface"] == surface]


def _problems(findings):
    return [f for f in findings if f["severity"] in ("missing", "drift")]


class TestManagedBlock:
    def test_clean_context_has_no_problems(self):
        assert _problems(diff_state(_snapshot())) == []

    def test_missing_managed_block_flagged(self):
        ctx = _context()
        ctx["claude_md"]["managed"] = {"present": False, "synced": None, "text": None}
        findings = _by_surface(diff_state(_snapshot([ctx])), "managed-block")
        assert [f["severity"] for f in findings] == ["missing"]
        assert findings[0]["context"] == "demo"

    def test_skip_sow_context_exempt(self):
        ctx = _context(skip_sow=True)
        ctx["claude_md"]["managed"] = {"present": False, "synced": None, "text": None}
        assert _by_surface(diff_state(_snapshot([ctx])), "managed-block") == []

    def test_missing_claude_md_flagged(self):
        ctx = _context()
        ctx["claude_md"] = {"exists": False}
        findings = _by_surface(diff_state(_snapshot([ctx])), "managed-block")
        assert [f["severity"] for f in findings] == ["missing"]

    def test_soul_mismatch_flagged(self):
        ctx = _context(soul="macgregor")
        findings = _by_surface(diff_state(_snapshot([ctx])), "soul")
        assert [f["severity"] for f in findings] == ["drift"]

    def test_soul_in_local_exempt_from_soul_check(self):
        ctx = _context(soul="david", soul_in_local=True)
        assert _by_surface(diff_state(_snapshot([ctx])), "soul") == []

    def test_unreachable_context_reported_as_info_only(self):
        ctx = {"id": "remote", "type": "obsidian", "reachable": False}
        findings = diff_state(_snapshot([ctx]))
        assert _problems(findings) == []
        assert _by_surface(findings, "reachability")[0]["context"] == "remote"


class TestSecurityGate:
    def test_clean_context_has_no_security_findings(self):
        assert _by_surface(diff_state(_snapshot()), "security-gate") == []

    def test_missing_gitleaksignore_flagged(self):
        surface = _by_surface(
            diff_state(_snapshot([_context(gitleaksignore_present=False)])), "security-gate"
        )
        assert [f["severity"] for f in surface] == ["missing"]
        assert ".gitleaksignore" in surface[0]["message"]


class TestCanonicalFamily:
    def _findings(self, members, available=True):
        rows = [
            RepoFamilyStatus(
                context_id="demo",
                branch="main",
                available=available,
                fetched=True,
                members=members,
            )
        ]
        return _by_surface(diff_state(_snapshot(), family_rows=rows), "canonical-family")

    def test_identical_members_produce_no_finding(self):
        assert self._findings({"new-session.sh": PRESENT}) == []

    def test_drifted_member_names_its_deployed_path(self):
        surface = self._findings({"guard_main_worktree.py": DRIFTED})
        assert [f["severity"] for f in surface] == ["drift"]
        assert ".claude/hooks/guard_main_worktree.py" in surface[0]["message"]

    def test_absent_but_doctrine_referenced_is_a_missing_finding(self):
        surface = self._findings({"with_test_env.py": ABSENT_REFERENCED})
        assert [f["severity"] for f in surface] == ["missing"]
        assert "CLAUDE.md" in surface[0]["message"]

    def test_plain_absence_is_informational(self):
        surface = self._findings({"guard_neon.py": ABSENT})
        assert [f["severity"] for f in surface] == ["info"]

    def test_unreadable_origin_ref_is_informational(self):
        surface = self._findings({}, available=False)
        assert [f["severity"] for f in surface] == ["info"]

    def test_family_is_skipped_when_no_rows_supplied(self):
        assert _by_surface(diff_state(_snapshot()), "canonical-family") == []


class TestSharedDeploy:
    def test_missing_target_flagged_once(self):
        snap = _snapshot(deploy_targets={"windows": None})
        surface = _by_surface(diff_state(snap), "shared-deploy:windows")
        assert [f["severity"] for f in surface] == ["missing"]

    def test_file_missing_from_target(self):
        snap = _snapshot(deploy_targets={"wsl": {}})
        surface = _by_surface(diff_state(snap), "shared-deploy:wsl")
        assert [f["severity"] for f in surface] == ["missing"]
        assert "souls/chestertron.md" in surface[0]["message"]

    def test_hash_mismatch_is_drift(self):
        snap = _snapshot(deploy_targets={"wsl": {"souls/chestertron.md": "old"}})
        surface = _by_surface(diff_state(snap), "shared-deploy:wsl")
        assert [f["severity"] for f in surface] == ["drift"]

    def test_extra_target_file_is_info(self):
        snap = _snapshot(
            deploy_targets={"wsl": {"souls/chestertron.md": "soul-sha", "extra.md": "x"}}
        )
        surface = _by_surface(diff_state(snap), "shared-deploy:wsl")
        assert [f["severity"] for f in surface] == ["info"]


class TestSettingsAndFreshness:
    def test_settings_presence_summarized_as_info(self):
        contexts = [_context(), _context(id="other", settings_sha256=None)]
        surface = _by_surface(diff_state(_snapshot(contexts)), "settings")
        assert len(surface) == 1
        assert surface[0]["severity"] == "info"
        assert "other" in surface[0]["message"]

    def test_stale_session_state_flagged(self):
        freshness = {"session_state_date": "2026-06-01", "last_merge_date": "2026-06-10"}
        surface = _by_surface(diff_state(_snapshot(), freshness=freshness), "tracking")
        assert [f["severity"] for f in surface] == ["drift"]

    def test_fresh_session_state_clean(self):
        freshness = {"session_state_date": "2026-06-10", "last_merge_date": "2026-06-10"}
        assert _by_surface(diff_state(_snapshot(), freshness=freshness), "tracking") == []

    def test_no_freshness_input_no_tracking_findings(self):
        assert _by_surface(diff_state(_snapshot()), "tracking") == []
