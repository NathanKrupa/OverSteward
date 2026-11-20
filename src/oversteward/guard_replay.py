# ABOUTME: Replays the destructive-command gate over the Bash commands recorded in session transcripts.
# ABOUTME: Measurement only: what the hook would ask or deny, by repo and attendance, against what it recorded.
"""What ``check_destructive_command.py`` would have said about the commands sessions ran.

The gate asks for confirmation on some commands, and an unanswered ask stalls an
unattended lane (OS#192, OS#674). Before the gate is registered anywhere new, this
replays it over the Bash commands Claude Code recorded and counts what it would
have asked or denied, by repo and by attended or unattended session, and how
often a recorded decision of the hook agrees with the replay.

* **Corpus.** Under the projects root, every ``<project>/<session>.jsonl`` and
  every ``<project>/<session>/subagents/**/agent-*.jsonl`` modified within the
  window. Each is read line by line through :func:`dispatch_run.iter_entries`;
  one it rejects is counted and named, contributes nothing, and the rest are
  still measured. A tool call that appears in more than one transcript is
  counted once, by its ``tool_use`` id.
* **Decision.** The hook file is loaded and its own ``main()`` is called on a
  PreToolUse event, with ``sys.stdin`` and ``sys.stdout`` swapped for the call
  and ``SystemExit`` caught. Its private matchers are never called, so the
  priority between its tiers is the hook's own. An exception, a non-zero exit
  or output that is not a decision is an ``error``, never a pass.
* **Recorded.** A PreToolUse ``attachment`` whose ``command`` names the hook file
  and whose ``stdout`` carries a ``permissionDecision`` is the hook's real
  decision for its ``toolUseID``. Another hook's decision on the same call is
  not this hook's, and is counted apart.
* **Public by construction.** The summary prints counts, registry context ids,
  the hook's own ``Pattern:`` names, the classes the labels file names and
  12-hex command keys, never a command, a path or a project directory's name.
  The command text goes only to ``--rows``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from oversteward import dispatch_run

ASK = "ask"
DENY = "deny"
PASS = "pass"
ERROR = "error"
#: The outcomes the hook can return. ``error`` is the replay's own.
OUTCOMES = (ASK, DENY, PASS, ERROR)
#: The outcomes that hold a command: the rows a reader labels.
FLAGGED = (ASK, DENY)

WARRANTED = "warranted"
FALSE = "false"
VERDICTS = (WARRANTED, FALSE)

#: A command attributed to no managed context.
OTHER = "other"
ATTENDED = "attended"
UNATTENDED = "unattended"
#: An entry with no boolean ``isSidechain``: neither side is assumed.
UNKNOWN = "unknown"
ATTENDANCE = (ATTENDED, UNATTENDED, UNKNOWN)

KEY_LENGTH = 12
_PATTERN_PREFIX = "Pattern: "


class ReplayUnreadable(RuntimeError):
    """The replay could not look: a missing root, hook, registry or labels file."""


@dataclass(frozen=True)
class Decision:
    """What the hook said about one command."""

    outcome: str
    pattern: str = ""
    detail: str = ""


@dataclass(frozen=True)
class Command:
    """One recorded Bash tool call."""

    text: str
    tool_use_id: str
    cwd: str
    attendance: str

    @property
    def key(self) -> str:
        return command_key(self.text)


@dataclass(frozen=True)
class Context:
    """A ``registry.yaml`` context with a ``local_path``."""

    id: str
    root: PurePosixPath

    @property
    def named(self) -> re.Pattern[str]:
        return re.compile(rf"(?<![\w./-]){re.escape(str(self.root))}(?![\w.-])")

    @property
    def project_dir(self) -> str:
        """The project directory Claude Code names for a session launched at ``root``."""
        return project_dir_name(str(self.root))


@dataclass(frozen=True)
class Label:
    verdict: str
    cls: str


def command_key(text: str) -> str:
    """The first 12 hex digits of the command's sha256: a public handle on a private row."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:KEY_LENGTH]


def project_dir_name(path: str) -> str:
    """Claude Code's project directory name for a launch directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


# ---------------------------------------------------------------------------
# The hook, called through its own entry point.
# ---------------------------------------------------------------------------

Hook = Callable[[str], Decision]


def load_hook(path: Path) -> Hook:
    """The hook at ``path`` as a function of the command text."""
    if not path.is_file():
        raise ReplayUnreadable(f"hook {path} is not a file")
    spec = importlib.util.spec_from_file_location(f"_guard_replay_{command_key(str(path))}", path)
    if spec is None or spec.loader is None:
        raise ReplayUnreadable(f"hook {path} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # a hook that cannot load could not look: exit 1
        raise ReplayUnreadable(f"hook {path} failed to load: {error!r}") from error
    main = getattr(module, "main", None)
    if not callable(main):
        raise ReplayUnreadable(f"hook {path} has no main()")
    return lambda text: run_hook(main, text)


def run_hook(main: Callable[[], object], command: str) -> Decision:
    """Call a PreToolUse(Bash) hook's ``main()`` on ``command`` and read its decision."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    stdin, stdout = sys.stdin, sys.stdout
    captured = io.StringIO()
    sys.stdin, sys.stdout = io.StringIO(json.dumps(event)), captured
    try:
        try:
            code = main()
        except SystemExit as exit_:
            code = exit_.code
    except Exception as error:  # the hook's crash is a measured outcome, never a pass
        return Decision(ERROR, detail=f"{type(error).__name__}: {error}")
    finally:
        sys.stdin, sys.stdout = stdin, stdout
    return read_output(captured.getvalue(), code)


def read_output(text: str, code: object) -> Decision:
    """The decision a hook's stdout and exit code carry."""
    if code not in (0, None):
        return Decision(ERROR, detail=f"exit {code!r}")
    if not text.strip():
        return Decision(PASS)
    decision = _hook_decision(text)
    if decision is None:
        return Decision(ERROR, detail="output is not a PreToolUse decision")
    outcome, reason = decision
    if outcome == "allow":
        return Decision(PASS)
    if outcome not in FLAGGED:
        return Decision(ERROR, detail=f"unknown permissionDecision {outcome!r}")
    return Decision(outcome, pattern=pattern_of(reason))


def _hook_decision(text: str) -> tuple[str, str] | None:
    """(permissionDecision, reason) from a hook's JSON output; None when it holds none."""
    try:
        output = json.loads(text)
    except json.JSONDecodeError:
        return None
    specific = output.get("hookSpecificOutput") if isinstance(output, Mapping) else None
    if not isinstance(specific, Mapping):
        return None
    decision = specific.get("permissionDecision")
    if not isinstance(decision, str):
        return None
    return decision, str(specific.get("permissionDecisionReason", ""))


def pattern_of(reason: str) -> str:
    """The reason's ``Pattern:`` line, without its prefix; empty when it has none."""
    for line in reason.splitlines():
        if line.startswith(_PATTERN_PREFIX):
            return line[len(_PATTERN_PREFIX) :].strip()
    return ""


# ---------------------------------------------------------------------------
# The corpus.
# ---------------------------------------------------------------------------

_GLOBS = ("*/*.jsonl", "*/*/subagents/**/agent-*.jsonl")
_HOOK_ERROR = "PreToolUse:Bash hook error: "
_BRACKETED = re.compile(r"\[([^\]\n]*)\]: ")
#: Claude Code's stand-in for a hook command it does not print.
_PLACEHOLDER = re.compile(r"command hook \d+")


def find_transcripts(root: Path, since_days: float, now: float) -> list[Path]:
    """Every transcript under ``root`` modified within ``since_days`` of ``now``."""
    if not root.is_dir():
        raise ReplayUnreadable(f"projects root {root} is not a directory")
    cutoff = now - since_days * 86400
    found: set[Path] = set()
    for pattern in _GLOBS:
        for path in root.glob(pattern):
            try:
                written = path.stat().st_mtime
            except FileNotFoundError:
                continue  # removed between the listing and the stat: nothing to read
            if written >= cutoff:
                found.add(path)
    return sorted(found)


@dataclass
class TranscriptRead:
    """What one transcript holds for the replay."""

    commands: list[Command] = field(default_factory=list)
    recorded: dict[str, str] = field(default_factory=dict)
    unnamed: dict[str, str] = field(default_factory=dict)
    other_hooks: dict[str, str] = field(default_factory=dict)


def read_transcript(path: Path, hook_name: str) -> TranscriptRead:
    """The Bash commands and recorded decisions of ``hook_name`` in one transcript.

    A recorded decision whose hook command is empty or Claude Code's ``command
    hook N`` placeholder names no hook; it is kept apart from this hook's own.
    Raises :class:`dispatch_run.TranscriptUnreadable`; nothing is returned for a
    transcript that cannot be read to its end.
    """
    names_hook = re.compile(rf"(?:^|[/\s\"']){re.escape(hook_name)}(?=$|[\s\"'])")
    read = TranscriptRead()
    for entry in dispatch_run.iter_entries(path):
        if not isinstance(entry, Mapping):
            continue
        read.commands.extend(bash_commands(entry))
        for tool_use_id, decision, command in recorded_decisions(entry):
            if not command or _PLACEHOLDER.fullmatch(command):
                read.unnamed[tool_use_id] = decision
            elif names_hook.search(command):
                read.recorded[tool_use_id] = decision
            else:
                read.other_hooks[tool_use_id] = decision
    return read


def bash_commands(entry: Mapping) -> list[Command]:
    """Every Bash ``tool_use`` of an assistant entry, with the entry's cwd and sidechain flag."""
    if entry.get("type") != "assistant":
        return []
    message = entry.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, list):
        return []
    sidechain = entry.get("isSidechain")
    attendance = UNKNOWN if not isinstance(sidechain, bool) else UNATTENDED if sidechain else ATTENDED
    commands = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            continue
        tool_input = block.get("input")
        text = tool_input.get("command") if isinstance(tool_input, Mapping) else None
        if block.get("name") == "Bash" and isinstance(text, str):
            commands.append(
                Command(text, str(block.get("id", "")), str(entry.get("cwd") or ""), attendance)
            )
    return commands


def recorded_decisions(entry: Mapping) -> list[tuple[str, str, str]]:
    """(tool_use id, decision, hook command) for each PreToolUse decision ``entry`` records.

    Claude Code records the two tiers differently (read from transcripts written
    in November 2026, not from a specification). An ``ask`` is an ``attachment``
    whose ``stdout`` carries the hook's ``permissionDecision``. A ``deny`` leaves
    no attachment: it is a ``tool_result`` error whose text begins
    ``PreToolUse:Bash hook error:``. The hooks seen there that block by exit
    code have their command in brackets after it; a JSON deny's text is its
    reason alone, which names no hook, so its hook command is empty.
    """
    attachment = entry.get("attachment")
    if isinstance(attachment, Mapping):
        if attachment.get("hookEvent") != "PreToolUse":
            return []
        decision = _hook_decision(str(attachment.get("stdout") or ""))
        if decision is None:
            return []
        return [(str(attachment.get("toolUseID", "")), decision[0], str(attachment.get("command", "")))]
    if entry.get("type") != "user":
        return []
    message = entry.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, list):
        return []
    found = []
    for block in content:
        text = _hook_error_text(block)
        if text is not None:
            named = _BRACKETED.match(text)
            found.append((str(block.get("tool_use_id", "")), DENY, named.group(1) if named else ""))
    return found


def _hook_error_text(block: object) -> str | None:
    """What follows ``PreToolUse:Bash hook error:`` in an error ``tool_result``; else None."""
    if not isinstance(block, Mapping) or block.get("type") != "tool_result":
        return None
    if block.get("is_error") is not True:
        return None
    content = block.get("content")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) for part in content if isinstance(part, Mapping)
        )
    if not isinstance(content, str) or not content.startswith(_HOOK_ERROR):
        return None
    return content[len(_HOOK_ERROR) :]


# ---------------------------------------------------------------------------
# Attribution and labels.
# ---------------------------------------------------------------------------


def load_contexts(registry: Path) -> list[Context]:
    """Every ``registry.yaml`` context that names a ``local_path``."""
    try:
        data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ReplayUnreadable(f"registry {registry}: {error}") from error
    contexts = data.get("contexts") if isinstance(data, Mapping) else None
    if not isinstance(contexts, list):
        raise ReplayUnreadable(f"registry {registry} lists no contexts")
    return [
        Context(str(ctx["id"]), PurePosixPath(str(ctx["local_path"])))
        for ctx in contexts
        if isinstance(ctx, Mapping) and ctx.get("id") and ctx.get("local_path")
    ]


def attribute(command: Command, contexts: Sequence[Context]) -> tuple[str, ...]:
    """Each context whose root holds the command's cwd or is named in its text; else ``other``."""
    cwd = PurePosixPath(command.cwd) if command.cwd else None
    ids = tuple(
        ctx.id
        for ctx in contexts
        if (cwd is not None and (cwd == ctx.root or ctx.root in cwd.parents))
        or ctx.named.search(command.text)
    )
    return ids or (OTHER,)


def launch_context(project_dir: str, contexts: Sequence[Context]) -> str:
    """The context a project directory's sessions were launched in, by its encoded root.

    The encoding is lossy (every non-alphanumeric is ``-``), so a launch directory
    beside a root whose name extends it with ``-`` reads as that root.
    """
    matches = [
        ctx
        for ctx in contexts
        if project_dir == ctx.project_dir or project_dir.startswith(ctx.project_dir + "-")
    ]
    if not matches:
        return OTHER
    return max(matches, key=lambda ctx: len(ctx.project_dir)).id


def load_labels(path: Path) -> dict[str, Label]:
    """Labels by command key, from JSON Lines of ``key``, ``verdict`` and ``class``."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ReplayUnreadable(f"labels {path}: {error}") from error
    labels: dict[str, Label] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReplayUnreadable(f"labels {path}:{number}: {error}") from error
        label = _label(row)
        if label is None:
            raise ReplayUnreadable(
                f"labels {path}:{number}: needs a key, a verdict in {VERDICTS} and a class"
            )
        labels[str(row["key"])] = label
    return labels


def _label(row: object) -> Label | None:
    if not isinstance(row, Mapping) or not isinstance(row.get("key"), str):
        return None
    verdict, cls = row.get("verdict"), row.get("class")
    if verdict not in VERDICTS or not isinstance(cls, str) or not cls.strip():
        return None
    return Label(str(verdict), cls.strip())


# ---------------------------------------------------------------------------
# The replay.
# ---------------------------------------------------------------------------


@dataclass
class Row:
    """One distinct command the hook held or crashed on. Private: it carries the text."""

    key: str
    text: str
    decision: Decision
    contexts: set[str] = field(default_factory=set)
    attendance: Counter[str] = field(default_factory=Counter)
    cwds: set[str] = field(default_factory=set)
    occurrences: int = 0

    def as_json(self, label: Label | None) -> dict:
        return {
            "key": self.key,
            "outcome": self.decision.outcome,
            "pattern": self.decision.pattern,
            "detail": self.decision.detail,
            "occurrences": self.occurrences,
            "contexts": sorted(self.contexts),
            "attendance": dict(sorted(self.attendance.items())),
            "cwds": sorted(self.cwds),
            "verdict": label.verdict if label else None,
            "class": label.cls if label else None,
            "command": self.text,
        }


@dataclass
class Replay:
    """Every count the replay measured."""

    transcripts: int = 0
    unreadable: list[str] = field(default_factory=list)
    sessions: dict[str, set[tuple[str, str]]] = field(default_factory=dict)
    commands: int = 0
    duplicates: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    by_context: Counter[tuple[str, str]] = field(default_factory=Counter)
    by_attendance: Counter[tuple[str, str]] = field(default_factory=Counter)
    by_pattern: Counter[tuple[str, str]] = field(default_factory=Counter)
    rows: dict[str, Row] = field(default_factory=dict)
    replayed: dict[str, tuple[str, str]] = field(default_factory=dict)
    recorded: dict[str, str] = field(default_factory=dict)
    unnamed: dict[str, str] = field(default_factory=dict)
    other_hooks: dict[str, str] = field(default_factory=dict)

    def agreement(
        self, recorded_by_id: Mapping[str, str] | None = None
    ) -> tuple[int, int, list[tuple[str, str, str]]]:
        """(agreeing, recorded, disagreements) over recorded decisions whose call was replayed.

        ``recorded_by_id`` defaults to this hook's own recorded decisions. Each
        disagreement is (command key, replayed outcome, recorded decision).
        """
        recorded_by_id = self.recorded if recorded_by_id is None else recorded_by_id
        agreed, total, disagreements = 0, 0, []
        for tool_use_id, recorded in sorted(recorded_by_id.items()):
            if tool_use_id not in self.replayed:
                continue
            key, outcome = self.replayed[tool_use_id]
            total += 1
            if outcome == recorded:
                agreed += 1
            else:
                disagreements.append((key, outcome, recorded))
        return agreed, total, sorted(set(disagreements))

    def unrecorded(self) -> Counter[tuple[str, str]]:
        """Replayed asks and denies with no recorded decision of this hook, by what was recorded.

        Keyed by (outcome, ``unnamed`` | ``other hook`` | ``none``).
        """
        found: Counter[tuple[str, str]] = Counter()
        for tool_use_id, (_, outcome) in self.replayed.items():
            if outcome not in FLAGGED or tool_use_id in self.recorded:
                continue
            if tool_use_id in self.unnamed:
                found[(outcome, "unnamed")] += 1
            elif tool_use_id in self.other_hooks:
                found[(outcome, "other hook")] += 1
            else:
                found[(outcome, "none")] += 1
        return found

    def recorded_unmatched(self) -> int:
        """Recorded decisions whose tool call no transcript in the window holds."""
        return sum(1 for tool_use_id in self.recorded if tool_use_id not in self.replayed)


def replay(
    transcripts: Iterable[Path], root: Path, hook: Hook, hook_name: str, contexts: Sequence[Context]
) -> Replay:
    """Read every transcript and replay the hook over each distinct tool call once."""
    result = Replay()
    decided: dict[str, Decision] = {}
    seen: set[str] = set()
    for path in transcripts:
        try:
            read = read_transcript(path, hook_name)
        except dispatch_run.TranscriptUnreadable as error:
            result.unreadable.append(str(error))
            continue
        result.transcripts += 1
        project, session = path.relative_to(root).parts[:2]
        launched = launch_context(project, contexts)
        result.sessions.setdefault(launched, set()).add((project, Path(session).stem))
        result.recorded.update(read.recorded)
        result.unnamed.update(read.unnamed)
        result.other_hooks.update(read.other_hooks)
        for command in read.commands:
            if command.tool_use_id and command.tool_use_id in seen:
                result.duplicates += 1
                continue
            seen.add(command.tool_use_id)
            if command.key not in decided:
                decided[command.key] = hook(command.text)
            _tally(result, command, decided[command.key], contexts)
    return result


def measure(
    root: Path,
    since_days: float,
    now: float,
    hook_path: Path,
    registry: Path,
    labels_path: Path | None,
) -> tuple[Replay, dict[str, Label]]:
    """Every input read and the replay run. Raises :class:`ReplayUnreadable` when it cannot look."""
    hook = load_hook(hook_path)
    contexts = load_contexts(registry)
    labels = load_labels(labels_path) if labels_path is not None else {}
    transcripts = find_transcripts(root, since_days, now)
    return replay(transcripts, root, hook, hook_path.name, contexts), labels


def _tally(result: Replay, command: Command, decision: Decision, contexts: Sequence[Context]) -> None:
    result.commands += 1
    result.outcomes[decision.outcome] += 1
    if command.tool_use_id:
        result.replayed[command.tool_use_id] = (command.key, decision.outcome)
    if decision.outcome == PASS:
        return
    owners = attribute(command, contexts)
    row = result.rows.setdefault(command.key, Row(command.key, command.text, decision))
    row.occurrences += 1
    row.contexts.update(owners)
    row.attendance[command.attendance] += 1
    if command.cwd:
        row.cwds.add(command.cwd)
    if decision.outcome in FLAGGED:
        for owner in owners:
            result.by_context[(decision.outcome, owner)] += 1
        result.by_attendance[(decision.outcome, command.attendance)] += 1
        result.by_pattern[(decision.outcome, decision.pattern or "(none)")] += 1


def exit_code(result: Replay) -> int:
    """0 measured; 1 a transcript was rejected or the hook errored; 2 nothing to look at."""
    if result.unreadable or result.outcomes[ERROR]:
        return 1
    if result.commands == 0:
        return 2
    return 0


def write_rows(result: Replay, labels: Mapping[str, Label], path: Path) -> None:
    """One JSON line per distinct command the hook held or crashed on."""
    with path.open("w", encoding="utf-8") as out:
        for key in sorted(result.rows):
            out.write(json.dumps(result.rows[key].as_json(labels.get(key))) + "\n")


# ---------------------------------------------------------------------------
# The summary: counts, pattern names and command keys only.
# ---------------------------------------------------------------------------


def summary(result: Replay, labels: Mapping[str, Label], hook_name: str, since_days: float) -> str:
    """The public summary of a replay. It never prints a command, a path or a project name."""
    lines = [
        f"guard replay of {hook_name} over {since_days:g} days",
        f"transcripts: {result.transcripts} read, {len(result.unreadable)} unreadable",
        "sessions by launch context: " + _sessions(result),
        f"commands: {result.commands} "
        f"({len(result.replayed)} with a tool_use id, {result.duplicates} duplicate calls skipped)",
        "outcomes: " + ", ".join(f"{o} {result.outcomes[o]}" for o in OUTCOMES),
    ]
    for outcome, noun in ((ASK, "asks"), (DENY, "denies")):
        lines.append(f"{noun} by context: " + _counts(result.by_context, outcome))
        lines.append(f"{noun} by attendance: " + _counts(result.by_attendance, outcome, ATTENDANCE))
        lines.append(f"{noun} by pattern: " + _counts(result.by_pattern, outcome))
    lines.extend(_label_lines(result, labels))
    lines.extend(_agreement_lines(result))
    return "\n".join(lines)


def _sessions(result: Replay) -> str:
    parts = []
    for launched in sorted(result.sessions):
        held = result.sessions[launched]
        dirs = len({project for project, _ in held})
        parts.append(f"{launched} {len(held)} ({dirs} project dirs)")
    return ", ".join(parts) or "none"


def _counts(
    counter: Counter[tuple[str, str]], outcome: str, order: Sequence[str] | None = None
) -> str:
    found = {name: n for (o, name), n in counter.items() if o == outcome}
    names = list(order) if order is not None else sorted(found, key=lambda n: (-found[n], n))
    return ", ".join(f"{name} {found.get(name, 0)}" for name in names) or "none"


def _label_lines(result: Replay, labels: Mapping[str, Label]) -> list[str]:
    flagged = [key for key, row in result.rows.items() if row.decision.outcome in FLAGGED]
    verdicts: Counter[str] = Counter()
    classes: dict[str, Counter[str]] = {verdict: Counter() for verdict in VERDICTS}
    for key in flagged:
        label = labels.get(key)
        if label is None:
            verdicts["unlabelled"] += 1
            continue
        verdicts[label.verdict] += 1
        classes[label.verdict][label.cls] += 1
    lines = [
        f"labels over {len(flagged)} distinct flagged commands: "
        f"{WARRANTED} {verdicts[WARRANTED]}, {FALSE} {verdicts[FALSE]}, "
        f"unlabelled {verdicts['unlabelled']}"
    ]
    for verdict in VERDICTS:
        counted = classes[verdict]
        shown = ", ".join(f"{c} {n}" for c, n in sorted(counted.items(), key=lambda i: (-i[1], i[0])))
        lines.append(f"{verdict} by class: {shown or 'none'}")
    return lines


def _agreement_lines(result: Replay) -> list[str]:
    agreed, total, disagreements = result.agreement()
    unrecorded = result.unrecorded()
    lines = [f"agreement: {agreed} of {total} recorded decisions of this hook"]
    lines += [f"  disagreement {key}: replay {got}, recorded {want}" for key, got, want in disagreements]
    for outcome in FLAGGED:
        held = {where: n for (o, where), n in unrecorded.items() if o == outcome}
        lines.append(
            f"{outcome} with no recorded decision of this hook: {sum(held.values())} "
            f"(none recorded {held.get('none', 0)}, naming no hook {held.get('unnamed', 0)}, "
            f"another hook's {held.get('other hook', 0)})"
        )
    lines.append(f"recorded decisions with no replayed call: {result.recorded_unmatched()}")
    lines.append(f"recorded decisions of other hooks: {len(result.other_hooks)}")
    same, compared, _ = result.agreement(result.unnamed)
    by_decision = Counter(result.unnamed.values())
    lines.append(
        f"recorded decisions naming no hook: {len(result.unnamed)} "
        f"({ASK} {by_decision[ASK]}, {DENY} {by_decision[DENY]}); "
        f"the replay gives the same outcome on {same} of the {compared} it replayed"
    )
    return lines
