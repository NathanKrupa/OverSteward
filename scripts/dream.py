# ABOUTME: Thin CLI for the dream cycle — transcript reader plus the convergent runner's batch steps.
# ABOUTME: Parses args, calls the oversteward.dream services, formats JSON. No business logic here.

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from oversteward.dream import correction, cycle, kaizen, promotion, roadmap, runlock, store_health
from oversteward.dream.consolidate import MemoryStore, StoreUnreadable, commit_store
from oversteward.dream.extract import CandidateFact
from oversteward.dream.ledger import ProcessedLedger
from oversteward.dream.standing import classify
from oversteward.dream.supersede import supersede
from oversteward.dream.transcripts import (
    TranscriptMeta,
    default_projects_root,
    enumerate_transcripts,
    find_transcript,
    parse_transcript,
)
from oversteward.estate_map.checkouts import TreeReader
from oversteward.sow.runners import GitCommand
from oversteward.stage_health.sources import GithubIssueStates

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "registry.yaml"


def _format_meta(meta: TranscriptMeta) -> str:
    when = datetime.fromtimestamp(meta.mtime).strftime("%Y-%m-%d %H:%M")
    tag = " [worktree]" if meta.is_worktree else ""
    return f"{when}  {meta.repo:16s}  {meta.session_id}{tag}"


def _cmd_list(args: argparse.Namespace) -> int:
    metas = enumerate_transcripts(args.projects_root)
    if args.repo:
        metas = [m for m in metas if m.repo == args.repo]
    for meta in metas:
        print(_format_meta(meta))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    meta = find_transcript(args.projects_root, args.session_id)
    if meta is None:
        print(f"No transcript found for session {args.session_id!r}", file=sys.stderr)
        return 1
    print(parse_transcript(meta.path))
    return 0


# ---- cycle subcommands (the /dream skill's deterministic steps) --------------


def _read_json(path: str):
    # Reason: `path` is an explicit CLI argument from the operator running this
    # command locally, not untrusted input crossing a trust boundary. Confining
    # it to a base directory would break the legitimate use (reading worksheets
    # and verdict files from wherever the operator put them) without denying an
    # attacker anything — anyone who can pass this argument already has the
    # operator's own filesystem access.
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")  # noqa: SEC-012
    return json.loads(text)


def _emit(payload: object) -> int:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _run_lock(args: argparse.Namespace) -> tuple[runlock.RunLock, runlock.Holder, str]:
    holder = runlock.discover_holder()
    trigger = args.trigger or runlock.default_trigger(holder, dict(os.environ))
    return runlock.RunLock(Path(args.lock), Path(args.runs)), holder, trigger


def _cmd_begin(args: argparse.Namespace) -> int:
    lock, holder, trigger = _run_lock(args)
    acquired = lock.ensure(holder, trigger)
    return _emit({"holder": holder.pid, "trigger": trigger, "acquired": acquired})


def _cmd_end(args: argparse.Namespace) -> int:
    lock, holder, trigger = _run_lock(args)
    # No ensure: `end` closes a run, it never opens one. release refuses a lock
    # another run holds, and on a free lock records only the `ended` row.
    lock.release(holder, runlock.ENDED, reason=args.reason, trigger=trigger)
    return _emit({"holder": holder.pid, "ended": args.reason})


def _cmd_unprocessed(args: argparse.Namespace) -> int:
    ledger = ProcessedLedger(Path(args.ledger))
    pending = cycle.find_unprocessed(args.projects_root, ledger, repo=args.repo)
    return _emit([p.to_dict() for p in pending])


def _cmd_worksheet(args: argparse.Namespace) -> int:
    raw = sys.stdin.read() if args.extract == "-" else Path(args.extract).read_text(encoding="utf-8")
    store = MemoryStore(Path(args.store))
    sheets = cycle.build_worksheets(raw, store, top_k=args.top_k)
    return _emit({"worksheets": [s.to_dict() for s in sheets]})


def _cmd_apply(args: argparse.Namespace) -> int:
    lock, holder, trigger = _run_lock(args)
    lock.ensure(holder, trigger)
    sheets = _read_json(args.worksheet)["worksheets"]
    verdicts = _read_json(args.verdicts)
    if len(sheets) != len(verdicts):
        print("worksheet/verdicts length mismatch", file=sys.stderr)
        return 1
    judged = [
        (CandidateFact.from_dict(sheet["candidate"]), cycle.Verdict.from_dict(verdict))
        for sheet, verdict in zip(sheets, verdicts)
    ]
    store = MemoryStore(Path(args.store))
    today = date.fromisoformat(args.today) if args.today else date.today()
    outcomes = cycle.apply_verdicts(judged, store, today=today, session_id=args.session)
    return _emit(
        {
            "outcomes": [
                {"action": o.action, "similarity": o.similarity, "description": o.candidate.description}
                for o in outcomes
            ],
            "flagged": [cycle.flagged_to_dict(f) for f in cycle.collect_flagged(outcomes)],
            "written_paths": [str(p) for p in cycle.collect_written_paths(store, outcomes)],
        }
    )


def _cmd_finalize(args: argparse.Namespace) -> int:
    lock, holder, trigger = _run_lock(args)
    lock.ensure(holder, trigger)
    results = _read_json(args.results)
    store = MemoryStore(Path(args.store))
    ledger = ProcessedLedger(Path(args.ledger))
    run_results = cycle.RunResults(
        flagged=[cycle.flagged_from_dict(d) for d in results.get("flagged", [])],
        written_paths=[Path(p) for p in results.get("written_paths", [])],
        processed=[cycle.PendingTranscript.from_dict(d) for d in results.get("transcripts", [])],
    )
    result = cycle.finalize_run(
        store,
        run_results,
        ledger,
        cycle.FinalizeOptions(
            repo_root=Path(args.store_repo),
            message=args.message,
            queue_path=Path(args.queue) if args.queue else None,
            flagged_path=Path(args.flagged) if args.flagged else None,
            dangling_before=_snapshot_targets(args.dangling_before),
        ),
    )
    # Success only: a finalize that raised keeps the lock for its retry.
    lock.release(holder, runlock.COMPLETED, count=len(run_results.processed))
    return _emit(
        {
            "committed": result.commit.committed,
            "message": result.commit.message,
            "index_path": str(result.index_path),
            "review_path": str(result.review_path),
            "recorded": result.recorded,
            "queue_drained": result.queue_drained,
            "open_flagged": result.open_flagged,
            "store_health": result.store_health.to_dict() if result.store_health else None,
        }
    )


def _snapshot_targets(path: str | None) -> frozenset[str] | None:
    """The queued targets of a `cycle store-health` report, or None without one."""
    if path is None:
        return None
    return frozenset(entry["target"] for entry in _read_json(path)["queue"])


def _cmd_store_health(args: argparse.Namespace) -> int:
    """Read-only, so no run lock. Exit 1 over a ceiling; StoreUnreadable exits 2 in main."""
    today = date.fromisoformat(args.today) if args.today else date.today()
    health = store_health.assess(MemoryStore(Path(args.store)), Path(args.store_repo), today=today)
    _emit(health.to_dict(args.limit))
    return 1 if health.over else 0


def _correction_sources() -> correction.Sources:
    """Every registry checkout with a local_path, read the way `estate_map.py check` reads them."""
    try:
        registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise correction.WorklistUnreadable(f"registry unreadable: {exc}") from exc
    found = correction.tree_checkouts(registry, home_root=ROOT)
    return correction.Sources(
        trees=TreeReader(GitCommand(), found), repos=tuple(found), issue_states=GithubIssueStates()
    )


def _cmd_correction_worklist(args: argparse.Namespace) -> int:
    """Read-only, so no run lock. WorklistUnreadable exits 2 in main."""
    today = date.fromisoformat(args.today) if args.today else date.today()
    worklist = correction.build_worklist(
        MemoryStore(Path(args.store)),
        args.correction_sources or _correction_sources(),
        today=today,
        min_age_days=args.min_age_days,
        limit=args.limit,
    )
    return _emit(worklist.to_dict())


def _add_correction_subparser(sub: argparse._SubParsersAction) -> None:
    grp = sub.add_parser("correction", help="the correction pass over stale Laws and Habits (OS#691)")
    actions = grp.add_subparsers(dest="action", required=True)

    wkl = actions.add_parser(
        "worklist", help="read-only: least recently reinforced Laws/Habits + evidence (JSON)"
    )
    wkl.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    wkl.add_argument("--min-age-days", type=int, default=correction.DEFAULT_MIN_AGE_DAYS)
    wkl.add_argument("--limit", type=int, default=correction.DEFAULT_LIMIT)
    wkl.add_argument("--today", default=None, help="YYYY-MM-DD stamp (default: today)")
    wkl.set_defaults(func=_cmd_correction_worklist)


def _cmd_drain(args: argparse.Namespace) -> int:
    lock, holder, trigger = _run_lock(args)
    acquired = lock.ensure(holder, trigger)
    store = MemoryStore(Path(args.store))
    flagged_store = cycle.FlaggedStore(Path(args.flagged))
    keys = args.key or None
    result = cycle.drain_flagged(store, flagged_store, keys=keys)
    if not args.no_commit and result.drained:
        message = f"dream: drain {result.drained} reviewed hold(s) {cycle.SKIP_CI_MARKER}"
        commit_store(Path(args.store_repo), [result.review_path], message)
    if acquired:
        lock.release(holder, runlock.ENDED, reason="drain")
    return _emit(
        {
            "drained": result.drained,
            "remaining": result.remaining,
            "review_path": str(result.review_path),
        }
    )


def _cmd_supersede(args: argparse.Namespace) -> int:
    lock, holder, trigger = _run_lock(args)
    acquired = lock.ensure(holder, trigger)
    store = MemoryStore(Path(args.store))
    memory = supersede(store, args.memory, args.replacement)
    index_path = store.regenerate_index()
    if acquired:
        lock.release(holder, runlock.ENDED, reason="supersede")
    return _emit(
        {
            "filename": memory.filename,
            "superseded_by": memory.metadata["superseded_by"],
            "kind": classify(memory).kind,
            "index_path": str(index_path),
        }
    )


def _cmd_roadmap_probe(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today) if args.today else date.today()
    report = roadmap.probe_repo(Path(args.roadmap), Path(args.repo_root), now=today)
    return _emit(report.to_dict())


def _cmd_roadmap_packet(args: argparse.Namespace) -> int:
    issues = _read_json(args.issues) if args.issues else []
    prs = _read_json(args.prs) if args.prs else []
    packet = roadmap.packet_for_repo(
        Path(args.roadmap), Path(args.repo_root), issues=issues, prs=prs
    )
    sys.stdout.write(packet)
    return 0


def _add_roadmap_subparser(sub: argparse._SubParsersAction) -> None:
    grp = sub.add_parser("roadmap", help="intent-reconciliation pass over ROADMAP.md (§13.4)")
    actions = grp.add_subparsers(dest="action", required=True)

    prb = actions.add_parser("probe", help="is the roadmap due for reconciliation? (JSON)")
    prb.add_argument("--roadmap", default=str(cycle.OVERSTEWARD_ROOT / "documentation/ROADMAP.md"))
    prb.add_argument("--repo-root", default=str(cycle.OVERSTEWARD_ROOT))
    prb.add_argument("--today", default=None, help="YYYY-MM-DD stamp (default: today)")
    prb.set_defaults(func=_cmd_roadmap_probe)

    pkt = actions.add_parser("packet", help="reconciliation context packet (markdown)")
    pkt.add_argument("--roadmap", default=str(cycle.OVERSTEWARD_ROOT / "documentation/ROADMAP.md"))
    pkt.add_argument("--repo-root", default=str(cycle.OVERSTEWARD_ROOT))
    pkt.add_argument("--issues", default=None, help="gh issue snapshot JSON file, or - for stdin")
    pkt.add_argument("--prs", default=None, help="gh pr snapshot JSON file")
    pkt.set_defaults(func=_cmd_roadmap_packet)


def _cmd_promotion_probe(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today) if args.today else date.today()
    ledger = Path(args.ledger or promotion.default_promotion_ledger_path(Path(args.repo_root)))
    probe = promotion.probe_due(promotion.read_last_run(ledger), today=today)
    return _emit(probe.to_dict())


def _cmd_promotion_packet(args: argparse.Namespace) -> int:
    """Build the worklist packet from a `fiscus review trajectories` JSON report.

    A :class:`FalseGreenError` exits 2, distinct from 1, so the caller can tell
    "the estate has nothing to promote" from "the detector is broken" — the two
    must never render the same (Fiscus #101).
    """
    report = _read_json(args.report)
    today = date.fromisoformat(args.today) if args.today else date.today()
    try:
        candidates = promotion.build_worklist(
            report, min_recurrence=args.min_recurrence, cap=args.cap
        )
    except promotion.FalseGreenError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    sys.stdout.write(promotion.format_packet(candidates, generated_on=today))
    if args.record:
        ledger = Path(args.ledger or promotion.default_promotion_ledger_path(Path(args.repo_root)))
        promotion.record_run(ledger, ran_on=today, candidates=len(candidates))
    return 0


def _add_promotion_subparser(sub: argparse._SubParsersAction) -> None:
    grp = sub.add_parser(
        "promotion", help="trajectory-promotion pass — recurring lessons → doctrine (§13.5)"
    )
    actions = grp.add_subparsers(dest="action", required=True)

    prb = actions.add_parser("probe", help="is the monthly promotion pass due? (JSON)")
    prb.add_argument("--repo-root", default=str(cycle.OVERSTEWARD_ROOT))
    prb.add_argument("--ledger", default=None, help="run-ledger path (default: data/dream)")
    prb.add_argument("--today", default=None, help="YYYY-MM-DD stamp (default: today)")
    prb.set_defaults(func=_cmd_promotion_probe)

    pkt = actions.add_parser("packet", help="promotion worklist packet (markdown)")
    pkt.add_argument("--report", required=True, help="fiscus trajectories JSON, or - for stdin")
    pkt.add_argument("--repo-root", default=str(cycle.OVERSTEWARD_ROOT))
    pkt.add_argument("--ledger", default=None, help="run-ledger path (default: data/dream)")
    pkt.add_argument("--today", default=None, help="YYYY-MM-DD stamp (default: today)")
    pkt.add_argument("--min-recurrence", type=int, default=promotion.MIN_RECURRENCE)
    pkt.add_argument("--cap", type=int, default=promotion.DEFAULT_CAP)
    pkt.add_argument("--record", action="store_true", help="record this run in the ledger")
    pkt.set_defaults(func=_cmd_promotion_packet)


def _kaizen_ledger(args: argparse.Namespace) -> Path:
    return Path(args.ledger or Path(args.repo_root) / "data" / "dream" / "kaizen.json")


def _cmd_kaizen_next(args: argparse.Namespace) -> int:
    """The session-start surface: one item, or a measured empty backlog.

    Exits 2 on a :class:`FalseGreenError` — same contract as `promotion packet`,
    so "nothing to fix" and "the detector is broken" never render the same.

    A *degraded* report stays exit 0 and banners instead (OS#352): the fallback
    still surfaces genuine lessons, so refusing it would cost more than the
    coarse ranking does. Exit 2 stays reserved for an instrument that saw
    nothing at all.
    """
    report = _read_json(args.report) if args.report else None
    try:
        candidates = promotion.build_worklist(report, cap=args.cap) if report else []
        queue = kaizen.build_queue(
            candidates=candidates,
            issues=_read_json(args.issues) if args.issues else [],
            verdicts=kaizen.read_verdicts(_kaizen_ledger(args)),
            repo=args.repo,
            report=report,
        )
    except promotion.FalseGreenError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    clustering = promotion.read_clustering_status(report) if report is not None else None
    sys.stdout.write(
        kaizen.format_next(
            kaizen.next_item(queue), queue_size=len(queue), clustering=clustering
        )
    )
    return 0


def _cmd_kaizen_resolve(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today) if args.today else date.today()
    kaizen.record_verdict(
        _kaizen_ledger(args), key=args.key, verdict=args.verdict, on=today, note=args.note or ""
    )
    return _emit({"key": args.key, "verdict": args.verdict, "on": today.isoformat()})


def _add_kaizen_subparser(sub: argparse._SubParsersAction) -> None:
    grp = sub.add_parser("kaizen", help="session-start queue — fix one recurring defect (OS#332)")
    actions = grp.add_subparsers(dest="action", required=True)

    nxt = actions.add_parser("next", help="this session's item (markdown)")
    nxt.add_argument("--report", default=None, help="fiscus trajectories JSON, or - for stdin")
    nxt.add_argument("--issues", default=None, help="gh issue snapshot JSON file")
    nxt.add_argument("--repo", default=kaizen.DEFAULT_REPO)
    nxt.add_argument("--repo-root", default=str(cycle.OVERSTEWARD_ROOT))
    nxt.add_argument("--ledger", default=None, help="verdict-ledger path (default: data/dream)")
    nxt.add_argument("--cap", type=int, default=promotion.DEFAULT_CAP)
    nxt.set_defaults(func=_cmd_kaizen_next)

    res = actions.add_parser("resolve", help="record a verdict so the item stops resurfacing")
    res.add_argument("--key", required=True, help="the item key printed by `kaizen next`")
    res.add_argument("--verdict", required=True, choices=kaizen.VERDICTS)
    res.add_argument("--note", default=None, help="why — one line")
    res.add_argument("--repo-root", default=str(cycle.OVERSTEWARD_ROOT))
    res.add_argument("--ledger", default=None, help="verdict-ledger path (default: data/dream)")
    res.add_argument("--today", default=None, help="YYYY-MM-DD stamp (default: today)")
    res.set_defaults(func=_cmd_kaizen_resolve)


def _add_supersede_subparser(sub: argparse._SubParsersAction) -> None:
    sup = sub.add_parser(
        "supersede",
        help="mark ONE stored memory retired (metadata.superseded_by) + rebuild the index",
    )
    sup.add_argument("memory", help="the memory's <slug>.md basename (bare slug accepted)")
    sup.add_argument("replacement", help="what to reach for instead, or 'no successor — <why>'")
    sup.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    _add_lock_args(sup)
    sup.set_defaults(func=_cmd_supersede)


def _add_transcripts_subparser(sub: argparse._SubParsersAction) -> None:
    transcripts = sub.add_parser("transcripts", help="inspect session transcripts")
    actions = transcripts.add_subparsers(dest="action", required=True)
    list_p = actions.add_parser("list", help="enumerate discovered transcripts")
    list_p.add_argument("--repo", help="filter to one inferred repo")
    list_p.set_defaults(func=_cmd_list)
    show_p = actions.add_parser("show", help="render one transcript as role-tagged text")
    show_p.add_argument("session_id")
    show_p.set_defaults(func=_cmd_show)


def _add_lock_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lock", default=str(runlock.DEFAULT_LOCK_PATH), help="run-lock path")
    parser.add_argument("--runs", default=str(runlock.DEFAULT_RUNS_PATH), help="run-ledger path")
    parser.add_argument(
        "--trigger",
        choices=runlock.TRIGGERS,
        default=None,
        help=f"what started this run (default: ${runlock.TRIGGER_ENV}, else session/manual)",
    )


def _add_cycle_subparser(sub: argparse._SubParsersAction) -> None:
    grp = sub.add_parser("cycle", help="the convergent dream-cycle batch steps")
    actions = grp.add_subparsers(dest="action", required=True)

    bgn = actions.add_parser("begin", help="take the machine-wide run lock (exit 3: another run holds it)")
    _add_lock_args(bgn)
    bgn.set_defaults(func=_cmd_begin)

    end = actions.add_parser("end", help="release the run lock and close the run with a reason")
    end.add_argument("--reason", required=True, help="why the run ended, one line")
    _add_lock_args(end)
    end.set_defaults(func=_cmd_end)

    unp = actions.add_parser("unprocessed", help="transcripts not yet in the ledger (JSON)")
    unp.add_argument("--projects-root", default=None)
    unp.add_argument("--ledger", default=str(cycle.DEFAULT_LEDGER_PATH))
    unp.add_argument("--repo", default=None, help="filter to one inferred repo")
    unp.set_defaults(func=_cmd_unprocessed)

    wks = actions.add_parser("worksheet", help="gate + prefilter raw extractor output (JSON)")
    wks.add_argument("--extract", required=True, help="raw extractor JSON file, or - for stdin")
    wks.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    wks.add_argument("--top-k", type=int, default=10)
    wks.set_defaults(func=_cmd_worksheet)

    app = actions.add_parser("apply", help="apply in-session verdicts to the store (JSON)")
    app.add_argument("--worksheet", required=True, help="worksheet JSON from `cycle worksheet`")
    app.add_argument("--verdicts", required=True, help="judge verdicts JSON, aligned by index")
    app.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    app.add_argument("--today", default=None, help="YYYY-MM-DD stamp (default: today)")
    app.add_argument("--session", default=None, help="originating session id")
    _add_lock_args(app)
    app.set_defaults(func=_cmd_apply)

    fin = actions.add_parser("finalize", help="index + review + commit + ledger (JSON)")
    fin.add_argument("--results", required=True, help="merged flagged/written/transcripts JSON")
    fin.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    fin.add_argument("--store-repo", default=str(cycle.DEFAULT_STORE_REPO))
    fin.add_argument("--ledger", default=str(cycle.DEFAULT_LEDGER_PATH))
    fin.add_argument("--queue", default=str(cycle.DEFAULT_QUEUE_PATH))
    fin.add_argument("--flagged", default=None, help="open-set path (default: ledger sibling)")
    fin.add_argument("--message", default=None, help="override the doc-only commit message")
    fin.add_argument("--dangling-before", default=None, help="pre-ruling `cycle store-health` JSON")
    _add_lock_args(fin)
    fin.set_defaults(func=_cmd_finalize)

    hlt = actions.add_parser("store-health", help="dangling-link queue + store size vs ceiling (JSON)")
    hlt.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    hlt.add_argument("--store-repo", default=str(cycle.DEFAULT_STORE_REPO))
    hlt.add_argument("--limit", type=int, default=store_health.DEFAULT_QUEUE_LIMIT)
    hlt.add_argument("--today", default=None, help="YYYY-MM-DD stamp (default: today)")
    hlt.set_defaults(func=_cmd_store_health)

    drn = actions.add_parser("drain", help="approve/clear held items + rebuild review surface (JSON)")
    drn.add_argument("--key", action="append", help="drain only this hold key (repeatable; default: all)")
    drn.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    drn.add_argument("--store-repo", default=str(cycle.DEFAULT_STORE_REPO))
    drn.add_argument(
        "--flagged",
        default=str(cycle.DEFAULT_LEDGER_PATH.parent / cycle.FLAGGED_FILENAME),
        help="open-set path (default: ledger sibling)",
    )
    drn.add_argument("--no-commit", action="store_true", help="rebuild the surface but do not commit")
    _add_lock_args(drn)
    drn.set_defaults(func=_cmd_drain)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oversteward dream")
    sub = parser.add_subparsers(dest="group", required=True)
    _add_transcripts_subparser(sub)
    _add_cycle_subparser(sub)
    _add_supersede_subparser(sub)
    _add_roadmap_subparser(sub)
    _add_promotion_subparser(sub)
    _add_kaizen_subparser(sub)
    _add_correction_subparser(sub)
    return parser


def main(argv: list[str], correction_sources: correction.Sources | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.correction_sources = correction_sources
    projects_root = getattr(args, "projects_root", None)
    args.projects_root = default_projects_root() if projects_root is None else Path(projects_root)
    try:
        return args.func(args)
    except runlock.Locked as exc:
        print(f"dream: skipped — {exc}", file=sys.stderr)
        return 3
    except runlock.LockUnreadable as exc:
        print(f"dream: {exc}", file=sys.stderr)
        return 2
    except StoreUnreadable as exc:
        print(f"dream: store unreadable — {exc}", file=sys.stderr)
        return 2
    except correction.WorklistUnreadable as exc:
        print(f"dream: correction worklist could not look — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
