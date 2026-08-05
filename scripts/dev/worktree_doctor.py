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

``teardown`` is the one verb that changes state, and it runs in strict order of
recoverability: check what still points here, name the databases the worktree
owns, remove the worktree, and only then drop them. Everything that can fail
happens before anything that cannot be undone, so a teardown that stops halfway
has destroyed nothing.

``sweep`` is the recovery path for the worktrees that never went through
``teardown``. Every other verb names a database by deriving it from a worktree's
path; remove the worktree by any other means and the path is gone, the
derivation has no input, and nothing can name the database again — it simply
sits on the container. So the sweep reconciles the other way: enumerate what the
container holds, subtract what the live worktrees account for, and report the
difference.

    worktree_doctor.py sweep [--repo <path>]    # report; destroys nothing
    worktree_doctor.py sweep --drop             # destroy what it reported

That is a match on *absence*, not a derivation, which makes it the one place
here that could destroy something it never positively named. It is therefore
dry-run by default, it prints which live worktree each database was matched
against so the inference can be audited before it is authorised, and it leaves
alone every name it cannot attribute to this repo's own stems.
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

#: What ``new-session.sh`` writes into every worktree it creates: a symlink to
#: the primary checkout's venv, and a direnv file. Neither is tracked, and
#: neither is reliably ignored — a ``.venv/`` pattern matches a directory but
#: not the symlink git sees as a file — so git counts them as untracked and
#: refuses the removal. The tool's own scaffolding blocked its own teardown on
#: every worktree it had ever created (OS#286).
LAUNCHER_ARTIFACTS = (".venv", ".envrc")

# The docker seam: a callable taking an argv tail and returning stdout, or None
# when docker is absent or unhappy. Injected so tests never need a daemon.
DockerRunner = Callable[[list[str]], "str | None"]


class WorktreeRemovalRefused(RuntimeError):
    """``git worktree remove`` declined — uncommitted work, or a held lock."""


@dataclass(frozen=True)
class Hit:
    """One thing that still references the worktree, and what breaks if it goes."""

    kind: str
    where: str
    detail: str
    breaks: str


def format_hit(hit: Hit) -> str:
    return f"{hit.kind}: {hit.where}\n    references: {hit.detail}\n    breaks:     {hit.breaks}"


def report_capture(worktree: Path, hits: Sequence[Hit], verdict: str) -> None:
    """Print what still points at ``worktree`` — the same account for both verbs."""
    print(f"{len(hits)} reference(s) to {worktree} — {verdict}:\n")
    print("\n\n".join(format_hit(hit) for hit in hits))
    print("\nRun `worktree_doctor.py repair` first, or accept the breakage knowingly.")


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


@dataclass(frozen=True)
class Ownership:
    """Which database names one worktree owns — the only names teardown may drop.

    A worktree can own more than one: aigranthelper keeps two per checkout, and
    the second stem (``test_research``) shares no prefix with the project name.
    The doctor cannot be told them — this file is a byte-identical copy in every
    repo, so per-repo configuration is not available to it. What every database
    a worktree owns *does* share is the derivation in ``worktree_db.derive``:

    * a short name gets ``_<slug>`` appended verbatim;
    * a name that overflowed the 63-byte identifier limit gets ``_<digest>``,
      the digest taken over the worktree's path.

    Both are computable from the worktree alone, so matching on the suffix finds
    every database it owns with no per-repo knowledge at all.
    """

    #: A name the caller supplied outright — matched exactly, nothing derived.
    exact: str | None = None
    #: The suffixes ``worktree_db.derive`` can append for this worktree.
    suffixes: tuple[str, ...] = ()

    def owns(self, database: str) -> bool:
        if self.exact is not None:
            return database == self.exact
        return any(database.endswith(suffix) for suffix in self.suffixes)


#: A tree with no worktree-owned databases at all: a primary checkout, or a repo
#: that has not picked up ``worktree_db.py``.
UNOWNED = Ownership()


def _suffix_claims(module, root: Path) -> Ownership:
    """The suffixes ``worktree_db.derive`` can append for a tree at ``root``.

    The one place either verb turns a path into database names. ``teardown``
    reaches it forwards through :func:`_ownership`; the sweep reaches it for a
    tree it already knows is linked, because git said so.
    """
    slug = module.sanitize(root.name)
    if not slug:
        return UNOWNED
    return Ownership(suffixes=(f"_{slug}", f"_{module.path_digest(str(root))}"))


def _ownership(worktree: Path) -> Ownership:
    """The names ``worktree`` owns, derived from its path — see :class:`Ownership`.

    A tree that is not a *linked* worktree owns nothing. The primary checkout's
    unsuffixed database is the shared bench every session gates against;
    reporting it as state teardown drops would be an invitation to destroy it.
    """
    module = _load_worktree_db()
    if module is None or not module.is_linked_worktree(worktree):
        return UNOWNED
    root = module.toplevel(worktree) or worktree
    slug = module.sanitize(root.name)
    if not slug:
        return UNOWNED
    if f"_{slug}" == module.SUFFIX:
        # A worktree named `test` derives the very suffix every *bench* name
        # ends with — `<project>_test`, for this repo and for every other repo
        # sharing the container. Nothing in the name distinguishes the two, so
        # rather than guess, the doctor claims only the one name it is certain
        # of and discovers no further stems.
        return Ownership(exact=module.database_name(worktree))
    return _suffix_claims(module, root)


#: Every database the server knows. The doctor filters the listing itself, since
#: what a worktree owns is a question about its path, not one postgres can answer.
LIST_DATABASES = "SELECT datname FROM pg_database"


def _psql(container: str, user: str, sql: str) -> list[str]:
    """A ``docker exec`` argv running one query through the maintenance database."""
    return ["exec", container, "psql", "-U", user, "-d", MAINTENANCE_DB, "-tAc", sql]


def _listed(answer: str | None) -> list[str]:
    """The database names in a ``psql -tA`` listing, in a stable order."""
    return sorted(line.strip() for line in (answer or "").splitlines() if line.strip())


def _holders(worktree: Path, docker: DockerRunner, name: str | None) -> list[tuple[str, str, str]]:
    """``(container, superuser, database)`` for every database ``worktree`` owns.

    Listing every database and filtering here — rather than asking after one
    name — is what lets a worktree own N of them without the doctor knowing any
    repo's stems. See :class:`Ownership`.
    """
    ownership = Ownership(exact=name) if name is not None else _ownership(worktree)
    if ownership == UNOWNED:
        return []
    held = []
    for container, user in postgres_containers(docker):
        listing = _listed(docker(_psql(container, user, LIST_DATABASES)))
        held.extend(
            (container, user, database) for database in listing if ownership.owns(database)
        )
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
    """Name every database the worktree owns and drop them; return what went."""
    return drop_held(_holders(worktree, docker, name), docker)


def drop_held(held: Iterable[tuple[str, str, str]], docker: DockerRunner) -> list[str]:
    """Drop already-named databases; return what was dropped.

    Separate from the naming because teardown must name them *before* the
    worktree goes and drop them *after* — every name is derived from the
    worktree's path, so nothing can work them out once it has been removed.

    Unlike ``repair`` — which reports docker work rather than doing it — this is
    reached only through an explicit ``teardown``, where dropping the database
    is the whole point of the verb. Nothing else on the container is touched.
    """
    dropped = []
    for container, user, database in held:
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
# sweep — the databases whose worktree is already gone
# ---------------------------------------------------------------------------
#
# Everywhere else the doctor acts on a name it *derived* from a path it can see.
# Here the path is gone — that is the whole premise — so the only question left
# is which names nothing live accounts for. That is an inference from absence,
# and it is the one place in this family where the doctor could destroy
# something it did not positively derive. Hence: it reports by default, it shows
# which live worktree each database was matched against so the inference can be
# audited, and it drops nothing it cannot attribute to this repo's own stems.


class SweepUnavailable(RuntimeError):
    """The sweep could not look — never to be reported as having found nothing."""


@dataclass(frozen=True)
class Candidate:
    """A database in this repo's derivation shape, and the live tree claiming it."""

    container: str
    user: str
    database: str
    #: The live worktree whose path derives this name. None is the whole finding.
    claimed_by: Path | None

    @property
    def held(self) -> tuple[str, str, str]:
        """The triple :func:`drop_held` drops."""
        return (self.container, self.user, self.database)


@dataclass(frozen=True)
class LiveTree:
    """A linked worktree git still knows about, and the names it accounts for."""

    path: Path
    #: The verbatim ``_<slug>`` its name derives — "" when it derives none.
    suffix: str
    ownership: Ownership


@dataclass(frozen=True)
class Reconciliation:
    """What the container holds, sorted by whether this repo can account for it."""

    candidates: tuple[Candidate, ...]
    #: Databases outside this repo's stems — another repo's, or hand-made. Never
    #: dropped: the doctor has no derivation that could have written them.
    unattributed: tuple[str, ...]

    @property
    def orphans(self) -> tuple[Candidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.claimed_by is None)


#: Databases the server creates for itself. Nobody's bench, so listing them as
#: unattributable would be noise on every run.
SYSTEM_DATABASES = frozenset({"postgres", "template0", "template1"})


def require_worktree_db():
    """The derivation, or a refusal. Absence must stop this verb, not quieten it.

    :func:`_load_worktree_db` tolerates absence because the doctor's other work
    must not stop for one missing family member. The sweep cannot inherit that:
    with no derivation it matches no database, and an empty result reads as
    "nothing is orphaned" when the truth is "I could not look".
    """
    module = _load_worktree_db()
    if module is None:
        raise SweepUnavailable(
            "worktree_db.py is not deployed beside this script — every name the "
            "sweep reasons about comes from it, so without it an orphan and an "
            "unknown are indistinguishable. Deploy the shared/scripts/dev/ family."
        )
    return module


def live_worktrees(repo: Path) -> tuple[Path, list[Path]]:
    """``(primary checkout, linked worktrees)`` as git currently knows them.

    ``git worktree list`` always names the main worktree first. A failure raises
    rather than returning nothing, because nothing is the answer that makes every
    database on the container look unclaimed.
    """
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError as failure:
        raise SweepUnavailable(f"git could not be run in {repo}: {failure}") from failure
    if result.returncode != 0:
        raise SweepUnavailable(f"git could not list the worktrees of {repo}: {result.stderr.strip()}")
    marker = "worktree "
    trees = [
        Path(line[len(marker) :].strip())
        for line in result.stdout.splitlines()
        if line.startswith(marker)
    ]
    if not trees:
        raise SweepUnavailable(f"{repo} is not inside a git checkout")
    return trees[0], trees[1:]


def _live_tree(module, path: Path) -> LiveTree:
    """One worktree git listed, with the names its path derives."""
    slug = module.sanitize(path.name)
    return LiveTree(path, f"_{slug}" if slug else "", _suffix_claims(module, path))


def _revealed_stem(database: str, tree: LiveTree, bench_suffix: str) -> str | None:
    """The stem standing in front of a live worktree's verbatim suffix.

    A repo can own more than one stem — aigranthelper's ``test_research`` shares
    nothing with its project name — and this file is a byte-identical copy in
    every repo, so it cannot be told them. A live worktree reveals them instead:
    every database it owns ends with the suffix its own path derives.

    Only the verbatim ``_<slug>`` reveals anything. The digest form cannot: a
    shortened name is ``<stem>_<cut-slug>_<digest>``, so what precedes the digest
    is the slug, not a stem. Nor can a worktree named ``test``, which derives the
    very suffix every bench name ends with — read as a revelation,
    ``<project>_test`` would yield the stem ``<project>``, and every bench on the
    container would then look like an orphan of it. Same refusal as
    :func:`_ownership`: where the name is ambiguous, discover nothing.
    """
    if not tree.suffix or tree.suffix == bench_suffix:
        return None
    if not database.endswith(tree.suffix) or len(database) <= len(tree.suffix):
        return None
    return database[: -len(tree.suffix)]


def _stems(module, primary: Path, trees: Sequence[LiveTree], databases: Iterable[str]) -> set[str]:
    """Every stem this repo owns: its own, plus whatever a live worktree reveals."""
    stems = {module.base_name(primary)}
    for database in databases:
        for tree in trees:
            revealed = _revealed_stem(database, tree, module.SUFFIX)
            if revealed:
                stems.add(revealed)
    return stems


def _attributed(module, database: str, stems: Iterable[str]) -> str | None:
    """The stem ``database`` was derived from, or None when nothing here owns it.

    ``derive`` only ever writes ``<stem>_<slug>`` or ``<stem>_<cut-slug>_<digest>``,
    every character of it inside the alphabet ``sanitize`` folds to. A name
    outside that shape was not written by the derivation, so nothing here can
    attribute it — and what cannot be attributed is reported, never dropped.

    A bare stem never matches: the shared bench carries no suffix, so no worktree
    ever derived it. That is what keeps ``<project>_test`` out of the result by
    construction rather than by special case.
    """
    if module.sanitize(database) != database:
        return None
    for stem in sorted(stems, key=len, reverse=True):
        if database.startswith(f"{stem}_") and len(database) > len(stem) + 1:
            return stem
    return None


def _database_listings(docker: DockerRunner) -> list[tuple[str, str, list[str]]]:
    """``(container, superuser, databases)`` for every running Postgres.

    Every silence is a refusal. ``docker`` answers None when it is absent or
    unhappy, which by the time it reaches a caller is indistinguishable from an
    empty answer — and an empty answer here reads as "nothing is orphaned".
    """
    if docker(["ps", "--format", "{{.Names}}"]) is None:
        raise SweepUnavailable("docker did not answer `docker ps` — is the daemon running?")
    listings = []
    for container, user in postgres_containers(docker):
        answer = docker(_psql(container, user, LIST_DATABASES))
        if answer is None:
            raise SweepUnavailable(f"{container} did not answer `{LIST_DATABASES}`")
        listings.append((container, user, _listed(answer)))
    if not listings:
        raise SweepUnavailable(
            "no running Postgres container — a stopped bench still holds every "
            "database it ever had, so nothing here could be called an orphan"
        )
    return listings


def reconcile(repo: Path, docker: DockerRunner) -> Reconciliation:
    """Match every database on the container against the worktrees git still lists."""
    module = require_worktree_db()
    primary, linked = live_worktrees(repo)
    trees = [_live_tree(module, path) for path in linked]
    listings = _database_listings(docker)
    everything = [database for _, _, databases in listings for database in databases]
    stems = _stems(module, primary, trees, everything)
    candidates = [
        Candidate(
            container,
            user,
            database,
            next((tree.path for tree in trees if tree.ownership.owns(database)), None),
        )
        for container, user, databases in listings
        for database in databases
        if _attributed(module, database, stems) is not None
    ]
    named = {candidate.database for candidate in candidates}
    return Reconciliation(
        tuple(candidates),
        tuple(sorted(set(everything) - named - SYSTEM_DATABASES)),
    )


def sweep_candidates(repo: Path, docker: DockerRunner) -> list[Candidate]:
    """Every database in this repo's shape, with the live tree that claims it."""
    return list(reconcile(repo, docker).candidates)


def format_candidate(candidate: Candidate) -> str:
    """One reconciled database and what it was matched against — the audit trail."""
    if candidate.claimed_by is None:
        return (
            f"  ORPHAN  {candidate.database} ({candidate.container})\n"
            "            matched: no live worktree derives this name"
        )
    return (
        f"  keep    {candidate.database} ({candidate.container})\n"
        f"            matched: {candidate.claimed_by}"
    )


def report_reconciliation(found: Reconciliation) -> None:
    """Print the whole working — what was matched, what was not, what is unclaimed."""
    print(f"{len(found.candidates)} database(s) in this repo's derivation shape:\n")
    print("\n".join(format_candidate(candidate) for candidate in found.candidates) or "  (none)")
    if found.unattributed:
        print("\nOutside this repo's stems — left alone, never dropped:")
        print("\n".join(f"    {name}" for name in found.unattributed))


def sweep(repo: Path, docker: DockerRunner, drop: bool = False) -> int:
    """Report the databases no live worktree accounts for; drop them only if asked.

    Non-zero means orphans were found and left standing — a question the operator
    still has to answer. Answering it with ``--drop`` exits 0.
    """
    found = reconcile(repo, docker)
    report_reconciliation(found)
    if not found.orphans:
        print("\nNo orphans — every database in this repo's shape has a live worktree.")
        return 0
    if not drop:
        print(
            f"\n{len(found.orphans)} orphan(s). Nothing was dropped: this is a match on "
            "absence, not a derivation.\nAudit the pairing above, then re-run with --drop."
        )
        return 1
    print()
    for dropped in drop_held([candidate.held for candidate in found.orphans], docker):
        print(f"dropped {dropped}")
    return 0


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


def is_tracked(worktree: Path, relative: str) -> bool:
    """True when git has ``relative`` under version control inside ``worktree``.

    A tracked path is by definition not the launcher's scaffolding, whatever its
    name — grantspider commits its ``.envrc``. Asking git makes the rule true
    rather than assumed, and an unanswerable git reads as *tracked*: the cost of
    keeping a file that could have gone is a retry, the cost of deleting one
    that should have stayed is the operator's work.
    """
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", str(worktree), "ls-files", "--error-unmatch", "--", relative],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return result.returncode == 0


def clear_launcher_scaffolding(worktree: Path) -> list[str]:
    """Delete only what ``new-session.sh`` wrote, so it cannot block the removal.

    Deliberately not ``--force``: that discards uncommitted work, the exact loss
    this family exists to prevent. Only the launcher's own symlink and file go —
    a real ``.venv`` *directory* is left alone, because the launcher never
    writes one and deleting a whole environment is no longer scaffolding, and a
    *tracked* path is left alone because it belongs to the repository rather
    than to the launcher. Every other untracked file still refuses the removal.
    """
    cleared = []
    for artifact in LAUNCHER_ARTIFACTS:
        path = worktree / artifact
        if not (path.is_symlink() or path.is_file()):
            continue
        if is_tracked(worktree, artifact):
            continue
        path.unlink()
        cleared.append(artifact)
    return cleared


def dirty_paths(worktree: Path) -> list[str] | None:
    """The paths ``git status`` reports in ``worktree`` — what would refuse a removal.

    ``None`` when git could not be asked, which the caller must read as "there
    may be work here", never as "the tree is clean".
    """
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # `XY path`: the status columns are fixed-width, the path starts at 3. A
    # quoted or renamed entry simply will not equal an artifact name, which
    # lands on the safe side — nothing is cleared.
    return [line[3:] for line in result.stdout.splitlines() if line.strip()]


def blocked_only_by_scaffolding(worktree: Path) -> bool:
    """True when the launcher's own artifacts are all that stands in git's way.

    Clearing is a mutation, so it must not happen on a removal that was going to
    be refused anyway (OS#286: a refused teardown changes nothing). No success
    case turns on this — if anything beyond the artifacts is dirty, git refuses
    whether or not they were cleared first.
    """
    dirty = dirty_paths(worktree)
    return dirty is not None and all(path in LAUNCHER_ARTIFACTS for path in dirty)


def remove_worktree(worktree: Path) -> None:
    """``git worktree remove`` — run from the checkout that owns the worktree.

    A refusal raises :class:`WorktreeRemovalRefused`, carrying git's own reason,
    rather than a raw ``CalledProcessError``: the operator is being told their
    work is uncommitted, which is a message, not a traceback.
    """
    if blocked_only_by_scaffolding(worktree):
        clear_launcher_scaffolding(worktree)
    owner = primary_checkout(worktree) or worktree.parent
    result = subprocess.run(  # list-form argv, no shell
        ["git", "-C", str(owner), "worktree", "remove", str(worktree)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip()
        raise WorktreeRemovalRefused(reason or f"git worktree remove {worktree} failed")


def teardown(
    worktree: Path,
    venvs: Iterable[Path],
    docker: DockerRunner | None = None,
    remove: Callable[[Path], None] = remove_worktree,
    name: str | None = None,
) -> int:
    """Check, remove the worktree, then drop what it owned. Non-zero means refused.

    Most recoverable step first, irreversible last — the ordering rule in the
    module docstring. The databases are *named* before the removal, because
    every name is derived from the worktree's path; they are *dropped* after it,
    because a removal git refuses must cost nothing (OS#286).
    """
    hits = check_worktree(worktree, venvs, docker=docker)
    if hits:
        report_capture(worktree, hits, "teardown refused")
        return 1
    held = _holders(worktree, docker, name) if docker is not None else []
    try:
        remove(worktree)
    except WorktreeRemovalRefused as refused:
        print(f"{worktree} was not removed — nothing was dropped:\n\n    {refused}")
        return 1
    print(f"removed {worktree}")
    if docker is not None:
        for dropped in drop_held(held, docker):
            print(f"dropped {dropped}")
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
    report_capture(worktree, hits, "removing it now would break them")
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


def _sweep(args: argparse.Namespace) -> int:
    """The verb refuses rather than answers whenever it could not look.

    Both refusals go to stderr and exit 2, kept apart from the 1 that means
    "orphans found": a caller has to be able to tell a finding from a failure,
    and nothing on stdout may read as a result the sweep never reached.
    """
    if args.no_docker:
        print(
            "sweep reconciles the container against the live worktrees — "
            "with --no-docker there is nothing to reconcile against",
            file=sys.stderr,
        )
        return 2
    repo = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
    try:
        return sweep(repo, docker_output, drop=args.drop)
    except SweepUnavailable as unavailable:
        print(f"sweep refused — {unavailable}", file=sys.stderr)
        return 2


#: What ``--repo`` means to the verbs that start from a worktree and work outwards.
DERIVED_REPO_HELP = "checkout whose venv to scan (default: derive from the worktree)"


def _add_scan_flags(verb: argparse.ArgumentParser, repo_help: str) -> None:
    """The two flags every verb shares: which checkout, and whether to ask docker."""
    verb.add_argument("--repo", help=repo_help)
    verb.add_argument("--no-docker", action="store_true", help="skip the docker query")


def _add_check_verb(sub) -> None:
    check = sub.add_parser("check", help="fail if anything still references a worktree")
    check.add_argument("worktree", help="the worktree about to be removed")
    _add_scan_flags(check, DERIVED_REPO_HELP)
    check.set_defaults(func=_check)


def _add_repair_verb(sub) -> None:
    repair = sub.add_parser("repair", help="repoint captured shebangs and .pth entries")
    _add_scan_flags(repair, "checkout to repair (default: the current directory)")
    repair.set_defaults(func=_repair)


def _add_teardown_verb(sub) -> None:
    down = sub.add_parser(
        "teardown", help="check, remove the worktree, then drop the databases it owned"
    )
    down.add_argument("worktree", help="the worktree to remove")
    _add_scan_flags(down, DERIVED_REPO_HELP)
    down.set_defaults(func=_teardown)


def _add_sweep_verb(sub) -> None:
    orphans = sub.add_parser(
        "sweep",
        help="report bench databases no live worktree accounts for; --drop destroys them",
    )
    _add_scan_flags(orphans, "checkout to reconcile (default: the current directory)")
    orphans.add_argument(
        "--drop",
        action="store_true",
        help="destroy the reported orphans (the default reports and destroys nothing)",
    )
    orphans.set_defaults(func=_sweep)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    _add_check_verb(sub)
    _add_repair_verb(sub)
    _add_teardown_verb(sub)
    _add_sweep_verb(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
