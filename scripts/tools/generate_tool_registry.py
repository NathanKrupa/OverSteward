# ABOUTME: Canonical tool-registry generator — shared across pickup repos (AG, GS, FI, OS, …).
# ABOUTME: Source lives at OverSteward/shared/scripts/tools/; deployed to <repo>/scripts/tools/.

"""
Tool Registry Generator
=======================
Introspects the codebase to discover all CLI tools, scripts, and entry points.
Outputs a structured markdown file at ``data/tool_registry.md``.

Discovery sources:
  1. Console scripts from pyproject.toml ``[project.scripts]``
  2. Runnable scripts in ``scripts/`` (detected via ABOUTME, argparse, click, ``__main__``)
  3. Module entry points (``__main__.py`` files)
  4. Streamlit apps
  5. Root-level runnable scripts

Console scripts are augmented with **subcommand discovery**: each console script
is invoked with ``--help`` (subprocess, timeout) and the resulting ``Commands:``
block (Click) or ``{a,b,c}`` subparsers block (argparse) is parsed. Failure is
silent — repos without installed console scripts simply skip the augmentation.

Project-specific category names live in an optional sidecar at
``data/tool_registry.toml``:

    [categories]              # scripts/<dir> → display name
    crawl = "Crawling"
    db = "Database"

    [package_categories]      # src/<package>/<subpkg> → display name
    cli = "CLI"

Description extraction priority:
  ABOUTME comments > module docstring > argparse description > Click docstring
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Convention strings
# ---------------------------------------------------------------------------

_ABOUTME_PREFIX = "ABOUTME:"
_ABOUTME_HASH_PREFIX = "# ABOUTME:"
_SCRIPTS_DIR_NAME = "scripts"
_DEFAULT_CATEGORY = "general"
_PY_EXT = ".py"
_PY_GLOB = "*.py"
_MD_RULE = "---"
_MD_CELL_SEP = " | "
_MD_DIVIDER_CELL = "---"

_HELP_TIMEOUT_SECONDS = 10
_HELP_FLAG = "--help"


def _md_section_separator() -> list[str]:
    return ["", _MD_RULE, ""]


def _md_row(cells: tuple[str, ...]) -> str:
    return "| " + _MD_CELL_SEP.join(cells) + " |"


def _md_divider_row(column_count: int) -> str:
    return _md_row((_MD_DIVIDER_CELL,) * column_count)


# ---------------------------------------------------------------------------
# Sidecar config loader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryConfig:
    """Project-specific category overrides loaded from ``data/tool_registry.toml``."""

    categories: dict[str, str] = field(default_factory=dict)
    package_categories: dict[str, str] = field(default_factory=dict)


def load_registry_config(root: Path) -> RegistryConfig:
    config_path = root / "data" / "tool_registry.toml"
    if not config_path.exists():
        return RegistryConfig()
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"  Warning: failed to read {config_path}: {exc}", file=sys.stderr)
        return RegistryConfig()
    return RegistryConfig(
        categories={str(k): str(v) for k, v in data.get("categories", {}).items()},
        package_categories={str(k): str(v) for k, v in data.get("package_categories", {}).items()},
    )


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class ToolType(StrEnum):
    CONSOLE_SCRIPT = "console_script"
    MODULE_ENTRY = "module_entry"
    STREAMLIT = "streamlit"
    SCRIPT = "script"
    ROOT_SCRIPT = "root_script"


TOOL_TYPE_PRIORITY: dict[ToolType, int] = {
    ToolType.CONSOLE_SCRIPT: 0,
    ToolType.MODULE_ENTRY: 1,
    ToolType.STREAMLIT: 2,
    ToolType.SCRIPT: 3,
    ToolType.ROOT_SCRIPT: 4,
}


@dataclass
class Subcommand:
    name: str
    description: str


@dataclass
class ToolEntry:
    name: str
    location: str
    command: str
    description: str
    category: str
    tool_type: ToolType
    internal: bool = False
    subcommands: list[Subcommand] = field(default_factory=list)

    @property
    def priority(self) -> int:
        return TOOL_TYPE_PRIORITY.get(self.tool_type, 99)


# ---------------------------------------------------------------------------
# Category normalization
# ---------------------------------------------------------------------------


def normalize_category(raw: str, config: RegistryConfig) -> str:
    return config.categories.get(raw.lower(), raw.replace("_", " ").title())


def _infer_console_script_category(module_path: str, config: RegistryConfig) -> str:
    parts = module_path.split(".")
    if len(parts) > 1:
        subpkg = parts[1]
        return config.package_categories.get(subpkg, normalize_category(subpkg, config))
    return "General"


# ---------------------------------------------------------------------------
# Description extraction helpers
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def extract_aboutme(path: Path) -> str | None:
    text = _read_file(path)
    if not text:
        return None
    lines = text.splitlines()[:10]
    aboutme_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        for prefix in (_ABOUTME_HASH_PREFIX, _ABOUTME_PREFIX):
            if stripped.startswith(prefix):
                aboutme_lines.append(stripped[len(prefix) :].strip())
                break
    return " — ".join(aboutme_lines) if aboutme_lines else None


def extract_module_docstring(path: Path) -> str | None:
    text = _read_file(path)
    if not text:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return None
    doc = ast.get_docstring(tree)
    if not doc:
        return None
    for line in doc.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("ABOUTME"):
            return stripped
    return None


def extract_argparse_description(path: Path) -> str | None:
    text = _read_file(path)
    if not text:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            name = None
        if name != "ArgumentParser":
            continue
        for kw in node.keywords:
            if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                val = kw.value.value
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return None


def extract_click_group_docstring(path: Path) -> str | None:
    text = _read_file(path)
    if not text:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            dec_str = ast.dump(dec)
            if "group" in dec_str or "command" in dec_str:
                doc = ast.get_docstring(node)
                if doc:
                    return doc.strip().splitlines()[0].strip()
    return None


def extract_description(path: Path) -> str:
    for extractor in (
        extract_aboutme,
        extract_module_docstring,
        extract_argparse_description,
        extract_click_group_docstring,
    ):
        result = extractor(path)
        if result:
            return result
    return "(no description found)"


# ---------------------------------------------------------------------------
# CLI detection
# ---------------------------------------------------------------------------


def _has_main_guard(text: str) -> bool:
    return bool(re.search(r"""if\s+__name__\s*==\s*['"]__main__['"]""", text))


def _imports_module(text: str, module: str) -> bool:
    pattern = rf"(?:^|\s)import\s+{module}|from\s+{module}\s+import"
    return bool(re.search(pattern, text, re.MULTILINE))


def is_cli_tool(path: Path) -> bool:
    text = _read_file(path)
    if not text:
        return False
    if _ABOUTME_PREFIX in text[:500]:
        return True
    if _has_main_guard(text):
        return True
    return _imports_module(text, "argparse") or _imports_module(text, "click")


# ---------------------------------------------------------------------------
# Skip rules
# ---------------------------------------------------------------------------

_SKIP_DIRS = (".venv", "site-packages", "node_modules", ".conda", "__pycache__")


def _should_skip(rel_str: str) -> bool:
    return any(skip in rel_str for skip in _SKIP_DIRS)


# ---------------------------------------------------------------------------
# Subcommand discovery (runtime --help parsing)
# ---------------------------------------------------------------------------

_CLICK_COMMANDS_HEADER = re.compile(r"^Commands:\s*$")
_CLICK_COMMAND_LINE = re.compile(r"^\s{2,}(\S+)(?:\s{2,}(.*))?$")
_ARGPARSE_SUBPARSERS_BLOCK = re.compile(r"^\s{2,}\{([^}]+)\}\s*$", re.MULTILINE)
_OPTIONAL_HEADER = re.compile(r"^(options:|optional arguments:)\s*$", re.IGNORECASE)


def _click_line_kind(raw: str) -> tuple[str, str, str]:
    """Classify one line within the Click ``Commands:`` block.

    Returns ``(kind, name, desc)``: kind is ``"blank"``, ``"command"``,
    ``"wrap"``, or ``"end"``. ``name`` and ``desc`` are populated only for
    ``"command"``. ``"wrap"`` lines carry the continuation text in ``desc``.
    """
    if not raw.strip():
        return ("blank", "", "")
    match = _CLICK_COMMAND_LINE.match(raw)
    if match and not raw.startswith("    "):
        return ("command", match.group(1), (match.group(2) or "").strip())
    if raw.startswith("    "):
        return ("wrap", "", raw.strip())
    return ("end", "", "")


def parse_click_commands(help_text: str) -> list[Subcommand]:
    """Parse the ``Commands:`` block from Click ``--help`` output."""
    in_commands = False
    out: list[Subcommand] = []
    last: Subcommand | None = None
    for raw in help_text.splitlines():
        if _CLICK_COMMANDS_HEADER.match(raw):
            in_commands = True
            continue
        if not in_commands:
            continue
        kind, name, desc = _click_line_kind(raw)
        if kind == "blank":
            if out:
                break
            continue
        if kind == "command":
            last = Subcommand(name=name, description=desc)
            out.append(last)
        elif kind == "wrap" and last is not None:
            last.description = (last.description + " " + desc).strip()
        else:
            break
    return out


_ARGPARSE_DETAIL_LINE = re.compile(r"^\s{4,}(\S+)(?:\s{2,}(.*))?$")


def _argparse_iter_details(
    lines: list[str],
    start: int,
) -> Iterator[tuple[str, str]]:
    """Yield ``(name, desc)`` rows from the argparse subparsers detail block."""
    for raw in lines[start:]:
        if not raw.strip():
            yield ("__blank__", "")
            continue
        if _OPTIONAL_HEADER.match(raw.strip()):
            yield ("__end__", "")
            return
        m = _ARGPARSE_DETAIL_LINE.match(raw)
        if m:
            yield (m.group(1), (m.group(2) or "").strip())


def parse_argparse_subcommands(help_text: str) -> list[Subcommand]:
    """Parse argparse subparsers from ``--help`` output."""
    match = _ARGPARSE_SUBPARSERS_BLOCK.search(help_text)
    if not match:
        return []
    names = {n.strip() for n in match.group(1).split(",") if n.strip()}
    start = help_text[: match.start()].count("\n") + 1
    out: list[Subcommand] = []
    seen: set[str] = set()
    for name, desc in _argparse_iter_details(help_text.splitlines(), start):
        if name == "__end__":
            break
        if name == "__blank__":
            if out:
                break
            continue
        if name not in names or name in seen:
            continue
        out.append(Subcommand(name=name, description=desc))
        seen.add(name)
    return out


def discover_subcommands(command_name: str) -> list[Subcommand]:
    """Invoke ``<command> --help`` and parse subcommands. Fail-soft on any error."""
    if not shutil.which(command_name):
        return []
    try:
        # command_name originates from pyproject.toml [project.scripts]
        # — trusted project config under version control, not user input.
        # No shell, explicit argv, fixed --help flag.
        result = subprocess.run(  # nosec B603
            [command_name, _HELP_FLAG],
            capture_output=True,
            text=True,
            timeout=_HELP_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError:
        # Catch each kind separately rather than `except (A, B):` — the
        # tuple form is rewritten differently across pickup repos (AG
        # strips parens via PEP 758; GS forbids the unparen form). Two
        # arms stay byte-identical in both.
        return []
    except subprocess.TimeoutExpired:
        return []
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if not output.strip():
        return []
    subs = parse_click_commands(output)
    if subs:
        return subs
    return parse_argparse_subcommands(output)


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def _resolve_console_script_path(module_path: str) -> tuple[Path, Path]:
    """Resolve a dotted module path to (relative, absolute) source paths.

    Tries module form ``src/<a/b>.py`` first, then package form
    ``src/<a/b>/__init__.py``, then flat layout. Returns the best candidate
    even if missing — the caller surfaces ``(module not found)`` via the
    ``file_abs.exists()`` check.
    """
    parts = module_path.split(".")
    for layout_root in (Path("src"), Path()):
        module_rel = layout_root / Path(*parts).with_suffix(".py")
        module_abs = PROJECT_ROOT / module_rel
        if module_abs.exists():
            return module_abs, module_rel
        pkg_rel = layout_root / Path(*parts) / "__init__.py"
        pkg_abs = PROJECT_ROOT / pkg_rel
        if pkg_abs.exists():
            return pkg_abs, pkg_rel
    fallback_rel = Path("src") / Path(*parts).with_suffix(".py")
    return PROJECT_ROOT / fallback_rel, fallback_rel


def collect_console_scripts(config: RegistryConfig) -> list[ToolEntry]:
    toml_path = PROJECT_ROOT / "pyproject.toml"
    if not toml_path.exists():
        return []
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    scripts = data.get("project", {}).get("scripts", {})
    entries: list[ToolEntry] = []
    for cmd_name, entry_point in scripts.items():
        module_path = entry_point.split(":")[0]
        file_abs, file_rel = _resolve_console_script_path(module_path)
        desc = extract_description(file_abs) if file_abs.exists() else "(module not found)"
        entries.append(
            ToolEntry(
                name=cmd_name,
                location=str(file_rel).replace("\\", "/"),
                command=cmd_name,
                description=desc,
                category=_infer_console_script_category(module_path, config),
                tool_type=ToolType.CONSOLE_SCRIPT,
                subcommands=discover_subcommands(cmd_name),
            )
        )
    return entries


def _classify_script_entry(
    py_file: Path,
    rel: Path,
    config: RegistryConfig,
) -> tuple[str, str, bool]:
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == _SCRIPTS_DIR_NAME:
        raw_cat = parts[1]
        if raw_cat.endswith(_PY_EXT):
            raw_cat = _DEFAULT_CATEGORY
    else:
        raw_cat = _DEFAULT_CATEGORY
    internal = py_file.name.startswith("_")
    if internal:
        name = f"_{py_file.stem.lstrip('_')}"
    else:
        name = py_file.stem.lstrip("_").replace("_", " ").title()
    return name, normalize_category(raw_cat, config), internal


def collect_scripts_dir(config: RegistryConfig) -> list[ToolEntry]:
    scripts_dir = PROJECT_ROOT / _SCRIPTS_DIR_NAME
    if not scripts_dir.exists():
        return []
    entries: list[ToolEntry] = []
    for py_file in sorted(scripts_dir.rglob(_PY_GLOB)):
        if py_file.name.startswith("__") or _should_skip(str(py_file)) or not is_cli_tool(py_file):
            continue
        rel = py_file.relative_to(PROJECT_ROOT)
        rel_posix = str(rel).replace("\\", "/")
        name, category, internal = _classify_script_entry(py_file, rel, config)
        entries.append(
            ToolEntry(
                name=name,
                location=rel_posix,
                command=f"python {rel_posix}",
                description=extract_description(py_file),
                category=category,
                tool_type=ToolType.SCRIPT,
                internal=internal,
            )
        )
    return entries


def collect_module_entries(config: RegistryConfig) -> list[ToolEntry]:
    entries: list[ToolEntry] = []
    for main_file in sorted(PROJECT_ROOT.rglob("__main__.py")):
        rel = main_file.relative_to(PROJECT_ROOT)
        rel_str = str(rel).replace("\\", "/")
        if _should_skip(rel_str):
            continue
        module_dir = main_file.parent
        rel_dir = str(module_dir.relative_to(PROJECT_ROOT))
        module_name = rel_dir.replace("\\", ".").replace("/", ".")
        desc = extract_description(main_file)
        top_dir = rel.parts[0] if len(rel.parts) > 1 else _DEFAULT_CATEGORY
        category = normalize_category(top_dir.replace("_", " "), config)
        entries.append(
            ToolEntry(
                name=f"python -m {module_name}",
                location=rel_str,
                command=f"python -m {module_name}",
                description=desc,
                category=category,
                tool_type=ToolType.MODULE_ENTRY,
            )
        )
    return entries


def _streamlit_category(rel: Path, config: RegistryConfig) -> str:
    top_dir = rel.parts[0] if len(rel.parts) > 1 else _DEFAULT_CATEGORY
    if top_dir.endswith(_PY_EXT):
        return "Dashboard"
    return normalize_category(top_dir.replace("_", " "), config)


def collect_streamlit_apps(config: RegistryConfig) -> list[ToolEntry]:
    entries: list[ToolEntry] = []
    for py_file in sorted(PROJECT_ROOT.rglob(_PY_GLOB)):
        rel = py_file.relative_to(PROJECT_ROOT)
        rel_str = str(rel).replace("\\", "/")
        if _should_skip(rel_str):
            continue
        text = _read_file(py_file)
        if not _imports_module(text, "streamlit"):
            continue
        entries.append(
            ToolEntry(
                name=py_file.stem,
                location=rel_str,
                command=f"streamlit run {rel_str}",
                description=extract_description(py_file),
                category=_streamlit_category(rel, config),
                tool_type=ToolType.STREAMLIT,
            )
        )
    return entries


def collect_root_scripts(_config: RegistryConfig) -> list[ToolEntry]:
    entries: list[ToolEntry] = []
    for py_file in sorted(PROJECT_ROOT.glob(_PY_GLOB)):
        if py_file.name.startswith("__") or py_file.name.startswith("."):
            continue
        text = _read_file(py_file)
        if not text:
            continue
        if _ABOUTME_PREFIX not in text[:500] and not _has_main_guard(text):
            continue
        entries.append(
            ToolEntry(
                name=py_file.stem,
                location=py_file.name,
                command=f"python {py_file.name}",
                description=extract_description(py_file),
                category="Root",
                tool_type=ToolType.ROOT_SCRIPT,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def deduplicate(entries: list[ToolEntry]) -> list[ToolEntry]:
    by_location: dict[str, ToolEntry] = {}
    for entry in entries:
        loc = entry.location
        if loc not in by_location or entry.priority < by_location[loc].priority:
            by_location[loc] = entry
    return list(by_location.values())


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _group_entries(entries: list[ToolEntry]) -> tuple[list[ToolEntry], dict[str, list[ToolEntry]]]:
    console = sorted(
        [e for e in entries if e.tool_type == ToolType.CONSOLE_SCRIPT],
        key=lambda e: e.name,
    )
    categories: dict[str, list[ToolEntry]] = {}
    for entry in entries:
        if entry.tool_type == ToolType.CONSOLE_SCRIPT:
            continue
        categories.setdefault(entry.category, []).append(entry)
    for cat in categories:
        categories[cat].sort(key=lambda e: (e.internal, e.name.lower()))
    return console, categories


def _render_header(total: int, cat_count: int) -> list[str]:
    timestamp = datetime.now(tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    return [
        "# Tool Registry",
        "",
        f"> Auto-generated by `scripts/tools/generate_tool_registry.py` on {timestamp}",
        f"> Found **{total}** tools across **{cat_count}** categories.",
        *_md_section_separator(),
    ]


# Anchor split into a separate constant so the assignment stays under
# the strictest line-length limit across pickup repos (99 in GS, 120 in
# AG). f-string interpolation prevents ruff format from merging or
# rewrapping the literal differently between projects.
_TOC_ANCHOR_CONSOLE = "#console-scripts-installed-cli-commands"
_TOC_CONSOLE_LINK = f"- [Console Scripts (installed CLI commands)]({_TOC_ANCHOR_CONSOLE})"
_TOC_SUBCOMMANDS_LINK = "- [Console Script Subcommands](#console-script-subcommands)"


def _render_toc(console: list[ToolEntry], sorted_cats: list[str]) -> list[str]:
    lines = ["## Table of Contents", ""]
    if console:
        lines.append(_TOC_CONSOLE_LINK)
        if any(e.subcommands for e in console):
            lines.append(_TOC_SUBCOMMANDS_LINK)
    for cat in sorted_cats:
        anchor = cat.lower().replace(" ", "-").replace("/", "").replace("(", "").replace(")", "")
        lines.append(f"- [{cat}](#{anchor})")
    lines += _md_section_separator()
    return lines


def _render_console_scripts_section(console: list[ToolEntry]) -> list[str]:
    if not console:
        return []
    lines = [
        "## Console Scripts (installed CLI commands)",
        "",
        "Installed via `pip install -e .` — available as shell commands after activation.",
        "",
        _md_row(("Command", "Module", "Description", "Subcommands")),
        _md_divider_row(4),
    ]
    for e in console:
        sub_summary = ", ".join(sorted(s.name for s in e.subcommands)) if e.subcommands else "—"
        lines.append(_md_row((f"`{e.command}`", f"`{e.location}`", e.description, sub_summary)))
    lines += _md_section_separator()
    return lines


def _render_subcommands_section(console: list[ToolEntry]) -> list[str]:
    with_subs = [e for e in console if e.subcommands]
    if not with_subs:
        return []
    lines = ["## Console Script Subcommands", ""]
    for e in with_subs:
        lines.append(f"### `{e.command}`")
        lines.append("")
        lines.append(_md_row(("Subcommand", "Description")))
        lines.append(_md_divider_row(2))
        for sub in sorted(e.subcommands, key=lambda s: s.name):
            desc = sub.description or "—"
            lines.append(_md_row((f"`{e.command} {sub.name}`", desc)))
        lines.append("")
    lines += [_MD_RULE, ""]
    return lines


def _render_category_section(category: str, entries: list[ToolEntry]) -> list[str]:
    lines = [
        f"## {category}",
        "",
        _md_row(("Name", "Location", "Command", "Description")),
        _md_divider_row(4),
    ]
    for e in entries:
        name_display = f"_{e.name}_" if e.internal else e.name
        lines.append(_md_row((name_display, f"`{e.location}`", f"`{e.command}`", e.description)))
    lines += _md_section_separator()
    return lines


def render_markdown(entries: list[ToolEntry]) -> str:
    console, categories = _group_entries(entries)
    sorted_cats = sorted(categories.keys())
    cat_count = len(sorted_cats) + (1 if console else 0)

    lines: list[str] = []
    lines.extend(_render_header(total=len(entries), cat_count=cat_count))
    lines.extend(_render_toc(console, sorted_cats))
    lines.extend(_render_console_scripts_section(console))
    lines.extend(_render_subcommands_section(console))
    for cat in sorted_cats:
        lines.extend(_render_category_section(cat, categories[cat]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _run_collectors(config: RegistryConfig) -> list[ToolEntry]:
    collectors = [
        ("console scripts (pyproject.toml)", collect_console_scripts),
        ("scripts/ directory", collect_scripts_dir),
        ("module entry points (__main__.py)", collect_module_entries),
        ("Streamlit apps", collect_streamlit_apps),
        ("root-level scripts", collect_root_scripts),
    ]
    all_entries: list[ToolEntry] = []
    for label, collector in collectors:
        try:
            found = collector(config)
            print(f"  {label}: {len(found)} found")
            all_entries.extend(found)
        except (OSError, ValueError, ImportError, SyntaxError) as exc:
            print(f"  {label}: ERROR — {exc}", file=sys.stderr)
    return all_entries


def main() -> None:
    print("Scanning codebase for tools...")
    config = load_registry_config(PROJECT_ROOT)
    all_entries = _run_collectors(config)
    before = len(all_entries)
    all_entries = deduplicate(all_entries)
    deduped = before - len(all_entries)
    if deduped:
        print(f"  Deduplicated: {deduped} duplicates removed")
    out_path = PROJECT_ROOT / "data" / "tool_registry.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(all_entries), encoding="utf-8")
    print(f"\nWrote {out_path.relative_to(PROJECT_ROOT)} ({len(all_entries)} tools)")


if __name__ == "__main__":
    main()
