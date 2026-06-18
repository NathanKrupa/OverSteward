# ABOUTME: Tests for the cross-repo issue filer — the Telegraph's relay primitive.
# ABOUTME: Pure composition (labels, body, argv, URL parse) + flow with an injected runner.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_filer():
    """Load the canonical shared script by file path (no install needed)."""
    rel = Path("shared") / "scripts" / "telegraph" / "file_cross_repo_issue.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("file_cross_repo_issue", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


filer = _load_filer()


# --- compose_labels -------------------------------------------------------


def test_compose_labels_adds_provenance_when_source_given():
    assert filer.compose_labels("needs-scoping", "grantspider") == [
        "needs-scoping",
        "from:grantspider",
    ]


def test_compose_labels_omits_provenance_without_source():
    assert filer.compose_labels("needs-scoping", None) == ["needs-scoping"]


def test_compose_labels_rejects_empty_primary_label():
    with pytest.raises(ValueError):
        filer.compose_labels("", "grantspider")


# --- compose_body ---------------------------------------------------------


def test_compose_body_appends_provenance_footer():
    out = filer.compose_body(
        "Need a funder_ein column.",
        "grantspider",
        "https://github.com/NathanKrupa/grantspider/issues/170",
    )
    assert out.startswith("Need a funder_ein column.")
    assert "grantspider" in out
    assert "issues/170" in out


def test_compose_body_without_source_is_unchanged():
    assert filer.compose_body("Body only.", None, None) == "Body only."


def test_compose_body_with_source_but_no_backlink_still_notes_origin():
    out = filer.compose_body("Body.", "grantspider", None)
    assert "grantspider" in out
    assert "Body." in out


# --- build_issue_argv -----------------------------------------------------


def test_build_issue_argv_repeats_label_flags():
    argv = filer.build_issue_argv(
        "NathanKrupa/aigranthelper", "Title", "Body", ["needs-scoping", "from:grantspider"]
    )
    assert argv[:5] == ["gh", "issue", "create", "--repo", "NathanKrupa/aigranthelper"]
    assert "--title" in argv and "Title" in argv
    assert "--body" in argv and "Body" in argv
    assert argv.count("--label") == 2
    label_idx = [i for i, a in enumerate(argv) if a == "--label"]
    assert {argv[i + 1] for i in label_idx} == {"needs-scoping", "from:grantspider"}


def test_build_issue_argv_rejects_empty_repo():
    with pytest.raises(ValueError):
        filer.build_issue_argv("", "T", "B", ["needs-scoping"])


def test_build_issue_argv_rejects_empty_title():
    with pytest.raises(ValueError):
        filer.build_issue_argv("owner/repo", "", "B", ["needs-scoping"])


# --- parse_issue_url ------------------------------------------------------


def test_parse_issue_url_returns_last_url_line():
    stdout = (
        "Creating issue in NathanKrupa/aigranthelper\n"
        "https://github.com/NathanKrupa/aigranthelper/issues/42\n"
    )
    assert (
        filer.parse_issue_url(stdout)
        == "https://github.com/NathanKrupa/aigranthelper/issues/42"
    )


def test_parse_issue_url_raises_without_url():
    with pytest.raises(ValueError):
        filer.parse_issue_url("no url here\n")


# --- file_cross_repo_issue (flow with injected runner) --------------------


def test_file_cross_repo_issue_files_and_returns_url():
    calls = []

    def fake_run(argv):
        calls.append(argv)
        return "https://github.com/NathanKrupa/aigranthelper/issues/7\n"

    url = filer.file_cross_repo_issue(
        "NathanKrupa/aigranthelper",
        "Add funder_ein",
        "Need a funder_ein column.",
        source_repo="grantspider",
        backlink="https://github.com/NathanKrupa/grantspider/issues/170",
        run=fake_run,
    )
    assert url == "https://github.com/NathanKrupa/aigranthelper/issues/7"
    assert len(calls) == 1
    argv = calls[0]
    labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
    assert "needs-scoping" in labels
    assert "from:grantspider" in labels
    body = argv[argv.index("--body") + 1]
    assert "issues/170" in body


def test_file_cross_repo_issue_defaults_to_needs_scoping():
    captured = {}

    def fake_run(argv):
        captured["argv"] = argv
        return "https://github.com/owner/repo/issues/1\n"

    filer.file_cross_repo_issue("owner/repo", "T", "B", source_repo="grantspider", run=fake_run)
    labels = [captured["argv"][i + 1] for i, a in enumerate(captured["argv"]) if a == "--label"]
    assert "needs-scoping" in labels


def test_file_cross_repo_issue_conducted_mode_uses_ready_label():
    captured = {}

    def fake_run(argv):
        captured["argv"] = argv
        return "https://github.com/owner/repo/issues/2\n"

    filer.file_cross_repo_issue(
        "owner/repo",
        "T",
        "B",
        label="ready-for-agent",
        source_repo="aigranthelper",
        run=fake_run,
    )
    labels = [captured["argv"][i + 1] for i, a in enumerate(captured["argv"]) if a == "--label"]
    assert "ready-for-agent" in labels
    assert "from:aigranthelper" in labels
