# ABOUTME: Canonical workflow-registry generator — shared across pickup repos (AG, GS, FI, OS, …).
# ABOUTME: Source at OverSteward/shared/scripts/workflows/; deployed to <repo>/scripts/workflows/.

"""
Workflow Registry Generator
===========================
Aggregates hand-authored workflow *descriptors* into a structured markdown
catalog at ``data/workflow_registry.md``. A "workflow" is a multi-step
Python↔Claude process (a Claude Agent SDK Workflow script, a Python pipeline,
or an operator-in-loop loop). Unlike the tool registry, this generator does NOT
sniff the filesystem — it only reads descriptors, so the registry is decoupled
from implementation shape.

Descriptor convention
---------------------
One markdown file per workflow at ``.claude/workflows/<name>.md`` with YAML
frontmatter plus a free-form body::

    ---
    name: enrich-drain
    summary: One-line what-it-does.       # required
    when_to_use: When to reach for this.  # required
    kind: workflow-script   # required: workflow-script | python-pipeline | operator-loop
    status: active          # optional (default active): active | experimental | deprecated
    entrypoint: .claude/workflows/enrich-drain.js   # optional: how you start it
    components:             # optional: files/commands it touches
      - scripts/enrich/split_batch.py
      - "grantspider enrich-profile pull-batch"
    phases:                 # optional (omit for workflow-script — see .js meta)
      - name: Generate
        detail: N Sonnet agents draft profiles per slice (no write)
      - name: Verify
        detail: Opus grounds + repairs, then apply
        model: opus
    ---
    Free-form body: the file-exchange contract, gotchas, links to docs/PRs.

Drift check: any ``components`` entry that looks like a path (no spaces, and
contains ``/`` or ``.``) is checked for existence on disk. A missing path emits
a warning but does not fail the run — descriptors are hand-authored and the
warning is the signal that one has drifted from reality.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Convention strings
# ---------------------------------------------------------------------------

_WORKFLOWS_DIR = Path(".claude") / "workflows"
_DESCRIPTOR_GLOB = "*.md"
_FENCE = "---"

_REQUIRED_FIELDS = ("name", "summary", "when_to_use", "kind")
_VALID_KINDS = ("workflow-script", "python-pipeline", "operator-loop")
_VALID_STATUSES = ("active", "experimental", "deprecated")
_DEFAULT_STATUS = "active"

_MD_RULE = "---"
_MD_CELL_SEP = " | "


def _md_section_separator() -> list[str]:
    return ["", _MD_RULE, ""]


def _md_row(cells: tuple[str, ...]) -> str:
    return "| " + _MD_CELL_SEP.join(cells) + " |"


def _md_divider_row(column_count: int) -> str:
    return _md_row((_MD_RULE,) * column_count)


def _md_escape(text: str) -> str:
    """Escape pipe and newline so free text survives inside a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Phase:
    name: str
    detail: str = ""
    model: str = ""


@dataclass
class WorkflowEntry:
    name: str
    summary: str
    when_to_use: str
    kind: str
    status: str
    entrypoint: str
    components: list[str] = field(default_factory=list)
    phases: list[Phase] = field(default_factory=list)
    body: str = ""
    source: str = ""  # descriptor path, POSIX-normalized, relative to repo root


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(frontmatter, body)``. Frontmatter is the YAML between the
    leading ``---`` fence and the next ``---`` on its own line; body is the
    remainder. Raises ``ValueError`` if no frontmatter block is present."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise ValueError("missing leading '---' frontmatter fence")
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :]).strip()
    raise ValueError("unterminated frontmatter (no closing '---')")


def _coerce_phases(raw: object) -> list[Phase]:
    phases: list[Phase] = []
    if not isinstance(raw, list):
        return phases
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            phases.append(
                Phase(
                    name=str(item["name"]),
                    detail=str(item.get("detail", "")),
                    model=str(item.get("model", "")),
                )
            )
    return phases


def parse_descriptor(path: Path, root: Path) -> WorkflowEntry:
    """Parse one descriptor file into a ``WorkflowEntry``. Raises ``ValueError``
    on malformed frontmatter, non-mapping YAML, missing required fields, or an
    invalid ``kind``."""
    frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")

    missing = [f for f in _REQUIRED_FIELDS if not data.get(f)]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    kind = str(data["kind"])
    if kind not in _VALID_KINDS:
        raise ValueError(f"invalid kind {kind!r} (expected one of {', '.join(_VALID_KINDS)})")

    status = str(data.get("status", _DEFAULT_STATUS))
    if status not in _VALID_STATUSES:
        valid = ", ".join(_VALID_STATUSES)
        print(
            f"  Warning: {path.name}: unknown status {status!r} (expected one of {valid})",
            file=sys.stderr,
        )

    components = [str(c) for c in data.get("components", []) or []]

    return WorkflowEntry(
        name=str(data["name"]),
        summary=str(data["summary"]),
        when_to_use=str(data["when_to_use"]),
        kind=kind,
        status=status,
        entrypoint=str(data.get("entrypoint", "")),
        components=components,
        phases=_coerce_phases(data.get("phases")),
        body=body,
        source=path.relative_to(root).as_posix(),
    )


# ---------------------------------------------------------------------------
# Drift check
# ---------------------------------------------------------------------------


def _is_path_like(component: str) -> bool:
    """A component is a checkable filesystem path if it has no spaces (commands
    have spaces) and looks path-shaped (contains a slash or a dot)."""
    return " " not in component and ("/" in component or "." in component)


def check_drift(entry: WorkflowEntry, root: Path) -> list[str]:
    """Return human-readable warnings for ``components`` paths that don't exist."""
    warnings: list[str] = []
    for component in entry.components:
        if _is_path_like(component) and not (root / component).exists():
            warnings.append(f"{entry.source}: component path not found: {component}")
    return warnings


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_descriptors(root: Path) -> tuple[list[WorkflowEntry], list[str]]:
    """Parse every descriptor under ``.claude/workflows/``. Returns the parsed
    entries (sorted by name) and a list of warnings (parse failures + drift)."""
    workflows_dir = root / _WORKFLOWS_DIR
    entries: list[WorkflowEntry] = []
    warnings: list[str] = []
    if not workflows_dir.is_dir():
        return entries, warnings
    for path in sorted(workflows_dir.glob(_DESCRIPTOR_GLOB)):
        try:
            entry = parse_descriptor(path, root)
        except (OSError, ValueError) as exc:
            warnings.append(f"{path.relative_to(root).as_posix()}: SKIPPED — {exc}")
            continue
        entries.append(entry)
        warnings.extend(check_drift(entry, root))
    entries.sort(key=lambda e: e.name.lower())
    return entries, warnings


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _render_header(total: int) -> list[str]:
    timestamp = datetime.now(tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    return [
        "# Workflow Registry",
        "",
        f"> Auto-generated by `scripts/workflows/generate_workflow_registry.py` on {timestamp}",
        f"> Found **{total}** workflow(s). Descriptors live in `.claude/workflows/*.md`.",
        *_md_section_separator(),
    ]


def _render_summary_table(entries: list[WorkflowEntry]) -> list[str]:
    lines = [
        _md_row(("Name", "Kind", "Status", "Summary", "When to use")),
        _md_divider_row(5),
    ]
    for e in entries:
        lines.append(
            _md_row(
                (
                    f"[{e.name}](#{e.name.lower().replace(' ', '-')})",
                    e.kind,
                    e.status,
                    _md_escape(e.summary),
                    _md_escape(e.when_to_use),
                )
            )
        )
    lines += _md_section_separator()
    return lines


def _render_workflow_section(entry: WorkflowEntry) -> list[str]:
    lines = [f"## {entry.name}", ""]
    meta = f"**Kind:** {entry.kind} · **Status:** {entry.status}"
    if entry.entrypoint:
        meta += f" · **Entry point:** `{entry.entrypoint}`"
    lines += [meta, "", entry.summary, "", f"**When to use:** {entry.when_to_use}", ""]

    if entry.components:
        lines.append("**Components:**")
        lines.append("")
        for component in entry.components:
            lines.append(f"- `{component}`")
        lines.append("")

    if entry.phases:
        lines.append(_md_row(("Phase", "Detail", "Model")))
        lines.append(_md_divider_row(3))
        for phase in entry.phases:
            lines.append(_md_row((phase.name, _md_escape(phase.detail), phase.model or "—")))
        lines.append("")

    if entry.body:
        lines += [entry.body, ""]

    lines.append(f"_Descriptor: `{entry.source}`_")
    lines += _md_section_separator()
    return lines


def render_markdown(entries: list[WorkflowEntry]) -> str:
    lines: list[str] = []
    lines.extend(_render_header(len(entries)))
    if entries:
        lines.extend(_render_summary_table(entries))
        for entry in entries:
            lines.extend(_render_workflow_section(entry))
    else:
        lines += [
            "_No workflow descriptors found. Add one at `.claude/workflows/<name>.md`._",
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Scanning .claude/workflows/ for descriptors...")
    entries, warnings = collect_descriptors(PROJECT_ROOT)
    for warning in warnings:
        print(f"  Warning: {warning}", file=sys.stderr)
    out_path = PROJECT_ROOT / "data" / "workflow_registry.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(entries), encoding="utf-8")
    print(f"\nWrote {out_path.relative_to(PROJECT_ROOT)} ({len(entries)} workflow(s))")


if __name__ == "__main__":
    main()
