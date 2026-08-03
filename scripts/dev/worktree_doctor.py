#!/usr/bin/env python3
# ABOUTME: Detects worktree paths captured by a shared venv or docker, and repairs them.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/scripts/dev/.
"""Find out what still points at a worktree before you remove it — and fix what does.

``guard_shared_venv.py`` stops *new* capture. This is the other half: capture
that already happened, and the sweep that would detonate it.

Two things quietly record a worktree's path and outlive the worktree:

* **The shared venv.** ``new-session.sh`` symlinks a worktree's ``.venv`` at the
  primary checkout's, so an env-mutating ``uv`` run from inside the worktree
  rewrites every console-script shebang and the ``__editable__*.pth`` pointer to
  the worktree's path. Remove the worktree and every entry point in every
  checkout on that venv breaks at once.
* **Docker compose.** A compose project stamps ``project.working_dir`` and its
  bind *source* paths onto each container. If the source is gone at restart,
  Docker recreates the deleted worktree path as root-owned directories to
  materialise the mount — a skeleton only ``sudo`` can remove.

Both failures are badly misattributed: the removal looks like the cause, when
the capture happened weeks earlier. Hence ``check`` before the removal.

    worktree_doctor.py check <worktree-path>    # exit 1 if anything points here
    worktree_doctor.py repair [--repo <path>]   # fix the venv, in place

``repair`` is deliberately narrow about what it will do on its own: it rewrites
shebangs and ``.pth`` entries, and it *reports* — never performs — anything
needing docker state changes or root. Those get the exact command to run, and a
human decides.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess  # list-form argv, no shell; docker reads only
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# The estate's session-worktree layout, from new-session.sh: a worktree always
# lives at <primary-checkout>/.claude/worktrees/<name>. That shape is what makes
# the repair a pure path rewrite — the primary checkout is the prefix.
WORKTREE_MARKER = "/.claude/worktrees/"

WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"

SHEBANG_CAPTURE = "venv-script-shebang"
PTH_CAPTURE = "editable-pth"
DOCKER_CAPTURE = "docker-compose-project"

# The docker seam: a callable taking an argv tail and returning stdout, or None
# when docker is absent or unhappy. Injected so tests never need a daemon.
DockerRunner = Callable[[list[str]], "str | None"]


@dataclass(frozen=True)
class Hit:
    """One thing that still references the worktree, and what breaks if it goes."""

    kind: str
    where: str
    detail: str
    breaks: str


def format_hit(hit: Hit) -> str:
    return f"{hit.kind}: {hit.where}\n    references: {hit.detail}\n    breaks:     {hit.breaks}"


# ---------------------------------------------------------------------------
# The one path rewrite both repairs are built on
# ---------------------------------------------------------------------------


def uncapture_path(path: str) -> str | None:
    """Rewrite a path that runs through a session worktree back at its checkout.

    ``/home/n/Repo/.claude/worktrees/wt/.venv/bin/python`` becomes
    ``/home/n/Repo/.venv/bin/python``. None means the path never went through a
    worktree — which is also what makes ``repair`` idempotent: a repaired path
    no longer carries the marker, so the second pass finds nothing.
    """
    index = path.find(WORKTREE_MARKER)
    if index == -1:
        return None
    primary = path[:index]
    _, _, tail = path[index + len(WORKTREE_MARKER) :].partition("/")
    return f"{primary}/{tail}" if tail else primary


def references(text: str, worktree: Path) -> bool:
    """True if ``text`` names ``worktree`` itself or something beneath it."""
    root = str(worktree).rstrip("/")
    return re.search(re.escape(root) + r"(?=/|\s|\"|'|$)", text) is not None


# ---------------------------------------------------------------------------
# Where to look
# ---------------------------------------------------------------------------


def console_scripts(venv: Path) -> list[Path]:
    """Every regular file in a venv's ``bin/`` — console scripts carry shebangs."""
    bin_dir = venv / "bin"
    if not bin_dir.is_dir():
        return []
    return sorted(path for path in bin_dir.iterdir() if path.is_file())


def pth_files(venv: Path) -> list[Path]:
    """Every ``.pth`` in the venv's site-packages, editable pointers included."""
    return sorted(venv.glob("lib/*/site-packages/*.pth"))


def shebang(path: Path) -> str | None:
    """The script's shebang line, or None if it has none / is not text."""
    try:
        with path.open("rb") as handle:
            first = handle.readline(512)
    except OSError:
        return None
    if not first.startswith(b"#!"):
        return None
    return first.decode("utf-8", errors="replace").rstrip("\n")


def _load_guard():
    """The shared-venv predicate from its canonical owner, ``guard_shared_venv.py``.

    Deliberately imported rather than reimplemented: two copies of "is this
    .venv a symlink out of the tree" drifting apart is the exact failure this
    family exists to prevent. Both deploy shapes are covered — canonical sibling
    and the hook location a pickup repo installs it to.
    """
    here = Path(__file__).resolve().parent
    for relative in ("guard_shared_venv.py", "../../.claude/hooks/guard_shared_venv.py"):
        candidate = (here / relative).resolve()
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location("guard_shared_venv", candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise FileNotFoundError(
        "guard_shared_venv.py not found beside this script or in .claude/hooks/ — "
        "deploy the shared/scripts/dev/ family, or pass --repo explicitly."
    )


def venv_of(checkout: Path) -> Path:
    """Where a checkout keeps its environment."""
    return checkout / ".venv"


def default_venvs(worktree: Path) -> list[Path]:
    """The venvs a worktree could have captured: the one it borrows, and its owner's.

    A worktree that was given a private venv can still have captured the shared
    one earlier, so the owning checkout's venv is always included.
    """
    borrowed = _load_guard().shared_venv_target(str(worktree))
    candidates = [Path(borrowed)] if borrowed else []
    owner = primary_checkout(worktree)
    if owner is not None:
        candidates.append(venv_of(owner))
    seen: dict[Path, Path] = {}
    for venv in candidates:
        if venv.is_dir():
            seen.setdefault(venv.resolve(), venv)
    return list(seen.values())


def primary_checkout(tree: Path) -> Path | None:
    """The checkout that owns ``tree``'s git directory — a worktree's primary."""
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", str(tree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    common = result.stdout.strip()
    return Path(common).parent if result.returncode == 0 and common else None


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def venv_hits(venv: Path, worktree: Path) -> list[Hit]:
    """Everything in one venv that still names ``worktree``."""
    hits = []
    for script in console_scripts(venv):
        line = shebang(script)
        if line and references(line, worktree):
            hits.append(
                Hit(
                    SHEBANG_CAPTURE,
                    str(script),
                    line,
                    f"`{script.name}` stops running for every checkout on {venv}",
                )
            )
    for pth in pth_files(venv):
        text = pth.read_text(encoding="utf-8", errors="replace")
        if references(text, worktree):
            hits.append(
                Hit(
                    PTH_CAPTURE,
                    str(pth),
                    text.strip(),
                    f"imports from this editable install resolve into {worktree}",
                )
            )
    return hits


def docker_output(args: list[str]) -> str | None:
    """Run a read-only docker query; None when docker is absent or fails."""
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["docker", *args], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def docker_hits(worktree: Path, docker: DockerRunner) -> list[Hit]:
    """Containers whose compose project is rooted at ``worktree``."""
    output = docker(
        [
            "ps",
            "-a",
            "--filter",
            f"label={WORKING_DIR_LABEL}={worktree}",
            "--format",
            "{{.ID}}\t{{.Names}}",
        ]
    )
    hits = []
    for line in (output or "").splitlines():
        container, _, name = line.partition("\t")
        if not container:
            continue
        hits.append(
            Hit(
                DOCKER_CAPTURE,
                f"{container} ({name})" if name else container,
                f"{WORKING_DIR_LABEL}={worktree}",
                "docker recreates this path as root-owned dirs on restart",
            )
        )
    return hits


def check_worktree(
    worktree: Path, venvs: Iterable[Path], docker: DockerRunner | None = None
) -> list[Hit]:
    """Everything that would break, or be resurrected, by removing ``worktree``."""
    hits: list[Hit] = []
    for venv in venvs:
        hits.extend(venv_hits(venv, worktree))
    if docker is not None:
        hits.extend(docker_hits(worktree, docker))
    return hits


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------


def repair_shebang(script: Path) -> str | None:
    """Repoint a captured shebang at the owning checkout. None if it was fine."""
    line = shebang(script)
    if line is None:
        return None
    fixed = uncapture_path(line)
    if fixed is None or fixed == line:
        return None
    body = script.read_bytes()
    script.write_bytes(fixed.encode("utf-8") + body[body.index(b"\n") :])
    return fixed


def _repair_pth_line(line: str) -> str:
    """Repoint one ``.pth`` entry, keeping its line ending exactly as it was."""
    entry = line.rstrip("\r\n")
    fixed = uncapture_path(entry)
    return line if fixed is None else fixed + line[len(entry) :]


def repair_pth(pth: Path) -> str | None:
    """Repoint captured ``.pth`` entries at the owning checkout. None if fine.

    A file with nothing captured is left byte-for-byte alone — a rewrite that
    "only" normalises a missing trailing newline is still a write to shared
    state, and it would make every run look like it repaired something.
    """
    text = pth.read_text(encoding="utf-8")
    fixed = "".join(_repair_pth_line(line) for line in text.splitlines(keepends=True))
    if fixed == text:
        return None
    pth.write_text(fixed, encoding="utf-8")
    return fixed.strip()


def repair_venv(venv: Path) -> list[str]:
    """Fix every captured shebang and ``.pth`` in one venv; report what changed."""
    fixed = []
    for script in console_scripts(venv):
        repaired = repair_shebang(script)
        if repaired is not None:
            fixed.append(f"shebang  {script} -> {repaired.removeprefix('#!')}")
    for pth in pth_files(venv):
        repaired = repair_pth(pth)
        if repaired is not None:
            fixed.append(f"editable {pth} -> {repaired}")
    return fixed


def stale_container_report(docker: DockerRunner) -> list[str]:
    """Containers whose compose ``working_dir`` is gone — reported, never removed.

    Removing a container is a state change on something a human may still be
    using, so the doctor hands back the exact command instead of running it.
    """
    output = docker(
        ["ps", "-a", "--format", '{{.ID}}\t{{.Names}}\t{{.Label "' + WORKING_DIR_LABEL + '"}}']
    )
    report = []
    for line in (output or "").splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        container, name, working_dir = fields[0], fields[1], fields[2]
        if not working_dir or Path(working_dir).is_dir():
            continue
        report.append(f"docker rm -f {container}    # {name} — working_dir {working_dir} is gone")
    return report


def is_root_owned(path: Path) -> bool:
    try:
        return path.stat().st_uid == 0
    except OSError:
        return False


def skeleton_report(repo: Path, is_root_owned: Callable[[Path], bool] = is_root_owned) -> list[str]:
    """Worktree paths with no git link left — docker bind-mount skeletons.

    Root-owned ones get a ``sudo`` line to copy. The doctor never escalates.
    """
    worktrees = repo / ".claude" / "worktrees"
    if not worktrees.is_dir():
        return []
    report = []
    for path in sorted(worktrees.iterdir()):
        if not path.is_dir() or (path / ".git").exists():
            continue
        prefix = "sudo " if is_root_owned(path) else ""
        report.append(f"{prefix}rm -rf {path}    # worktree skeleton, no git link")
    return report


def repair_repo(repo: Path, docker: DockerRunner | None = None) -> tuple[list[str], list[str]]:
    """Repair ``repo``'s venv in place; return (what was fixed, what needs a human)."""
    fixed = repair_venv(venv_of(repo))
    manual = skeleton_report(repo)
    if docker is not None:
        manual.extend(stale_container_report(docker))
    return fixed, manual


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _check(args: argparse.Namespace) -> int:
    worktree = Path(args.worktree).resolve()
    venvs = [venv_of(Path(args.repo).resolve())] if args.repo else default_venvs(worktree)
    hits = check_worktree(worktree, venvs, docker=None if args.no_docker else docker_output)
    if not hits:
        return 0
    print(f"{len(hits)} reference(s) to {worktree} — removing it now would break them:\n")
    print("\n\n".join(format_hit(hit) for hit in hits))
    print("\nRun `worktree_doctor.py repair` first, or accept the breakage knowingly.")
    return 1


def _repair(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
    fixed, manual = repair_repo(repo, docker=None if args.no_docker else docker_output)
    print("\n".join(fixed) if fixed else f"nothing to repair in {venv_of(repo)}")
    if manual:
        print("\nNeeds a human — the doctor will not do these itself:")
        print("\n".join(f"    {line}" for line in manual))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    check = sub.add_parser("check", help="fail if anything still references a worktree")
    check.add_argument("worktree", help="the worktree about to be removed")
    check.add_argument(
        "--repo", help="checkout whose venv to scan (default: derive from the worktree)"
    )
    check.add_argument("--no-docker", action="store_true", help="skip the docker query")
    check.set_defaults(func=_check)

    repair = sub.add_parser("repair", help="repoint captured shebangs and .pth entries")
    repair.add_argument("--repo", help="checkout to repair (default: the current directory)")
    repair.add_argument("--no-docker", action="store_true", help="skip the docker query")
    repair.set_defaults(func=_repair)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
