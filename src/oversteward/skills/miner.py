# ABOUTME: Mines repeated Bash command sequences across session transcripts and drafts a SKILL.md per cluster.
# ABOUTME: Deterministic and zero-LLM — support is counted in distinct sessions, drafts land in a review dir.

"""Skill miner.

Claude Code has no tool that turns repeated work into a skill; the documented
path is to notice the repetition by hand. This module does the noticing. It
walks session transcripts, keeps every Bash tool call, reduces each call to a
*signature* (the program plus its subcommand, nothing else), and counts how many
distinct sessions contain each contiguous sequence of signatures. A sequence
that recurs across enough sessions is a procedure the estate keeps re-deriving,
and the miner drafts it as a ``SKILL.md`` for Nathan to approve, edit or bin.

Two borrowed rules shape the output:

- **Drafts stage, they never install.** Hermes-agent gates agent-written skills
  behind a pending directory and an explicit approval. The miner writes under a
  review directory and stops there.
- **Tool names alone are not a procedure.** gbrain's Memorable integration
  rejects captures that carry only tool names as unreplayable. Every step in a
  draft therefore carries the most common *concrete* command seen for it, not
  just the signature the clustering keyed on.

Support is counted in sessions, not occurrences: one session that ran the same
sweep ten times is one vote. A shorter sequence contained in a longer one is
dropped only when its support is identical, so a widely shared prefix survives
alongside the longer, rarer procedure that extends it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from oversteward.dream.extract import matched_secret
from oversteward.dream.transcripts import enumerate_transcripts, read_records

#: Programs whose arguments are objects, never verbs — no subcommand is kept for them.
_PLAIN_PROGRAMS: frozenset[str] = frozenset(
    {
        "mkdir",
        "rm",
        "cp",
        "mv",
        "touch",
        "ln",
        "chmod",
        "chown",
        "kill",
        "pkill",
        "curl",
        "wget",
        "ssh",
        "scp",
        "bash",
        "sh",
        "source",
        "python",
        "python3",
        "pytest",
        "open",
        "code",
    }
)

#: CLIs whose first word is a resource group, not a verb (``gh pr view``,
#: ``grantspider db scratch``): two bare words are kept. Every other program
#: keeps one, because a second bare word is usually an object (``ruff check src``).
_TWO_LEVEL_CLIS: frozenset[str] = frozenset(
    {"gh", "docker", "railway", "grantspider", "aigranthelper", "oversteward", "wphelper", "fiscus"}
)

#: Python interpreters whose real subject is the script they run.
_PYTHON_PROGRAMS: frozenset[str] = frozenset({"python", "python3", "py"})

#: Wrappers that run another command; the signature belongs to the wrapped one.
#: ``timeout`` consumes its flags, their values and one duration; the rest
#: consume only their leading flags.
_WRAPPERS: frozenset[str] = frozenset({"timeout", "nohup", "sudo", "time", "nice", "env", "exec"})
_DURATION = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
#: ``timeout`` flags whose value is itself duration-shaped and must not be read as the duration.
_TIMEOUT_VALUE_FLAGS: frozenset[str] = frozenset({"-k", "--kill-after", "-s", "--signal"})

#: Shell plumbing, output filters and read-only inspection tools. They carry no
#: procedural meaning: a skill is what you *do*, not what you looked at first.
_NOISE_PROGRAMS: frozenset[str] = frozenset(
    {
        "cd",
        "export",
        "echo",
        "printf",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        "tr",
        "cut",
        "tee",
        "true",
        "false",
        "set",
        "sleep",
        "xargs",
        "cat",
        "ls",
        "find",
        "grep",
        "rg",
        "ugrep",
        "egrep",
        "sed",
        "awk",
        "diff",
        "cmp",
        "stat",
        "file",
        "jq",
        "which",
        "date",
        "pwd",
        "test",
        "read",
    }
)

_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: A token that can be a program name. Anything else at segment head is a
#: fragment of quoted or heredoc text that leaked past the splitter.
_PROGRAM_NAME = re.compile(r"^[A-Za-z0-9_./+-]+$")
#: Shell keywords that prefix a command (``do git fetch``): stripped, the rest signs.
_COMMAND_PREFIX_KEYWORDS: frozenset[str] = frozenset({"do", "then", "else", "if", "elif", "while", "until", "!"})
#: Shell keywords that head a segment without running anything.
_SHELL_KEYWORDS: frozenset[str] = frozenset({"for", "done", "fi", "case", "esac", "in", "function", "select"})


def _split_segments(command: str) -> list[str]:
    """Split a command on ``;`` ``&&`` ``||`` ``|`` and newlines, outside quotes.

    Text inside single or double quotes never splits, so a multi-line
    ``python -c "..."`` body stays one segment. A heredoc (``<<``) ends the
    scan: everything after it is data, not commands.
    """
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                current.append(command[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            current.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < len(command):
            current.append(command[i : i + 2])
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            continue
        if command.startswith("<<", i):
            segments.append("".join(current))
            return [s for s in segments if s.strip()]
        for sep in ("&&", "||", "|", ";", "\n"):
            if command.startswith(sep, i):
                segments.append("".join(current))
                current = []
                i += len(sep)
                break
        else:
            current.append(ch)
            i += 1
    segments.append("".join(current))
    return [s for s in segments if s.strip()]
_BARE_WORD = re.compile(r"^[a-z][a-z0-9_-]*$")
_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


# ---- signatures ------------------------------------------------------------------


def _program_of(tokens: list[str]) -> tuple[str, list[str]]:
    """Return ``(program basename, remaining args)`` after unwrapping prefixes.

    Env assignments (``PYTHONPATH=x``) and wrappers (``timeout 600``, ``nohup``)
    are stripped so the signature names the command that did the work.
    """
    tokens = [t for t in tokens if t != "&"]
    while tokens:
        if _ENV_ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
            continue
        program = Path(tokens[0]).name
        if program == "timeout":
            rest = tokens[1:]
            while rest and not _DURATION.match(rest[0]):
                rest = rest[2:] if rest[0] in _TIMEOUT_VALUE_FLAGS else rest[1:]
            tokens = rest[1:]
            continue
        if program in _WRAPPERS:
            rest = tokens[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
            tokens = rest
            continue
        return program, tokens[1:]
    return "", []


def _bare_subcommands(args: list[str], limit: int) -> list[str]:
    kept: list[str] = []
    for arg in args:
        if len(kept) >= limit or not _BARE_WORD.match(arg):
            break
        kept.append(arg)
    return kept


def _segment_signature(segment: str) -> str:
    """Signature of one pipeline segment, or '' when it is noise."""
    tokens = segment.split()
    while tokens and tokens[0] in _COMMAND_PREFIX_KEYWORDS:
        tokens = tokens[1:]
    program, args = _program_of(tokens)
    if not program or not _PROGRAM_NAME.match(program):
        return ""
    if program in _NOISE_PROGRAMS or program in _SHELL_KEYWORDS:
        return ""
    if program == "uv" and args and args[0] == "run":
        rest = [a for a in args[1:] if not a.startswith("--")]
        return _segment_signature(" ".join(rest)) if rest else "uv run"
    if program in _PYTHON_PROGRAMS:
        script = next((a for a in args if a.endswith(".py")), None)
        if script is None:
            # An inline `python -c` snippet is a one-off, never a repeatable step.
            return ""
        after = args[args.index(script) + 1 :]
        return " ".join([Path(script).name, *_bare_subcommands(after, 1)])
    if program.endswith(".py"):
        return " ".join([program, *_bare_subcommands(args, 1)])
    if program in _PLAIN_PROGRAMS:
        return program
    depth = 2 if program in _TWO_LEVEL_CLIS else 1
    return " ".join([program, *_bare_subcommands(args, depth)])


def signature_of(command: str) -> str:
    """Reduce a shell command to the program-and-subcommand chain it runs.

    Paths, flags, values and output filters are dropped, so two invocations of
    the same procedure with different arguments share a signature. A command
    made only of noise (inspection, plumbing) signs empty and is not a step.
    Consecutive identical segments collapse, so ``A; A; A`` signs as ``A``.
    """
    parts: list[str] = []
    for segment in _split_segments(command.strip()):
        sig = _segment_signature(segment)
        if sig and (not parts or parts[-1] != sig):
            parts.append(sig)
    return " ; ".join(parts)


# ---- runs ------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandCall:
    """One Bash tool call, with the signature it clusters under."""

    session_id: str
    repo: str
    command: str
    description: str
    signature: str


def _is_user_turn(record: dict[str, Any]) -> bool:
    """True for a real user message; tool results are user-role records but not turns."""
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
    return False


def _bash_calls(record: dict[str, Any], session_id: str, repo: str) -> list[CommandCall]:
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    calls: list[CommandCall] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") != "Bash":
            continue
        tool_input = block.get("input") or {}
        command = str(tool_input.get("command", "")).strip()
        if not command:
            continue
        signature = signature_of(command)
        if not signature:
            continue
        calls.append(
            CommandCall(
                session_id=session_id,
                repo=repo,
                command=command,
                description=str(tool_input.get("description", "")).strip(),
                signature=signature,
            )
        )
    return calls


def extract_runs(
    records: Iterable[dict[str, Any]], *, session_id: str, repo: str
) -> list[list[CommandCall]]:
    """Split one transcript's Bash calls into runs bounded by real user turns.

    A run is the stretch of tool calls between two user messages — one
    autonomous pass of work. Sequences are mined inside runs only, so a
    procedure never spans a user's change of subject. Consecutive calls with
    the same signature collapse to one: a poll repeated five times is one step,
    not a five-step procedure.
    """
    runs: list[list[CommandCall]] = []
    current: list[CommandCall] = []
    for record in records:
        if _is_user_turn(record):
            if current:
                runs.append(current)
            current = []
            continue
        for call in _bash_calls(record, session_id, repo):
            if current and current[-1].signature == call.signature:
                continue
            current.append(call)
    if current:
        runs.append(current)
    return runs


# ---- mining ----------------------------------------------------------------------


@dataclass(frozen=True)
class StepExample:
    """The most common concrete form of one step across its supporting sessions.

    ``withheld`` is True when every concrete command seen for the step matched a
    credential pattern; ``command`` is then empty. A transcript is the one
    place a secret is guaranteed to have been typed, so the draft carries the
    signature and nothing else — never a redacted copy.
    """

    signature: str
    command: str
    description: str
    withheld: bool = False


def _is_clean(text: str) -> bool:
    return matched_secret(text) is None


@dataclass(frozen=True)
class SkillCandidate:
    """A contiguous signature sequence and the sessions that ran it."""

    signatures: tuple[str, ...]
    sessions: tuple[str, ...]
    repos: tuple[str, ...]
    examples: tuple[StepExample, ...]

    @property
    def support(self) -> int:
        return len(self.sessions)


def _ngrams(run: list[CommandCall], min_len: int, max_len: int) -> Iterable[tuple[int, int]]:
    for start in range(len(run)):
        for length in range(min_len, max_len + 1):
            end = start + length
            if end > len(run):
                break
            yield start, end


def _is_contiguous_sub(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    if len(short) >= len(long):
        return False
    width = len(short)
    return any(long[i : i + width] == short for i in range(len(long) - width + 1))


def _best_examples(
    signatures: tuple[str, ...], occurrences: list[tuple[CommandCall, ...]]
) -> tuple[StepExample, ...]:
    examples: list[StepExample] = []
    for index, signature in enumerate(signatures):
        commands = Counter(occ[index].command for occ in occurrences if _is_clean(occ[index].command))
        descriptions = Counter(
            occ[index].description
            for occ in occurrences
            if occ[index].description and _is_clean(occ[index].description)
        )
        description = descriptions.most_common(1)[0][0] if descriptions else ""
        if commands:
            command, withheld = commands.most_common(1)[0][0], False
        else:
            command, withheld = "", True
        examples.append(
            StepExample(signature=signature, command=command, description=description, withheld=withheld)
        )
    return tuple(examples)


def mine_candidates(
    runs: Iterable[list[CommandCall]], *, min_sessions: int, min_len: int, max_len: int
) -> list[SkillCandidate]:
    """Find signature sequences that recur across at least ``min_sessions`` sessions.

    Ranked by support, then by length. A sequence contained in a longer one with
    the same support is dropped as redundant; one with wider support is kept.
    """
    sessions_by_seq: dict[tuple[str, ...], set[str]] = defaultdict(set)
    repos_by_seq: dict[tuple[str, ...], set[str]] = defaultdict(set)
    occurrences: dict[tuple[str, ...], list[tuple[CommandCall, ...]]] = defaultdict(list)
    for run in runs:
        for start, end in _ngrams(run, min_len, max_len):
            window = tuple(run[start:end])
            seq = tuple(call.signature for call in window)
            sessions_by_seq[seq].add(window[0].session_id)
            repos_by_seq[seq].add(window[0].repo)
            occurrences[seq].append(window)

    supported = {seq: s for seq, s in sessions_by_seq.items() if len(s) >= min_sessions}
    kept: list[tuple[str, ...]] = []
    for seq in supported:
        subsumed = any(
            _is_contiguous_sub(seq, other) and supported[other] == supported[seq]
            for other in supported
        )
        if not subsumed:
            kept.append(seq)

    candidates = [
        SkillCandidate(
            signatures=seq,
            sessions=tuple(sorted(supported[seq])),
            repos=tuple(sorted(repos_by_seq[seq])),
            examples=_best_examples(seq, occurrences[seq]),
        )
        for seq in kept
    ]
    candidates.sort(key=lambda c: (-c.support, -len(c.signatures), c.signatures))
    return candidates


# ---- existing-skill coverage -------------------------------------------------------


def covering_skills(candidate: SkillCandidate, skills_dirs: Iterable[Path]) -> tuple[str, ...]:
    """Names of existing skills whose SKILL.md mentions every step's signature.

    Advisory only. A draft it flags is probably a procedure a skill already
    prescribes, which means the skill is not being invoked — a different
    finding from "no skill exists".
    """
    names: list[str] = []
    for skills_dir in skills_dirs:
        if not skills_dir.is_dir():
            continue
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            text = skill_md.read_text(encoding="utf-8", errors="replace")
            if all(sig in text for sig in candidate.signatures):
                names.append(skill_md.parent.name)
    return tuple(names)


# ---- drafts ----------------------------------------------------------------------


def slug_for(candidate: SkillCandidate) -> str:
    words = " ".join(candidate.signatures[:3]).replace(".py", "")
    slug = _SLUG_CLEAN.sub("-", words.lower()).strip("-")
    return slug[:60] or "procedure"


def render_draft(candidate: SkillCandidate, *, covered_by: tuple[str, ...] = ()) -> str:
    """Render one candidate as a SKILL.md draft with provenance and a DRAFT marker."""
    slug = slug_for(candidate)
    steps = " → ".join(candidate.signatures)
    lines = [
        "---",
        f"name: {slug}",
        f'description: "DRAFT — mined procedure: {steps}. Rewrite before use: say when to invoke it."',
        "---",
        "",
        f"# /{slug} — DRAFT, mined from {candidate.support} sessions",
        "",
        "This draft was generated by the skill miner from repeated Bash sequences.",
        "It is a starting point, not a skill: rewrite the description, name the",
        "trigger, and delete steps that were incidental.",
        "",
        "## Provenance",
        "",
        f"- sessions: {candidate.support}",
        f"- repos: {', '.join(candidate.repos)}",
        f"- session ids: {', '.join(candidate.sessions)}",
    ]
    if covered_by:
        lines.append(
            f"- already prescribed by: {', '.join(covered_by)} — "
            "the sequence is being re-derived rather than invoked; fix that skill's trigger instead"
        )
    lines += ["", "## Steps", ""]
    for index, example in enumerate(candidate.examples, start=1):
        title = example.description or example.signature
        if example.withheld:
            body = f"   `{example.signature}` — command withheld: every form seen matched a credential pattern"
            lines += [f"{index}. {title}", "", body, ""]
            continue
        lines += [f"{index}. {title}", "", "   ```bash", f"   {example.command}", "   ```", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_drafts(
    candidates: Iterable[SkillCandidate], out_dir: Path, *, skills_dirs: Iterable[Path]
) -> list[Path]:
    """Write one ``<slug>/SKILL.md`` per candidate under ``out_dir`` plus an INDEX.md."""
    skills_dirs = list(skills_dirs)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index_lines = ["# Skill drafts — review, then install or discard", ""]
    used: Counter[str] = Counter()
    for candidate in candidates:
        base = slug_for(candidate)
        used[base] += 1
        slug = base if used[base] == 1 else f"{base}-{used[base]}"
        covered = covering_skills(candidate, skills_dirs)
        target = out_dir / slug / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = render_draft(candidate, covered_by=covered)
        if slug != base:
            text = text.replace(f"name: {base}\n", f"name: {slug}\n", 1)
        target.write_text(text, encoding="utf-8")
        written.append(target)
        note = f" (already in: {', '.join(covered)})" if covered else ""
        index_lines.append(
            f"- `{slug}/` — {candidate.support} sessions, {len(candidate.signatures)} steps: "
            f"{' → '.join(candidate.signatures)}{note}"
        )
    (out_dir / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return written


# ---- end to end ---------------------------------------------------------------------


@dataclass(frozen=True)
class MiningResult:
    """``sessions_unreadable`` counts transcripts that yielded no record at all —
    a corpus that could not be read, which must never report as a clean measurement."""

    sessions_scanned: int
    sessions_unreadable: int
    runs_scanned: int
    candidates: list[SkillCandidate]


def mine_projects_root(
    projects_root: Path,
    *,
    repo: str | None,
    min_sessions: int,
    min_len: int,
    max_len: int,
    since_mtime: float | None = None,
) -> MiningResult:
    """Mine every transcript under ``projects_root`` (optionally one repo, or newer than a time)."""
    metas = enumerate_transcripts(projects_root)
    if repo:
        metas = [m for m in metas if m.repo == repo]
    if since_mtime is not None:
        metas = [m for m in metas if m.mtime >= since_mtime]
    runs: list[list[CommandCall]] = []
    unreadable = 0
    for meta in metas:
        records = read_records(meta.path)
        if not records:
            unreadable += 1
            continue
        runs.extend(extract_runs(records, session_id=meta.session_id, repo=meta.repo))
    candidates = mine_candidates(runs, min_sessions=min_sessions, min_len=min_len, max_len=max_len)
    return MiningResult(
        sessions_scanned=len(metas),
        sessions_unreadable=unreadable,
        runs_scanned=len(runs),
        candidates=candidates,
    )
