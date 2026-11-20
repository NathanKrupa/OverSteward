# ABOUTME: Audits which .claude/hooks/ scripts each managed repo ships and which ones it registers.
# ABOUTME: Reads origin/<branch> only (settings.json and agent-card frontmatter); never a working tree.

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from oversteward.dev_family import REGULAR_MODES, SYMLINK_MODE, GitRepo, RepoFamilyStatus

HOOKS_DIR = ".claude/hooks"
SETTINGS_PATH = ".claude/settings.json"
AGENTS_DIR = ".claude/agents"

REGISTERED = "registered"
PRESENT_UNREGISTERED = "present-unregistered"
REGISTERED_ABSENT = "registered-absent"

_NAME = r"[^/\s\"'$`\\]+\.py"
# The one command shape that registers a script: the project-dir variable followed by
# .claude/hooks/<name>.py as one whole shell word, bare or double-quoted (the whole path
# or the variable alone), behind any interpreter. Single quotes stop the shell expanding
# the variable, so a single-quoted path names a file that does not exist and registers
# nothing.
_REGISTRATION = re.compile(
    rf'(?<!\S)(?:"\$CLAUDE_PROJECT_DIR/\.claude/hooks/(?P<quoted>{_NAME})"'
    rf'|"\$CLAUDE_PROJECT_DIR"/\.claude/hooks/(?P<var_quoted>{_NAME})'
    rf"|\$CLAUDE_PROJECT_DIR/\.claude/hooks/(?P<bare>{_NAME}))(?!\S)"
)
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)^---[ \t]*\r?$", re.MULTILINE | re.DOTALL)


class _Unreadable(Exception):
    """A directory at the ref could not be listed, or a source on it could not be parsed."""


@dataclass(frozen=True)
class Registration:
    """One command that runs a hook script: the script, the file naming it, its event."""

    script: str
    source: str
    event: str


@dataclass(frozen=True)
class RepoHooks:
    """One repo's hook scripts and registrations at origin/<branch>, or why they were not read."""

    context_id: str
    branch: str
    unreadable: str | None = None
    present: frozenset[str] = frozenset()
    registrations: tuple[Registration, ...] = ()
    unshaped: tuple[str, ...] = ()

    def statuses(self) -> dict[str, str]:
        """Each script that is present or registered, with its status."""
        registered = {reg.script for reg in self.registrations}
        return {
            script: _status(script in self.present, script in registered)
            for script in sorted(self.present | registered)
        }


def _status(present: bool, registered: bool) -> str:
    if registered:
        return REGISTERED if present else REGISTERED_ABSENT
    return PRESENT_UNREGISTERED


def _delivers_a_file(git: GitRepo, ref: str, relpath: str, mode: bytes) -> bool:
    """A regular file, or a link ``GitRepo.resolve`` follows to one inside the tree."""
    if mode in REGULAR_MODES:
        return True
    return mode == SYMLINK_MODE and git.resolve(ref, relpath) != relpath


def _present_scripts(git: GitRepo, ref: str) -> frozenset[str]:
    listing = git.entries(ref, HOOKS_DIR)
    if listing is None:
        raise _Unreadable(f"could not list {HOOKS_DIR}/ at {ref}")
    return frozenset(
        name
        for name, mode in listing.items()
        if name.endswith(".py") and _delivers_a_file(git, ref, f"{HOOKS_DIR}/{name}", mode)
    )


def _commands(hooks: Any) -> Iterator[tuple[str, str]]:
    """Every (event, command) under a ``hooks`` mapping, in Claude Code's settings shape."""
    if not isinstance(hooks, dict):
        return
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            inner = group.get("hooks") if isinstance(group, dict) else None
            for hook in inner if isinstance(inner, list) else []:
                command = hook.get("command") if isinstance(hook, dict) else None
                if isinstance(command, str):
                    yield str(event), command


def _settings_hooks(git: GitRepo, ref: str) -> Any:
    raw = git.blob(ref, SETTINGS_PATH)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise _Unreadable(f"{SETTINGS_PATH} at {ref} is not JSON") from exc
    if not isinstance(data, dict):
        raise _Unreadable(f"{SETTINGS_PATH} at {ref} is not a JSON object")
    return data.get("hooks")


def _card_hooks(git: GitRepo, ref: str) -> Iterator[tuple[str, Any]]:
    """(card path, its frontmatter ``hooks``) for each agent card at the ref."""
    listing = git.entries(ref, AGENTS_DIR)
    if listing is None:
        raise _Unreadable(f"could not list {AGENTS_DIR}/ at {ref}")
    for name in sorted(listing):
        if not name.endswith(".md"):
            continue
        source = f"{AGENTS_DIR}/{name}"
        text = (git.blob(ref, source) or b"").decode("utf-8", errors="replace")
        match = _FRONTMATTER.match(text)
        if match is None:
            continue
        try:
            meta = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            raise _Unreadable(f"{source} at {ref}: frontmatter is not YAML") from exc
        if meta is not None and not isinstance(meta, dict):
            raise _Unreadable(f"{source} at {ref}: frontmatter is not a YAML mapping")
        yield source, (meta or {}).get("hooks")


def _registrations(
    source: str, hooks: Any
) -> tuple[list[Registration], list[str]]:
    """The registrations a source's ``hooks`` makes, and its commands outside the shape."""
    found: list[Registration] = []
    unshaped: list[str] = []
    for event, command in _commands(hooks):
        names = [next(g for g in m.groups() if g) for m in _REGISTRATION.finditer(command)]
        found.extend(Registration(name, source, event) for name in names)
        if command.count(f"{HOOKS_DIR}/") > len(names):
            unshaped.append(f"{source} ({event}) names {HOOKS_DIR}/ outside the shape: {command}")
    return found, unshaped


def _read(git: GitRepo, row: RepoFamilyStatus, ref: str) -> RepoHooks:
    sources = [(SETTINGS_PATH, _settings_hooks(git, ref)), *_card_hooks(git, ref)]
    registrations: list[Registration] = []
    unshaped: list[str] = []
    for source, hooks in sources:
        found, odd = _registrations(source, hooks)
        registrations.extend(found)
        unshaped.extend(odd)
    return RepoHooks(
        context_id=row.context_id,
        branch=row.branch,
        present=_present_scripts(git, ref),
        registrations=tuple(registrations),
        unshaped=tuple(unshaped),
    )


def _audit(row: RepoFamilyStatus, git: GitRepo, fetch_requested: bool) -> RepoHooks:
    ref = f"origin/{row.branch}"
    if not row.available:
        return RepoHooks(row.context_id, row.branch, unreadable=f"{ref} absent")
    if fetch_requested and not row.fetched:
        return RepoHooks(row.context_id, row.branch, unreadable=f"fetch of {ref} failed")
    try:
        return _read(git, row, ref)
    except _Unreadable as exc:
        return RepoHooks(row.context_id, row.branch, unreadable=str(exc))


def gather_hook_registration(
    registry: dict[str, Any],
    family_rows: list[RepoFamilyStatus],
    fetch_requested: bool,
    repo_factory: Callable[[Path], GitRepo] = GitRepo,
) -> list[RepoHooks]:
    """Audit each context the family audit read, on the ref it fetched. No second fetch."""
    local_paths = {ctx["id"]: ctx.get("local_path") for ctx in registry.get("contexts", [])}
    return [
        _audit(row, repo_factory(Path(local_paths[row.context_id])), fetch_requested)
        for row in family_rows
    ]


def format_hook_table(rows: list[RepoHooks], fetch_requested: bool) -> list[str]:
    """The per-context matrix: registered against present, then one line per script."""
    refs = "each repo's origin ref" if fetch_requested else "local origin refs, NOT fetched"
    lines = [f"## HOOK REGISTRATION ({refs})"]
    for row in rows:
        header = f"{row.context_id} (origin/{row.branch})"
        if row.unreadable is not None:
            lines.append(f"{header}: COULD NOT READ — {row.unreadable}")
            continue
        statuses = row.statuses()
        registered = sum(1 for status in statuses.values() if status == REGISTERED)
        lines.append(
            f"{header}: {registered} of {len(row.present)} present scripts registered"
            f" ({len(row.registrations)} registrations)"
        )
        width = max((len(script) for script in statuses), default=0)
        lines.extend(f"  {script:<{width}}  {status}" for script, status in statuses.items())
    return lines
