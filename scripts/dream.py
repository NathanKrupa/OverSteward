# ABOUTME: Thin CLI for the dream cycle — transcript reader plus the convergent runner's batch steps.
# ABOUTME: Parses args, calls the oversteward.dream services, formats JSON. No business logic here.

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from oversteward.dream import cycle, roadmap
from oversteward.dream.consolidate import MemoryStore, commit_store
from oversteward.dream.extract import CandidateFact
from oversteward.dream.ledger import ProcessedLedger
from oversteward.dream.transcripts import (
    TranscriptMeta,
    default_projects_root,
    enumerate_transcripts,
    find_transcript,
    parse_transcript,
)


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
        ),
    )
    return _emit(
        {
            "committed": result.commit.committed,
            "message": result.commit.message,
            "index_path": str(result.index_path),
            "review_path": str(result.review_path),
            "recorded": result.recorded,
            "queue_drained": result.queue_drained,
            "open_flagged": result.open_flagged,
        }
    )


def _cmd_drain(args: argparse.Namespace) -> int:
    store = MemoryStore(Path(args.store))
    flagged_store = cycle.FlaggedStore(Path(args.flagged))
    keys = args.key or None
    result = cycle.drain_flagged(store, flagged_store, keys=keys)
    if not args.no_commit and result.drained:
        message = f"dream: drain {result.drained} reviewed hold(s) {cycle.SKIP_CI_MARKER}"
        commit_store(Path(args.store_repo), [result.review_path], message)
    return _emit(
        {
            "drained": result.drained,
            "remaining": result.remaining,
            "review_path": str(result.review_path),
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


def _add_transcripts_subparser(sub: argparse._SubParsersAction) -> None:
    transcripts = sub.add_parser("transcripts", help="inspect session transcripts")
    actions = transcripts.add_subparsers(dest="action", required=True)
    list_p = actions.add_parser("list", help="enumerate discovered transcripts")
    list_p.add_argument("--repo", help="filter to one inferred repo")
    list_p.set_defaults(func=_cmd_list)
    show_p = actions.add_parser("show", help="render one transcript as role-tagged text")
    show_p.add_argument("session_id")
    show_p.set_defaults(func=_cmd_show)


def _add_cycle_subparser(sub: argparse._SubParsersAction) -> None:
    grp = sub.add_parser("cycle", help="the convergent dream-cycle batch steps")
    actions = grp.add_subparsers(dest="action", required=True)

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
    app.set_defaults(func=_cmd_apply)

    fin = actions.add_parser("finalize", help="index + review + commit + ledger (JSON)")
    fin.add_argument("--results", required=True, help="merged flagged/written/transcripts JSON")
    fin.add_argument("--store", default=str(cycle.DEFAULT_STORE_PATH))
    fin.add_argument("--store-repo", default=str(cycle.DEFAULT_STORE_REPO))
    fin.add_argument("--ledger", default=str(cycle.DEFAULT_LEDGER_PATH))
    fin.add_argument("--queue", default=str(cycle.DEFAULT_QUEUE_PATH))
    fin.add_argument("--flagged", default=None, help="open-set path (default: ledger sibling)")
    fin.add_argument("--message", default=None, help="override the doc-only commit message")
    fin.set_defaults(func=_cmd_finalize)

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
    drn.set_defaults(func=_cmd_drain)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oversteward dream")
    sub = parser.add_subparsers(dest="group", required=True)
    _add_transcripts_subparser(sub)
    _add_cycle_subparser(sub)
    _add_roadmap_subparser(sub)
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    projects_root = getattr(args, "projects_root", None)
    args.projects_root = default_projects_root() if projects_root is None else Path(projects_root)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
