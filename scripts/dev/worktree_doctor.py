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

# Not a capture: state the worktree owns and teardown drops. Kept out of the
# blocking set deliberately — see check_worktree.
DATABASE_OWNED = "worktree-database"

# The database every psql/dropdb call connects THROUGH. Never the database being
# looked for or dropped, and never the implicit default: with no ``-d``, libpq
# connects to a database named after the user, which no estate container has
# (OS#278). ``postgres`` is created by the official image on every bootstrap.
MAINTENANCE_DB = "postgres"

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


def _load_sibling(name: str, *relatives: str):
    """Import a family member by path, or None when it is not deployed here.

    Deliberately imported rather than reimplemented: two copies of the same
    predicate drifting apart is the exact failure this family exists to prevent.
    Every deploy shape is covered — canonical sibling, and the hook location a
    pickup repo installs to.
    """
    here = Path(__file__).resolve().parent
    for relative in relatives:
        candidate = (here / relative).resolve()
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location(name, candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None


def _load_guard():
    """The shared-venv predicate from its canonical owner, ``guard_shared_venv.py``."""
    module = _load_sibling(
        "guard_shared_venv", "guard_shared_venv.py", "../../.claude/hooks/guard_shared_venv.py"
    )
    if module is None:
        raise FileNotFoundError(
            "guard_shared_venv.py not found beside this script or in .claude/hooks/ — "
            "deploy the shared/scripts/dev/ family, or pass --repo explicitly."
        )
    return module


def _load_worktree_db():
    """The database-name derivation from ``worktree_db.py``, or None if not deployed.

    Absence is tolerated: a repo that has not picked up ``worktree_db.py`` has no
    per-worktree databases to find, and the doctor's other work must not stop
    because one family member is missing.
    """
    return _load_sibling("worktree_db", "worktree_db.py")


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


def bind_sources(container: str, docker: DockerRunner) -> list[str]:
    """The host paths a container bind-mounts. Named volumes are not paths."""
    output = docker(
        [
            "inspect",
            "--format",
            '{{range .Mounts}}{{if eq .Type "bind"}}{{println .Source}}{{end}}{{end}}',
            container,
        ]
    )
    return [line.strip() for line in (output or "").splitlines() if line.strip()]


def _under(path: str, root: Path) -> bool:
    """True when ``path`` is ``root`` or sits beneath it — not merely prefixed."""
    base = str(root).rstrip("/")
    return path == base or path.startswith(f"{base}/")


def docker_hits(worktree: Path, docker: DockerRunner) -> list[Hit]:
    """Containers that bind-mount a path inside ``worktree``.

    The compose ``working_dir`` label narrows the candidates cheaply, but it is
    not the breakage on its own. A shared bench container under one fixed
    compose project outlives every worktree, so its label names whichever tree
    happened to run ``compose up`` first — and blocking that tree's teardown for
    a container it does not own is a false positive that never clears. What
    actually breaks is a *bind mount*: with the source gone, docker recreates the
    deleted path as root-owned directories to materialise it.
    """
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
        captured = [source for source in bind_sources(container, docker) if _under(source, worktree)]
        if not captured:
            continue
        hits.append(
            Hit(
                DOCKER_CAPTURE,
                f"{container} ({name})" if name else container,
                f"bind mount {captured[0]}",
                "docker recreates this path as root-owned dirs on restart",
            )
        )
    return hits


def check_worktree(
    worktree: Path, venvs: Iterable[Path], docker: DockerRunner | None = None
) -> list[Hit]:
    """Everything that would break, or be resurrected, by removing ``worktree``.

    The worktree's own database is deliberately NOT here: it is state the
    worktree owns and teardown drops, not capture that breaks another checkout.
    Counting it would block every teardown of every worktree forever. See
    :func:`database_hits`.
    """
    hits: list[Hit] = []
    for venv in venvs:
        hits.extend(venv_hits(venv, worktree))
    if docker is not None:
        hits.extend(docker_hits(worktree, docker))
    return hits


# ---------------------------------------------------------------------------
# the worktree's database on the shared test container
# ---------------------------------------------------------------------------


def postgres_containers(docker: DockerRunner) -> list[tuple[str, str]]:
    """Running containers that are a Postgres, as ``(container, superuser)``.

    The superuser comes from the image's own ``POSTGRES_USER`` rather than a
    constant, because the name differs per repo (``grantspider``,
    ``aigranthelper``) and this file is a byte-identical copy in all of them. A
    container with no ``POSTGRES_USER`` is not a Postgres, and is never exec'd
    into.
    """
    listing = docker(["ps", "--format", "{{.Names}}"])
    found = []
    for container in (listing or "").split():
        env = docker(
            ["inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", container]
        )
        for line in (env or "").splitlines():
            key, _, value = line.partition("=")
            if key == "POSTGRES_USER" and value:
                found.append((container, value))
                break
    return found


def _database_name(worktree: Path, name: str | None) -> str | None:
    if name is not None:
        return name
    module = _load_worktree_db()
    if module is None:
        return None
    try:
        return module.database_name(worktree)
    except FileNotFoundError:
        return None


def _holders(worktree: Path, docker: DockerRunner, name: str | None) -> list[tuple[str, str, str]]:
    """``(container, superuser, database)`` for every container holding the database."""
    database = _database_name(worktree, name)
    if not database:
        return []
    held = []
    for container, user in postgres_containers(docker):
        answer = docker(
            [
                "exec",
                container,
                "psql",
                "-U",
                user,
                # Without ``-d``, libpq connects to a database named after the
                # user — which no estate container has, since POSTGRES_DB is
                # ``<project>_test`` and POSTGRES_USER is ``<project>``. The
                # probe then fails to connect and every worktree reads as
                # database-free (OS#278). ``postgres`` is the maintenance
                # database the official image always creates.
                "-d",
                MAINTENANCE_DB,
                "-tAc",
                f"SELECT 1 FROM pg_database WHERE datname = '{database}'",
            ]
        )
        if (answer or "").strip() == "1":
            held.append((container, user, database))
    return held


def database_hits(
    worktree: Path, docker: DockerRunner, name: str | None = None
) -> list[Hit]:
    """The databases ``worktree`` owns on the shared test container.

    Reported as owned state, not as a blocker — see :func:`check_worktree`.
    """
    return [
        Hit(
            DATABASE_OWNED,
            f"{container} ({database})",
            f"database {database}",
            "left behind on the shared container when the worktree goes",
        )
        for container, _, database in _holders(worktree, docker, name)
    ]


def drop_database(worktree: Path, docker: DockerRunner, name: str | None = None) -> list[str]:
    """Drop the worktree's database; return what was dropped.

    Unlike ``repair`` — which reports docker work rather than doing it — this is
    reached only through an explicit ``teardown``, where dropping the database
    is the whole point of the verb. Nothing else on the container is touched.
    """
    dropped = []
    for container, user, database in _holders(worktree, docker, name):
        # ``--maintenance-db`` for the same reason as the probe's ``-d``, with
        # one addition: a client cannot drop the database it is connected to.
        docker(
            [
                "exec",
                container,
                "dropdb",
                "--if-exists",
                "-U",
                user,
                "--maintenance-db",
                MAINTENANCE_DB,
                database,
            ]
        )
        dropped.append(f"{database} ({container})")
    return dropped


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


def remove_worktree(worktree: Path) -> None:
    """``git worktree remove`` — run from the checkout that owns the worktree."""
    owner = primary_checkout(worktree) or worktree.parent
    subprocess.run(  # list-form argv, no shell
        ["git", "-C", str(owner), "worktree", "remove", str(worktree)],
        check=True,
        timeout=60,
    )


def teardown(
    worktree: Path,
    venvs: Iterable[Path],
    docker: DockerRunner | None = None,
    remove: Callable[[Path], None] = remove_worktree,
    name: str | None = None,
) -> int:
    """Check, drop the worktree's database, then remove it. Non-zero means refused.

    The order is the point. Capture is checked first and stops everything, so a
    refused teardown changes nothing at all — no database dropped, no worktree
    gone. Only once nothing else points here does the doctor touch state.

    This is the one verb that acts on docker rather than reporting it: dropping
    the database *is* the teardown, and it is reached only by asking for one.
    """
    hits = check_worktree(worktree, venvs, docker=docker)
    if hits:
        print(f"{len(hits)} reference(s) to {worktree} — teardown refused:\n")
        print("\n\n".join(format_hit(hit) for hit in hits))
        print("\nRun `worktree_doctor.py repair` first, or accept the breakage knowingly.")
        return 1
    if docker is not None:
        for dropped in drop_database(worktree, docker, name=name):
            print(f"dropped {dropped}")
    remove(worktree)
    print(f"removed {worktree}")
    return 0


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


def _venvs_for(args: argparse.Namespace, worktree: Path) -> list[Path]:
    return [venv_of(Path(args.repo).resolve())] if args.repo else default_venvs(worktree)


def _check(args: argparse.Namespace) -> int:
    worktree = Path(args.worktree).resolve()
    venvs = _venvs_for(args, worktree)
    docker = None if args.no_docker else docker_output
    hits = check_worktree(worktree, venvs, docker=docker)
    if docker is not None:
        owned = database_hits(worktree, docker)
        if owned:
            print("Worktree-owned state — `worktree_doctor.py teardown` drops it:\n")
            print("\n\n".join(format_hit(hit) for hit in owned))
            print()
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


def _teardown(args: argparse.Namespace) -> int:
    worktree = Path(args.worktree).resolve()
    return teardown(
        worktree,
        _venvs_for(args, worktree),
        docker=None if args.no_docker else docker_output,
    )


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

    down = sub.add_parser("teardown", help="check, drop the worktree's database, remove it")
    down.add_argument("worktree", help="the worktree to remove")
    down.add_argument(
        "--repo", help="checkout whose venv to scan (default: derive from the worktree)"
    )
    down.add_argument("--no-docker", action="store_true", help="skip the docker query")
    down.set_defaults(func=_teardown)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
