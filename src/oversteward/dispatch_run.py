# ABOUTME: Reads a dispatched agent's transcript for what its own report cannot be trusted to say.
# ABOUTME: Finds a tool call held on an unanswered `ask` prompt, and checks a reported duration.
"""What a dispatched run's transcript shows, as opposed to what the run reports.

Two questions, both raised by OS#674 (AG#2736, 2026-11-07):

* **Is the agent held on a confirmation prompt?** ``check_destructive_command.py``
  answers some commands with ``permissionDecision: "ask"``. An unattended
  subagent then waits for a human who is not watching, and nothing reaches the
  orchestrator. The transcript records it: a ``PreToolUse`` hook attachment
  carrying the ``ask`` for a ``tool_use`` id, and no ``tool_result`` for that id
  after it. AG#2736 sat that way from 03:52 to 10:36 UTC.
* **Was ``duration_seconds`` measured?** That agent reported 9000 for a run of
  about 27,060 seconds. A duration is measured when it equals the difference of
  the ``started_at`` and ``ended_at`` stamps the report carries, and, given the
  transcript, when it agrees with the span of the transcript's own timestamps.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

#: The hook decision that waits for a human rather than refusing.
ASK = "ask"

#: Slack between a report's duration and the transcript's span. The agent takes
#: its stamps a little after its first entry and a little before its last.
SPAN_TOLERANCE_S = 300


class TranscriptUnreadable(RuntimeError):
    """A transcript that could not be read or parsed — never "nothing pending"."""


@dataclass(frozen=True)
class PendingPrompt:
    """A tool call the hook sent to a confirmation prompt that nobody answered."""

    transcript: str
    tool_use_id: str
    asked_at: datetime
    reason: str

    def age_min(self, now: datetime) -> float:
        return (now - self.asked_at).total_seconds() / 60.0


def parse_stamp(text: str) -> datetime:
    """An ISO-8601 stamp as an aware UTC datetime. A naive stamp is rejected."""
    stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError(f"stamp {text!r} carries no timezone")
    return stamp.astimezone(UTC)


def read_entries(path: Path) -> list[dict]:
    """Every JSON entry of a transcript, in order.

    A transcript is appended while the agent runs, so a final line that does not
    parse is a write still in progress and is dropped. A bad line anywhere else
    means the file is not a transcript, and raises.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TranscriptUnreadable(f"{path}: {error}") from error
    entries = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as error:
            if number == len(lines):
                break
            raise TranscriptUnreadable(f"{path}:{number}: {error}") from error
    return entries


def _ask_reason(entry: Mapping) -> tuple[str, str] | None:
    """(tool_use_id, reason) when ``entry`` is a PreToolUse hook answering ``ask``."""
    attachment = entry.get("attachment")
    if not isinstance(attachment, Mapping) or attachment.get("hookEvent") != "PreToolUse":
        return None
    try:
        output = json.loads(attachment.get("stdout") or "")
    except json.JSONDecodeError:
        return None
    decision = output.get("hookSpecificOutput", {}) if isinstance(output, Mapping) else {}
    if not isinstance(decision, Mapping) or decision.get("permissionDecision") != ASK:
        return None
    reason = str(decision.get("permissionDecisionReason", "")).splitlines()
    return str(attachment.get("toolUseID", "")), (reason[0] if reason else ASK)


def _answered_ids(entry: Mapping) -> set[str]:
    """The ``tool_use`` ids a user entry carries results for."""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, list):
        return set()
    return {
        str(block.get("tool_use_id"))
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "tool_result"
    }


def pending_prompts(entries: Iterable[Mapping], transcript: str = "") -> list[PendingPrompt]:
    """Every ``ask`` decision whose tool call has no result after it."""
    asked: dict[str, PendingPrompt] = {}
    for entry in entries:
        found = _ask_reason(entry)
        if found is not None:
            tool_use_id, reason = found
            stamp = parse_stamp(str(entry["timestamp"]))
            asked[tool_use_id] = PendingPrompt(transcript, tool_use_id, stamp, reason)
            continue
        for answered in _answered_ids(entry):
            asked.pop(answered, None)
    return list(asked.values())


def blocked_prompts(
    entries: Iterable[Mapping], now: datetime, warn_min: float, transcript: str = ""
) -> list[PendingPrompt]:
    """The pending prompts that have waited at least ``warn_min`` minutes."""
    return [p for p in pending_prompts(entries, transcript) if p.age_min(now) >= warn_min]


def recent_transcripts(root: Path, now: datetime, window_hours: float) -> list[Path]:
    """Subagent transcripts under ``root`` written to within ``window_hours``.

    A held agent writes nothing while it waits, so the window must outlast the
    longest hold worth reporting; it bounds the sweep, not the detection.
    """
    cutoff = now.timestamp() - window_hours * 3600
    found = root.glob("*/*/subagents/agent-*.jsonl")
    return sorted(path for path in found if path.stat().st_mtime >= cutoff)


def transcript_span_s(entries: Iterable[Mapping]) -> float | None:
    """Seconds from the first timestamped entry to the last; None if fewer than two."""
    stamps = [parse_stamp(str(e["timestamp"])) for e in entries if e.get("timestamp")]
    if len(stamps) < 2:
        return None
    return (max(stamps) - min(stamps)).total_seconds()


def _stamp_field(report: Mapping, key: str, problems: list[str]) -> datetime | None:
    value = report.get(key)
    if value is None:
        problems.append(f"{key} is missing — take it with `date -u +%Y-%m-%dT%H:%M:%SZ`")
        return None
    try:
        return parse_stamp(str(value))
    except ValueError:
        problems.append(f"{key} {value!r} is not an ISO-8601 UTC stamp")
        return None


def duration_problems(report: Mapping, span_s: float | None = None) -> list[str]:
    """Why ``report``'s ``duration_seconds`` is not a measurement; empty when it is.

    It must equal ``ended_at - started_at`` to the second. When ``span_s`` (the
    transcript's own span) is given, it must also agree with that within
    :data:`SPAN_TOLERANCE_S`, so a pair of stamps written to fit an estimate
    fails as well.
    """
    problems: list[str] = []
    reported = report.get("duration_seconds")
    if not isinstance(reported, int) or isinstance(reported, bool):
        problems.append(f"duration_seconds {reported!r} is not an integer")
    started = _stamp_field(report, "started_at", problems)
    ended = _stamp_field(report, "ended_at", problems)
    if started and ended and isinstance(reported, int):
        measured = int((ended - started).total_seconds())
        if measured < 0:
            problems.append(f"ended_at {ended:%H:%M:%S} is before started_at {started:%H:%M:%S}")
        elif abs(reported - measured) > 1:
            problems.append(f"duration_seconds {reported} != ended_at - started_at = {measured}")
    if span_s is not None and isinstance(reported, int):
        if abs(reported - span_s) > SPAN_TOLERANCE_S:
            problems.append(
                f"duration_seconds {reported} disagrees with the transcript's span of "
                f"{span_s:.0f}s (tolerance {SPAN_TOLERANCE_S}s)"
            )
    return problems


@dataclass(frozen=True)
class Sweep:
    """One pass over a set of transcripts: how many were read, and what is held."""

    checked: int
    blocked: tuple[PendingPrompt, ...]


def sweep(paths: Sequence[Path], now: datetime, warn_min: float) -> Sweep:
    """Read every transcript in ``paths`` and collect the prompts held past ``warn_min``.

    Raises :class:`TranscriptUnreadable` on the first transcript that cannot be
    read, so a sweep that could not look never reports a clear result.
    """
    blocked: list[PendingPrompt] = []
    for path in paths:
        blocked.extend(blocked_prompts(read_entries(path), now, warn_min, str(path)))
    return Sweep(len(paths), tuple(blocked))


def watch(
    find: Callable[[datetime], Sequence[Path]],
    warn_min: float,
    for_min: float,
    poll_sec: float,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = time.sleep,
) -> Sweep:
    """Sweep every ``poll_sec`` until a prompt is held or ``for_min`` has passed.

    Returns the first sweep that found a held prompt, else the last sweep. It
    ends once either way, so a background run notifies its caller exactly once.
    """
    start = clock()
    while True:
        now = clock()
        result = sweep(find(now), now, warn_min)
        if result.blocked or (now - start).total_seconds() >= for_min * 60:
            return result
        sleeper(poll_sec)


_YAML_FENCE = re.compile(r"```ya?ml\n(.*?)```", re.S)


def report_from_text(text: str) -> Mapping:
    """The structured report in ``text``: its first ```yaml fence, else the whole text.

    Raises ``ValueError`` when no mapping can be read from it.
    """
    fence = _YAML_FENCE.search(text)
    try:
        report = yaml.safe_load(fence.group(1) if fence else text)
    except yaml.YAMLError as error:
        raise ValueError(f"report is not YAML: {error}") from error
    if not isinstance(report, Mapping):
        raise ValueError("report holds no YAML mapping")
    return report
