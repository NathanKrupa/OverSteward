# ABOUTME: Tests for the metered-API guard hook (.claude/hooks/guard_metered_api.py).
# ABOUTME: Pure predicate truth table; no CLI, no network, no hook plumbing.

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load():
    rel = Path("shared") / "scripts" / "dev" / "guard_metered_api.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("guard_metered_api", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


g = _load()


@pytest.fixture(autouse=True)
def _unarmed(monkeypatch):
    """Every test starts from an unarmed session — an inherited override is not a finding."""
    monkeypatch.delenv("CLAUDE_ALLOW_METERED_API", raising=False)


def _blocked(command: str) -> bool:
    return g.refusal(command) is not None


# --- the drains that must be refused --------------------------------------
#
# Each shape below was confirmed in grantspider's CLI to construct an
# AnthropicClient (or build_llm_client("anthropic", ...)) and loop a cohort.


def test_bare_enrich_is_refused():
    """The exact command that drained the org's credits on 2026-08-20."""
    assert _blocked("grantspider enrich")


def test_enrich_with_options_is_refused():
    assert _blocked("grantspider enrich --source website --limit 500")


def test_enrichment_worker_run_is_refused():
    assert _blocked("grantspider enrichment-worker run --claim-budget 200")


def test_llm_extract_run_is_refused():
    assert _blocked("grantspider llm-extract run --limit 50")


def test_hygiene_beautify_text_is_refused():
    assert _blocked("grantspider hygiene beautify-text --limit 100")


def test_pcs_backfills_are_refused():
    assert _blocked("grantspider pcs backfill-grants")
    assert _blocked("grantspider pcs backfill-programmes")


def test_dq_ntee_check_is_refused():
    assert _blocked("grantspider dq ntee-check --limit 500")


def test_corporate_direct_ingest_is_refused():
    assert _blocked("grantspider corporate-direct-ingest")


# --- the invocation shapes the estate actually types ----------------------


def test_venv_path_invocation_is_refused():
    assert _blocked(".venv/bin/grantspider enrich")


def test_uv_run_invocation_is_refused():
    assert _blocked("uv run --no-sync grantspider enrich")


def test_invocation_after_a_shell_separator_is_refused():
    assert _blocked("cd /home/natha/grantspider && grantspider enrich --limit 500")


def test_backgrounded_invocation_is_refused():
    """The incident shape: a drain pushed into the background from a session."""
    assert _blocked("grantspider enrich --limit 500 > /tmp/enrich.log 2>&1")


# --- the neighbours that must NOT be refused ------------------------------
#
# A guard that cries wolf gets overridden reflexively, which leaves the real
# case unguarded. Every command below is either the sanctioned Max-billed path
# or costs nothing at all.


def test_enrich_profile_pull_batch_is_untouched():
    """The Max workflow this guard exists to point people at."""
    assert not _blocked("grantspider enrich-profile pull-batch --limit 40")


def test_enrich_profile_apply_is_untouched():
    assert not _blocked("grantspider enrich-profile apply results.jsonl")


def test_db_scratch_is_untouched():
    assert not _blocked("grantspider db scratch 'select count(*) from foundations'")


def test_enrich_dispositions_is_untouched():
    """Local-GPU qwen, zero metered cost — and it shares a prefix with `enrich`."""
    assert not _blocked("grantspider enrich-dispositions --batch-size 20")


def test_llm_extract_queue_verbs_are_untouched():
    assert not _blocked("grantspider llm-extract export-queue --limit 30")
    assert not _blocked("grantspider llm-extract import-results results.jsonl")


def test_hygiene_beautify_queue_verbs_are_untouched():
    assert not _blocked("grantspider hygiene beautify-pull-batch --limit 30")
    assert not _blocked("grantspider hygiene beautify-apply results.jsonl")


def test_other_dq_verbs_are_untouched():
    assert not _blocked("grantspider dq snapshot")


def test_non_grantspider_commands_are_untouched():
    assert not _blocked("pytest -q")
    assert not _blocked("git commit -m 'wip'")


def test_help_is_never_refused():
    """Rendering help spends nothing, even for a group that is metered end to end."""
    assert not _blocked("grantspider enrich --help")
    assert not _blocked("grantspider enrichment-worker --help")


# --- prose is not a command ----------------------------------------------


def test_quoted_mention_in_a_commit_message_does_not_block():
    assert not _blocked('git commit -m "feat(guard): refuse grantspider enrich"')


def test_single_quoted_mention_does_not_block():
    assert not _blocked("grep -rn 'grantspider enrich' documentation/")


def test_heredoc_body_mention_does_not_block():
    """PR bodies describe the very commands this guard refuses."""
    command = (
        "gh pr create --body \"$(cat <<'EOF'\n"
        "Blocks `grantspider enrich` unless armed.\n"
        "grantspider enrich\n"
        "EOF\n"
        ')"'
    )
    assert not _blocked(command)


def test_a_real_drain_after_a_quoted_mention_is_still_refused():
    """Stripping prose must not blind the guard to the command beside it."""
    assert _blocked("echo 'about to drain' && grantspider enrich --limit 500")


# --- the escape hatch -----------------------------------------------------


def test_inline_override_allows():
    assert not _blocked("CLAUDE_ALLOW_METERED_API=1 grantspider enrich --limit 500")


def test_inline_override_allows_a_path_invocation():
    assert not _blocked("CLAUDE_ALLOW_METERED_API=1 .venv/bin/grantspider enrich")


def test_exported_override_allows(monkeypatch):
    monkeypatch.setenv("CLAUDE_ALLOW_METERED_API", "1")
    assert not _blocked("grantspider enrich --limit 500")


def test_quoted_override_does_not_wave_through():
    """A mention inside a string is not an assignment."""
    assert _blocked("echo \"CLAUDE_ALLOW_METERED_API=1\" && grantspider enrich")


def test_a_sibling_guards_override_does_not_wave_this_one_through(monkeypatch):
    monkeypatch.setenv("CLAUDE_ALLOW_MAIN_GIT", "1")
    assert _blocked("grantspider enrich")


# --- the refusal has to be actionable -------------------------------------


def test_refusal_names_the_max_billed_alternative_for_the_enrich_drain():
    message = g.refusal("grantspider enrich --limit 500")
    assert "enrich-profile pull-batch" in message
    assert "enrich-profile apply" in message


def test_refusal_names_the_queue_bridge_for_llm_extract():
    message = g.refusal("grantspider llm-extract run")
    assert "llm-extract export-queue" in message
    assert "llm-extract import-results" in message


def test_refusal_names_the_arming_prefix():
    assert "CLAUDE_ALLOW_METERED_API=1" in g.refusal("grantspider enrich")


def test_refusal_names_the_command_it_refused():
    assert "pcs backfill-grants" in g.refusal("grantspider pcs backfill-grants --limit 10")


# --- hook plumbing --------------------------------------------------------


def test_subcommand_path_stops_at_the_first_flag():
    assert g.subcommand_path("grantspider llm-extract run --limit 5") == ("llm-extract", "run")


def test_subcommand_path_is_none_for_a_non_grantspider_command():
    assert g.subcommand_path("pytest -q") is None


# --- the deployment IS the control ---------------------------------------
#
# A merged hook is not a live hook. The canonical source, the deployed
# byte-copy and the settings registration are three separate deliveries, and
# any one of them missing leaves a guard that reports nothing forever.


def test_the_deployed_copy_is_byte_identical_to_canonical():
    canonical = REPO_ROOT / "shared" / "scripts" / "dev" / "guard_metered_api.py"
    deployed = REPO_ROOT / ".claude" / "hooks" / "guard_metered_api.py"
    assert deployed.read_bytes() == canonical.read_bytes()


def test_the_hook_is_registered_as_a_pretooluse_bash_hook():
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entry in settings["hooks"]["PreToolUse"]
        if entry.get("matcher") == "Bash"
        for hook in entry["hooks"]
    ]
    assert any("guard_metered_api.py" in command for command in commands)
