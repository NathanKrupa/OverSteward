# ABOUTME: MIDDLE decisions — whether a target's verify runs in a worktree venv built from its own uv.lock.
# ABOUTME: Derives the extras from the branch's CI `uv sync` and the local-path installs the lock does not carry.

"""Which environment a target's `make verify` runs in under `sow --verify`.

The target's shared `.venv` follows its primary checkout, which sits on the
branch production runs. A sync PR targets the registry branch, which can be a
different one, so verifying in the shared venv measures the wrong dependency
set: a base that moved a linter one patch ahead is gated by the older one.

A target whose CI installs with `uv sync`, and whose branch carries a
`uv.lock`, is therefore verified in a venv built inside sow's throwaway
worktree from that branch's own lock (dispatch playbook step 6a, with
`--locked`). Everything is read from the worktree, so the extras and the lock
are the base branch's, never the primary checkout's. Every other target keeps
the borrowed link to its shared venv.

The shared venv is read for one thing only: the local-directory installs it
carries that the lock does not name — packages a CI job layers on top of its
sync from a source sow cannot reach. They are installed into
the worktree venv from the same directory the shared venv took them from, with
their dependencies, as CI's own layering installs them.
"""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from .runners import SowError

CI_WORKFLOW = Path(".github") / "workflows" / "ci.yml"
LOCKFILE = "uv.lock"

#: `uv sync` flags that do not change which packages the sync installs. `--python`
#: names CI's own interpreter, which is not this machine's, so it is never carried.
_NEUTRAL_FLAGS = frozenset(
    {"--locked", "--frozen", "--quiet", "-q", "--verbose", "-v", "--no-progress"}
)
_NEUTRAL_VALUED_FLAGS = frozenset({"--python", "-p"})
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "&"})


@dataclass(frozen=True)
class LockedVenvPlan:
    """How the worktree venv is built: the sync's extras and the installs layered on it."""

    sync_args: tuple[str, ...]
    carried: tuple[tuple[str, ...], ...]

    def describe(self) -> str:
        extras = " ".join(self.sync_args) or "no extras"
        layered = f", plus {len(self.carried)} local install(s)" if self.carried else ""
        return f"verified in a worktree venv built from uv.lock ({extras}{layered})"


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _sync_flags(tokens: list[str], start: int) -> list[str]:
    """The flags of one `uv sync` invocation, up to the next shell separator."""
    flags: list[str] = []
    for token in tokens[start:]:
        if token in _SHELL_SEPARATORS:
            break
        flags.append(token)
    return flags


def _install_args(flags: list[str]) -> tuple[list[str], bool]:
    """(extras, all-extras) for one invocation, refusing a flag that changes the set otherwise."""
    extras: list[str] = []
    every_extra = False
    pending = iter(flags)
    for flag in pending:
        name, _, inline = flag.partition("=")
        if name == "--extra":
            extra = inline or next(pending, "")
            if not extra:
                raise SowError("ci.yml runs `uv sync --extra` with no extra named")
            extras.append(extra)
        elif name == "--all-extras":
            every_extra = True
        elif name in _NEUTRAL_VALUED_FLAGS:
            if not inline:
                next(pending, None)
        elif name not in _NEUTRAL_FLAGS:
            raise SowError(f"ci.yml runs `uv sync {flag}`, which sow cannot reproduce")
    return extras, every_extra


def _run_scripts(document: object) -> list[str]:
    """Every step's `run:` script. A workflow of another shape is refused, never skipped."""
    if document is None:
        return []
    if not isinstance(document, dict):
        raise SowError("ci.yml is not a mapping")
    jobs = document.get("jobs") or {}
    if not isinstance(jobs, dict):
        raise SowError("ci.yml `jobs` is not a mapping")
    scripts: list[str] = []
    for name, job in jobs.items():
        steps = (job.get("steps") or []) if isinstance(job, dict) else None
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            raise SowError(f"ci.yml job `{name}` does not hold a list of steps")
        scripts.extend(step["run"] for step in steps if isinstance(step.get("run"), str))
    return scripts


def _commands(script: str) -> list[list[str]]:
    """The script's commands as tokens: one per logical line, a quote may span lines."""
    commands: list[list[str]] = []
    pending = ""
    for line in script.replace("\\\n", " ").splitlines():
        pending = f"{pending}\n{line}" if pending else line
        try:
            commands.append(shlex.split(pending, comments=True))
        except ValueError:
            continue
        pending = ""
    if pending:
        raise SowError(f"ci.yml has a run line sow cannot read: {pending.strip()}")
    return commands


def ci_sync_args(ci_text: str) -> tuple[str, ...] | None:
    """The extras a CI workflow's `uv sync` steps install, or None when none syncs.

    Only `run:` scripts are read, never prose, and shell comments are dropped.
    Several syncs union their extras, so one environment covers every job;
    `--all-extras` anywhere means all of them.
    """
    try:
        document = yaml.safe_load(ci_text)
    except yaml.YAMLError as exc:
        raise SowError(f"ci.yml could not be parsed: {exc}") from exc
    found = False
    extras: list[str] = []
    every_extra = False
    for script in _run_scripts(document):
        for tokens in _commands(script):
            for index in range(len(tokens) - 1):
                if tokens[index : index + 2] != ["uv", "sync"]:
                    continue
                found = True
                named, every = _install_args(_sync_flags(tokens, index + 2))
                every_extra = every_extra or every
                extras.extend(extra for extra in named if extra not in extras)
    if not found:
        return None
    if every_extra:
        return ("--all-extras",)
    return tuple(arg for extra in extras for arg in ("--extra", extra))


def lock_package_names(lock_text: str) -> frozenset[str]:
    """Every package a uv.lock resolves, the project itself included, normalized."""
    try:
        lock = tomllib.loads(lock_text)
    except tomllib.TOMLDecodeError as exc:
        raise SowError(f"uv.lock could not be parsed: {exc}") from exc
    return frozenset(_normalize(str(package.get("name", ""))) for package in lock.get("package", ()))


def _dist_name(dist_info: Path) -> str:
    metadata = dist_info / "METADATA"
    if metadata.is_file():
        found = re.search(r"^Name:\s*(\S+)", metadata.read_text(errors="replace"), re.MULTILINE)
        if found:
            return found.group(1)
    return dist_info.name.split("-")[0]


def carried_installs(shared_venv: Path, locked: frozenset[str]) -> tuple[tuple[str, ...], ...]:
    """`uv pip install` arguments for each local-directory install the lock does not name."""
    carried = []
    for direct_url in sorted(shared_venv.glob("lib/python*/site-packages/*.dist-info/direct_url.json")):
        try:
            record = json.loads(direct_url.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        url = urlparse(str(record.get("url", "")))
        if url.scheme != "file" or _normalize(_dist_name(direct_url.parent)) in locked:
            continue
        path = unquote(url.path)
        editable = bool((record.get("dir_info") or {}).get("editable"))
        carried.append(("-e", path) if editable else (path,))
    return tuple(carried)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SowError(f"{path.name} could not be read: {exc}") from exc


def locked_venv_plan(worktree: Path, shared_venv: Path) -> LockedVenvPlan | None:
    """The worktree venv to build for verify, or None when the target keeps its shared venv."""
    lockfile = worktree / LOCKFILE
    workflow = worktree / CI_WORKFLOW
    if not lockfile.is_file() or not workflow.is_file():
        return None
    sync_args = ci_sync_args(_read(workflow))
    if sync_args is None:
        return None
    locked = lock_package_names(_read(lockfile))
    return LockedVenvPlan(sync_args, carried_installs(shared_venv, locked))
