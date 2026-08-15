# ABOUTME: Tests for shared/scripts/tools/generate_tool_registry.py.
# ABOUTME: Covers Click/argparse --help parsing, sidecar config loading, fail-soft discovery.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    """Load the shared canonical script as a module under a unique name.

    Importing by file path keeps the test independent of where the script
    has been sown into the repo (``shared/...`` vs ``scripts/tools/...``).
    """
    script_path = Path(__file__).resolve().parent.parent / "shared" / "scripts" / "tools" / "generate_tool_registry.py"
    spec = importlib.util.spec_from_file_location("oversteward_tool_registry_shared", script_path)
    assert spec and spec.loader, "spec_from_file_location returned no loader"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_module()


# ---------------------------------------------------------------------------
# Sidecar config loader
# ---------------------------------------------------------------------------


def test_load_registry_config_missing_returns_empty(gen, tmp_path):
    cfg = gen.load_registry_config(tmp_path)
    assert cfg.categories == {}
    assert cfg.package_categories == {}


def test_load_registry_config_parses_toml(gen, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "tool_registry.toml").write_text(
        '[categories]\ncrawl = "Crawling"\ndb = "Database"\n'
        '[package_categories]\ncli = "CLI"\n',
        encoding="utf-8",
    )
    cfg = gen.load_registry_config(tmp_path)
    assert cfg.categories == {"crawl": "Crawling", "db": "Database"}
    assert cfg.package_categories == {"cli": "CLI"}


def test_normalize_category_uses_config(gen):
    cfg = gen.RegistryConfig(categories={"db": "Database"}, package_categories={})
    assert gen.normalize_category("db", cfg) == "Database"
    assert gen.normalize_category("research", cfg) == "Research"
    assert gen.normalize_category("my_thing", cfg) == "My Thing"


# ---------------------------------------------------------------------------
# Click subcommand parsing
# ---------------------------------------------------------------------------


CLICK_HELP_BASIC = """\
Usage: grantspider [OPTIONS] COMMAND [ARGS]...

  GrantSpider — grant research data pipeline.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  audit       Audit-quality commands.
  b2          B2 bucket maintenance.
  cleanup     Cleanup operations.
  hygiene     URL and grant hygiene.
"""

CLICK_HELP_NO_DESC = """\
Usage: tool [OPTIONS] COMMAND [ARGS]...

Commands:
  alpha
  beta
"""

CLICK_HELP_WRAPPED = """\
Usage: tool [OPTIONS] COMMAND [ARGS]...

Commands:
  long        This description wraps onto a second
              continuation line.
  short       One-liner.
"""


def test_parse_click_commands_basic(gen):
    subs = gen.parse_click_commands(CLICK_HELP_BASIC)
    assert [(s.name, s.description) for s in subs] == [
        ("audit", "Audit-quality commands."),
        ("b2", "B2 bucket maintenance."),
        ("cleanup", "Cleanup operations."),
        ("hygiene", "URL and grant hygiene."),
    ]


def test_parse_click_commands_no_description(gen):
    subs = gen.parse_click_commands(CLICK_HELP_NO_DESC)
    assert [(s.name, s.description) for s in subs] == [("alpha", ""), ("beta", "")]


def test_parse_click_commands_wrapped_description(gen):
    subs = gen.parse_click_commands(CLICK_HELP_WRAPPED)
    by_name = {s.name: s.description for s in subs}
    assert "This description wraps onto a second continuation line." in by_name["long"]
    assert by_name["short"] == "One-liner."


def test_parse_click_commands_returns_empty_on_no_block(gen):
    assert gen.parse_click_commands("Usage: tool\n\nOptions:\n  --help") == []


# ---------------------------------------------------------------------------
# argparse subcommand parsing
# ---------------------------------------------------------------------------


ARGPARSE_HELP = """\
usage: tool [-h] {alpha,beta,gamma} ...

A demo tool.

positional arguments:
  {alpha,beta,gamma}
    alpha         Do the alpha thing.
    beta          Do the beta thing.
    gamma         Do the gamma thing.

options:
  -h, --help     show this help message and exit
"""


def test_parse_argparse_subcommands(gen):
    subs = gen.parse_argparse_subcommands(ARGPARSE_HELP)
    assert [(s.name, s.description) for s in subs] == [
        ("alpha", "Do the alpha thing."),
        ("beta", "Do the beta thing."),
        ("gamma", "Do the gamma thing."),
    ]


def test_parse_argparse_subcommands_returns_empty_on_no_block(gen):
    assert gen.parse_argparse_subcommands("usage: tool [-h]\n\noptions:\n  -h help") == []


# ---------------------------------------------------------------------------
# discover_subcommands fail-soft behavior
# ---------------------------------------------------------------------------


def test_discover_subcommands_missing_command_is_silent(gen):
    """A command that isn't on PATH should yield [] without raising."""
    assert gen.discover_subcommands("oversteward_definitely_not_a_real_command_xyz") == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_console_scripts_section_lists_subcommand_summary(gen):
    entry = gen.ToolEntry(
        name="grantspider",
        location="src/grantspider/cli/__init__.py",
        command="grantspider",
        description="Grant research data pipeline.",
        category="CLI",
        tool_type=gen.ToolType.CONSOLE_SCRIPT,
        subcommands=[
            gen.Subcommand(name="audit", description="Audit-quality commands."),
            gen.Subcommand(name="b2", description="B2 bucket maintenance."),
        ],
    )
    lines = gen._render_console_scripts_section([entry])
    body = "\n".join(lines)
    assert "audit, b2" in body


def test_render_subcommands_section_emits_per_command_tables(gen):
    entry = gen.ToolEntry(
        name="grantspider",
        location="src/grantspider/cli/__init__.py",
        command="grantspider",
        description="Grant research data pipeline.",
        category="CLI",
        tool_type=gen.ToolType.CONSOLE_SCRIPT,
        subcommands=[
            gen.Subcommand(name="audit", description="Audit-quality commands."),
        ],
    )
    body = "\n".join(gen._render_subcommands_section([entry]))
    assert "### `grantspider`" in body
    assert "`grantspider audit`" in body
    assert "Audit-quality commands." in body


def test_render_subcommands_section_returns_empty_when_none(gen):
    entry = gen.ToolEntry(
        name="thing",
        location="src/thing.py",
        command="thing",
        description="A thing.",
        category="General",
        tool_type=gen.ToolType.CONSOLE_SCRIPT,
    )
    assert gen._render_subcommands_section([entry]) == []
