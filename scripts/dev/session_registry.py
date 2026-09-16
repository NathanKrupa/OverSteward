#!/usr/bin/env python3
# ABOUTME: SessionStart/SessionEnd registry of live Claude sessions, plus a tmux boot resume.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; byte-copied into each repo's scripts/dev/.

"""Remember which Claude sessions were alive, so a reboot does not cost their context.

After a WSL restart or a laptop sleep every session is gone, and the
orchestrator rebuilds context by re-reading ``SESSION_STATE``, ``git log`` and
issues — a reconstruction the transcript classifier keeps finding at the top of
the spend table. ``claude -r <id>`` restores the transcript for free, but only
if something wrote the ids down while the sessions were running.

That is all this is: two hooks that append a line each, and a boot verb that
reads them back.

Subcommands::

    session_registry.py record            # SessionStart hook; hook JSON on stdin
    session_registry.py retire            # SessionEnd hook; hook JSON on stdin
    session_registry.py list              # live rows as a table
    session_registry.py resume [--dry-run]   # one tmux window per live row

Hook wiring goes in the **global** ``~/.claude/settings.json``, not a repo's —
sessions span repos, and a per-repo registration would miss every session
started anywhere else. Point it at the OverSteward checkout's deployed copy
rather than taking a third copy into ``~/.claude/hooks/``; a copy nothing
compares is a copy that drifts::

    "SessionStart": [{"hooks": [{"type": "command",
        "command": "python3 /home/natha/OverSteward/scripts/dev/session_registry.py record"}]}],
    "SessionEnd":   [{"hooks": [{"type": "command",
        "command": "python3 /home/natha/OverSteward/scripts/dev/session_registry.py retire"}]}]

**The store is append-only.** Every ``record``/``retire`` appends one JSON line
and readers fold by ``session_id``, last line wins. A read-modify-write file
would lose a row whenever two sessions started at once — which is exactly when
this is worth having — and a partially rewritten registry is worse than a stale
one. Appends of a single short line are atomic under ``O_APPEND``.

**Naming.** Nathan will not name sessions by hand reliably, so the name is
resolved in three tiers and the tier is recorded beside it: an explicit
``-n``/``--name`` (the hook payload's ``session_title``), else the latest
``ai-title`` record in the session's own transcript, else the ``cwd``
basename. A later ``record``/``retire`` for the same session may *improve* the
name (a fresh session has no ``ai-title`` yet — it is written after the first
exchange) but never demotes it.

**Liveness is the absence of a clean end.** A row with no ``ended_at`` is live:
a crashed or killed session never ran its ``SessionEnd`` hook, so it still
looks live, which is precisely the state ``resume`` exists for. Age is measured
from ``last_seen`` and ``--max-age-hours`` drops rows too old to be "what was
running when the machine went down".

**Unverified:** whether Claude Code runs the ``SessionEnd`` hook when the
process is terminated by a signal (``pkill``) is *not* established here — it
could not be driven from the sandbox this was written in. If a signal does
fire ``SessionEnd``, those rows carry ``ended_at`` and ``resume`` skips them;
``--include-ended`` is the escape hatch for that case. Treat this paragraph as
a claim awaiting the acceptance run, not as a verified invariant.

Exit codes, which must not be collapsed:

* ``0`` — a measured answer. ``list``/``resume`` print the counts they saw,
  including zero, so "nothing live" never looks like "never looked".
* ``1`` — something failed: the registry could not be written, or tmux refused
  a window.
* ``2`` — could not look: no registry file at all, or ``resume`` with no tmux
  on ``PATH``. A skip must never read as a pass.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_COULD_NOT_LOOK = 2

DEFAULT_REGISTRY = Path.home() / ".claude" / "session-registry.jsonl"
DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_TMUX_SESSION = "claude"
DEFAULT_MAX_AGE_HOURS = 24.0

# Name tiers, best first. The tier is stored beside the name so a later hook
# can improve a fallback name without ever overwriting an explicit one.
EXPLICIT = "explicit"
AI_TITLE = "ai-title"
CWD_BASENAME = "cwd"
NAME_TIERS = (EXPLICIT, AI_TITLE, CWD_BASENAME)

UNNAMED = "session"
WINDOW_NAME_LIMIT = 40

# Transcripts run to tens of megabytes; the ai-title records are rewritten on
# every turn, so the last one is always near the end. Read the tail only.
TRANSCRIPT_TAIL_BYTES = 256 * 1024

TranscriptReader = Callable[[str], str]


@dataclass(frozen=True)
class Registry:
    """The folded store: one row per session id, plus what could not be parsed."""

    rows: dict[str, dict]
    unreadable: int


@dataclass(frozen=True)
class Window:
    """One tmux window to open for one recorded session."""

    name: str
    cwd: str
    command: str


def read_transcript_tail(path: str, root: Path) -> str:
    """The last ``TRANSCRIPT_TAIL_BYTES`` of a transcript under ``root``, else ``""``.

    The path arrives in the hook payload, so it is confined to the transcript
    root before it is opened rather than trusted — and a refusal says so on
    stderr, because a silently empty read is indistinguishable from a session
    that simply has no title yet.

    A truncated first line is fine: ``latest_ai_title`` skips lines it cannot
    parse, so a partial record is simply not a record.
    """
    if not path:
        return ""
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(root.resolve()):
        print(
            f"[session-registry] refusing a transcript outside {root}: {candidate}",
            file=sys.stderr,
        )
        return ""
    try:
        with candidate.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - TRANSCRIPT_TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def transcript_reader(root: Path) -> TranscriptReader:
    """The transcript-reading seam the hooks pass to ``resolve_name``."""
    return lambda path: read_transcript_tail(path, root)


def latest_ai_title(transcript: str) -> str | None:
    """The last ``ai-title`` Claude Code wrote for this session, if any."""
    title: str | None = None
    for line in transcript.splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(record, dict) and record.get("type") == "ai-title":
            candidate = str(record.get("aiTitle") or "").strip()
            if candidate:
                title = candidate
    return title


def resolve_name(payload: dict, read_transcript: TranscriptReader) -> tuple[str, str]:
    """``(name, tier)`` for one hook payload — explicit, then ai-title, then cwd."""
    explicit = str(payload.get("session_title") or "").strip()
    if explicit:
        return explicit, EXPLICIT
    generated = latest_ai_title(read_transcript(str(payload.get("transcript_path") or "")))
    if generated:
        return generated, AI_TITLE
    return Path(str(payload.get("cwd") or "")).name or UNNAMED, CWD_BASENAME


def _tier_rank(tier: str) -> int:
    return NAME_TIERS.index(tier) if tier in NAME_TIERS else len(NAME_TIERS)


def _best_name(fresh: tuple[str, str], existing: dict | None) -> tuple[str, str]:
    """Keep the better-sourced of a freshly resolved name and the recorded one."""
    if not existing:
        return fresh
    recorded = str(existing.get("name") or "")
    recorded_tier = str(existing.get("name_source") or "")
    if recorded and _tier_rank(recorded_tier) < _tier_rank(fresh[1]):
        return recorded, recorded_tier
    return fresh


def _upsert(
    payload: dict,
    existing: dict | None,
    now: datetime,
    read_transcript: TranscriptReader,
    ended: bool,
) -> dict:
    stamp = now.isoformat()
    name, tier = _best_name(resolve_name(payload, read_transcript), existing)
    previous = existing or {}
    return {
        "session_id": str(payload.get("session_id") or ""),
        "name": name,
        "name_source": tier,
        "cwd": str(payload.get("cwd") or previous.get("cwd") or ""),
        "transcript_path": str(
            payload.get("transcript_path") or previous.get("transcript_path") or ""
        ),
        "started_at": str(previous.get("started_at") or stamp),
        "last_seen": stamp,
        "ended_at": stamp if ended else None,
        "end_reason": str(payload.get("reason") or "") if ended else "",
    }


def record_row(
    payload: dict, existing: dict | None, now: datetime, read_transcript: TranscriptReader
) -> dict:
    """The row a ``SessionStart`` writes: live again, ``started_at`` preserved."""
    return _upsert(payload, existing, now, read_transcript, ended=False)


def retire_row(
    payload: dict, existing: dict | None, now: datetime, read_transcript: TranscriptReader
) -> dict:
    """The row a ``SessionEnd`` writes: the same row, plus when and why it ended."""
    return _upsert(payload, existing, now, read_transcript, ended=True)


def fold_rows(lines: Iterable[str]) -> Registry:
    """Fold the append-only log into one row per session id; last line wins."""
    rows: dict[str, dict] = {}
    unreadable = 0
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            unreadable += 1
            continue
        session_id = row.get("session_id") if isinstance(row, dict) else None
        if session_id:
            rows[str(session_id)] = row
        else:
            unreadable += 1
    return Registry(rows=rows, unreadable=unreadable)


def load_registry(path: Path) -> Registry | None:
    """The folded store, or ``None`` when there is no store to read (exit 2)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return fold_rows(text.splitlines())


def append_row(path: Path, row: dict) -> None:
    """Append one row. Single short line under ``O_APPEND`` — atomic between writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def parse_stamp(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def live_rows(
    registry: Registry,
    now: datetime,
    max_age_hours: float | None = None,
    include_ended: bool = False,
) -> list[dict]:
    """Rows still considered live, oldest first.

    Live means no clean ``SessionEnd`` was recorded — a crash leaves exactly
    that. ``max_age_hours`` drops rows last seen too long ago to be part of
    "what was running"; a row whose ``last_seen`` cannot be parsed is kept
    rather than silently dropped.
    """
    selected = []
    for row in registry.rows.values():
        if row.get("ended_at") and not include_ended:
            continue
        seen = parse_stamp(row.get("last_seen"))
        if max_age_hours is not None and seen is not None:
            if (now - seen).total_seconds() > max_age_hours * 3600:
                continue
        selected.append(row)
    return sorted(selected, key=lambda row: str(row.get("last_seen") or ""))


def format_age(row: dict, now: datetime) -> str:
    seen = parse_stamp(row.get("last_seen"))
    if seen is None:
        return "?"
    seconds = max(0, int((now - seen).total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600:02d}h"


def format_table(rows: Sequence[dict], now: datetime) -> list[str]:
    """One line per row: id, name, cwd, age."""
    lines = [f"{'SESSION':36}  {'NAME':28}  {'AGE':>7}  CWD"]
    for row in rows:
        lines.append(
            f"{str(row.get('session_id') or ''):36}  {str(row.get('name') or ''):28}  "
            f"{format_age(row, now):>7}  {row.get('cwd') or ''}"
        )
    return lines


def window_name(name: str) -> str:
    """A tmux-safe window name: ``.`` and ``:`` break tmux target specs."""
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in name)
    safe = "-".join(part for part in safe.split("-") if part)
    return (safe[:WINDOW_NAME_LIMIT] or UNNAMED).strip("-") or UNNAMED


def plan_windows(rows: Sequence[dict], claude_bin: str = "claude") -> list[Window]:
    """One window per row, opened in the recorded cwd, resuming the recorded id."""
    return [
        Window(
            name=window_name(str(row.get("name") or "")),
            cwd=str(row.get("cwd") or ""),
            command=f"{shlex.quote(claude_bin)} -r {shlex.quote(str(row.get('session_id') or ''))}",
        )
        for row in rows
    ]


def tmux_commands(
    windows: Sequence[Window],
    tmux_bin: str,
    tmux_session: str,
    session_exists: bool,
) -> list[list[str]]:
    """The exact argv list ``resume`` runs — the same list ``--dry-run`` prints."""
    commands: list[list[str]] = []
    for window in windows:
        if commands or session_exists:
            commands.append(
                [tmux_bin, "new-window", "-t", tmux_session, "-n", window.name,
                 "-c", window.cwd, window.command]
            )
        else:
            commands.append(
                [tmux_bin, "new-session", "-d", "-s", tmux_session, "-n", window.name,
                 "-c", window.cwd, window.command]
            )
    return commands


def _registry_or_complaint(path: Path) -> Registry | None:
    registry = load_registry(path)
    if registry is None:
        print(
            f"[session-registry] COULD NOT LOOK: no registry at {path}.\n"
            "  Nothing has been recorded — wire the SessionStart/SessionEnd hooks first.",
            file=sys.stderr,
        )
    return registry


def _report_unreadable(registry: Registry) -> None:
    if registry.unreadable:
        print(
            f"[session-registry] {registry.unreadable} unreadable line(s) skipped.",
            file=sys.stderr,
        )


def _hook(args: argparse.Namespace, now: datetime, ended: bool) -> int:
    """Shared body of ``record`` and ``retire``: read stdin, fold, append one row."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError) as error:
        print(f"[session-registry] unreadable hook payload: {error}", file=sys.stderr)
        return EXIT_FAILED
    if not isinstance(payload, dict) or not payload.get("session_id"):
        print("[session-registry] hook payload carries no session_id", file=sys.stderr)
        return EXIT_FAILED

    path = Path(args.registry)
    existing = (load_registry(path) or Registry({}, 0)).rows.get(str(payload["session_id"]))
    builder = retire_row if ended else record_row
    try:
        append_row(
            path,
            builder(payload, existing, now, transcript_reader(Path(args.transcript_root))),
        )
    except OSError as error:
        print(f"[session-registry] could not write {path}: {error}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


def cmd_list(args: argparse.Namespace, now: datetime) -> int:
    registry = _registry_or_complaint(Path(args.registry))
    if registry is None:
        return EXIT_COULD_NOT_LOOK
    _report_unreadable(registry)
    rows = live_rows(registry, now, args.max_age_hours, args.include_ended)
    for line in format_table(rows, now):
        print(line)
    print(f"[session-registry] {len(rows)} live of {len(registry.rows)} recorded session(s).")
    return EXIT_OK


def cmd_resume(args: argparse.Namespace, now: datetime) -> int:
    tmux_bin = shutil.which(args.tmux_bin)
    if tmux_bin is None:
        print(
            f"[session-registry] COULD NOT LOOK: {args.tmux_bin!r} is not on PATH, so no "
            "session was resumed.\n  Install tmux, or resume by hand: claude -r <id>.",
            file=sys.stderr,
        )
        return EXIT_COULD_NOT_LOOK

    registry = _registry_or_complaint(Path(args.registry))
    if registry is None:
        return EXIT_COULD_NOT_LOOK
    _report_unreadable(registry)

    rows = live_rows(registry, now, args.max_age_hours, args.include_ended)
    windows = plan_windows(rows, args.claude_bin)
    # Asked even for a dry run: `has-session` reads, it does not act, and a plan
    # that says `new-session` against a server that already has one is a lie.
    exists = _tmux_session_exists(tmux_bin, args.tmux_session)
    commands = tmux_commands(windows, tmux_bin, args.tmux_session, exists)

    if args.dry_run:
        for command in commands:
            print(shlex.join(command))
        print(f"[session-registry] would open {len(commands)} window(s) in '{args.tmux_session}'.")
        return EXIT_OK

    return _run_tmux(commands, args.tmux_session)


def _tmux_session_exists(tmux_bin: str, tmux_session: str) -> bool:
    return (
        subprocess.run(
            [tmux_bin, "has-session", "-t", tmux_session],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _run_tmux(commands: Sequence[Sequence[str]], tmux_session: str) -> int:
    for command in commands:
        result = subprocess.run(list(command), capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(
                f"[session-registry] tmux refused: {shlex.join(command)}\n  {result.stderr.strip()}",
                file=sys.stderr,
            )
            return EXIT_FAILED
    print(f"[session-registry] opened {len(commands)} window(s) in '{tmux_session}'.")
    return EXIT_OK


def _add_read_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help="Drop rows last seen longer ago than this (default: %(default)s; 0 = no limit).",
    )
    parser.add_argument(
        "--include-ended",
        action="store_true",
        help="Include rows that recorded a clean SessionEnd.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="Append-only JSONL store (default: %(default)s).",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    hook = argparse.ArgumentParser(add_help=False)
    hook.add_argument(
        "--transcript-root",
        default=str(DEFAULT_TRANSCRIPT_ROOT),
        help="Only read transcripts under this directory (default: %(default)s).",
    )
    subcommands.add_parser(
        "record", parents=[common, hook], help="SessionStart hook; JSON on stdin."
    )
    subcommands.add_parser(
        "retire", parents=[common, hook], help="SessionEnd hook; JSON on stdin."
    )

    listing = subcommands.add_parser("list", parents=[common], help="Print live sessions.")
    _add_read_arguments(listing)

    resume = subcommands.add_parser("resume", parents=[common], help="Reopen live sessions in tmux.")
    _add_read_arguments(resume)
    resume.add_argument("--dry-run", action="store_true", help="Print the plan; open nothing.")
    resume.add_argument("--tmux-session", default=DEFAULT_TMUX_SESSION)
    resume.add_argument("--tmux-bin", default="tmux")
    resume.add_argument("--claude-bin", default="claude")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(UTC)
    if getattr(args, "max_age_hours", None) == 0:
        args.max_age_hours = None
    if args.command == "record":
        return _hook(args, now, ended=False)
    if args.command == "retire":
        return _hook(args, now, ended=True)
    if args.command == "list":
        return cmd_list(args, now)
    return cmd_resume(args, now)


if __name__ == "__main__":
    raise SystemExit(main())
