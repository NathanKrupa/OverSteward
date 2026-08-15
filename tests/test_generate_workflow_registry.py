# ABOUTME: Tests for shared/scripts/workflows/generate_workflow_registry.py.
# ABOUTME: Covers frontmatter parsing, required-field validation, drift checks, collection, rendering.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    """Load the shared canonical script by file path so the test is independent
    of where the script has been sown (``shared/...`` vs ``scripts/workflows/...``)."""
    script_path = (
        Path(__file__).resolve().parent.parent
        / "shared"
        / "scripts"
        / "workflows"
        / "generate_workflow_registry.py"
    )
    spec = importlib.util.spec_from_file_location("oversteward_workflow_registry_shared", script_path)
    assert spec and spec.loader, "spec_from_file_location returned no loader"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_module()


VALID_DESCRIPTOR = """\
---
name: enrich-drain
summary: Drain not-yet-profiled foundations.
when_to_use: Backfill foundation profiles in-session, no API key.
kind: workflow-script
status: active
entrypoint: .claude/workflows/enrich-drain.js
components:
  - scripts/enrich/split_batch.py
  - "grantspider enrich-profile pull-batch"
---
Body text describing the file-exchange contract.
"""


# ---------------------------------------------------------------------------
# Frontmatter splitting
# ---------------------------------------------------------------------------


def test_split_frontmatter_basic(gen):
    fm, body = gen.split_frontmatter(VALID_DESCRIPTOR)
    assert "name: enrich-drain" in fm
    assert body == "Body text describing the file-exchange contract."


def test_split_frontmatter_missing_fence_raises(gen):
    with pytest.raises(ValueError, match="missing leading"):
        gen.split_frontmatter("no frontmatter here\n")


def test_split_frontmatter_unterminated_raises(gen):
    with pytest.raises(ValueError, match="unterminated"):
        gen.split_frontmatter("---\nname: x\nbody with no closing fence\n")


# ---------------------------------------------------------------------------
# Descriptor parsing & validation
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    wf_dir = tmp_path / ".claude" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    path = wf_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_descriptor_valid(gen, tmp_path):
    path = _write(tmp_path, "enrich-drain.md", VALID_DESCRIPTOR)
    entry = gen.parse_descriptor(path, tmp_path)
    assert entry.name == "enrich-drain"
    assert entry.kind == "workflow-script"
    assert entry.status == "active"
    assert entry.entrypoint == ".claude/workflows/enrich-drain.js"
    assert entry.components == ["scripts/enrich/split_batch.py", "grantspider enrich-profile pull-batch"]
    assert entry.source == ".claude/workflows/enrich-drain.md"


def test_parse_descriptor_missing_required_field_raises(gen, tmp_path):
    text = "---\nname: x\nsummary: y\nkind: python-pipeline\n---\nbody"
    path = _write(tmp_path, "bad.md", text)
    with pytest.raises(ValueError, match="when_to_use"):
        gen.parse_descriptor(path, tmp_path)


def test_parse_descriptor_invalid_kind_raises(gen, tmp_path):
    text = "---\nname: x\nsummary: y\nwhen_to_use: z\nkind: bogus\n---\nbody"
    path = _write(tmp_path, "bad.md", text)
    with pytest.raises(ValueError, match="invalid kind"):
        gen.parse_descriptor(path, tmp_path)


def test_parse_descriptor_defaults_status_active(gen, tmp_path):
    text = "---\nname: x\nsummary: y\nwhen_to_use: z\nkind: python-pipeline\n---\nbody"
    path = _write(tmp_path, "p.md", text)
    assert gen.parse_descriptor(path, tmp_path).status == "active"


def test_parse_descriptor_coerces_phases(gen, tmp_path):
    text = (
        "---\nname: x\nsummary: y\nwhen_to_use: z\nkind: python-pipeline\n"
        "phases:\n  - name: Prepare\n    detail: build queue\n"
        "  - name: Verify\n    detail: check\n    model: opus\n---\nbody"
    )
    path = _write(tmp_path, "p.md", text)
    phases = gen.parse_descriptor(path, tmp_path).phases
    assert [(p.name, p.detail, p.model) for p in phases] == [
        ("Prepare", "build queue", ""),
        ("Verify", "check", "opus"),
    ]


# ---------------------------------------------------------------------------
# Drift check
# ---------------------------------------------------------------------------


def test_is_path_like(gen):
    assert gen._is_path_like("scripts/enrich/split_batch.py")
    assert gen._is_path_like("data/foo.json")
    assert not gen._is_path_like("grantspider enrich-profile pull-batch")  # spaces → command
    assert not gen._is_path_like("gaudi")  # no slash/dot → ambiguous, skip


def test_check_drift_flags_missing_path(gen, tmp_path):
    path = _write(tmp_path, "enrich-drain.md", VALID_DESCRIPTOR)
    entry = gen.parse_descriptor(path, tmp_path)
    warnings = gen.check_drift(entry, tmp_path)
    assert len(warnings) == 1
    assert "scripts/enrich/split_batch.py" in warnings[0]


def test_check_drift_silent_when_path_exists(gen, tmp_path):
    path = _write(tmp_path, "enrich-drain.md", VALID_DESCRIPTOR)
    entry = gen.parse_descriptor(path, tmp_path)
    (tmp_path / "scripts" / "enrich").mkdir(parents=True)
    (tmp_path / "scripts" / "enrich" / "split_batch.py").write_text("", encoding="utf-8")
    assert gen.check_drift(entry, tmp_path) == []


# ---------------------------------------------------------------------------
# Collection (valid + malformed coexist; malformed is skipped, not fatal)
# ---------------------------------------------------------------------------


def test_collect_descriptors_skips_malformed(gen, tmp_path):
    _write(tmp_path, "good.md", VALID_DESCRIPTOR)
    _write(tmp_path, "bad.md", "---\nname: only\n---\nbody")  # missing required fields
    entries, warnings = gen.collect_descriptors(tmp_path)
    assert [e.name for e in entries] == ["enrich-drain"]
    assert any("bad.md" in w and "SKIPPED" in w for w in warnings)
    assert any("split_batch.py" in w for w in warnings)  # drift warning from the good one


def test_collect_descriptors_empty_when_no_dir(gen, tmp_path):
    entries, warnings = gen.collect_descriptors(tmp_path)
    assert entries == []
    assert warnings == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_markdown_includes_workflow(gen, tmp_path):
    path = _write(tmp_path, "enrich-drain.md", VALID_DESCRIPTOR)
    entry = gen.parse_descriptor(path, tmp_path)
    body = gen.render_markdown([entry])
    assert "# Workflow Registry" in body
    assert "Found **1** workflow(s)" in body
    assert "## enrich-drain" in body
    assert "workflow-script" in body
    assert "`scripts/enrich/split_batch.py`" in body
    assert "_Descriptor: `.claude/workflows/enrich-drain.md`_" in body


def test_render_markdown_empty(gen):
    body = gen.render_markdown([])
    assert "Found **0** workflow(s)" in body
    assert "No workflow descriptors found" in body
