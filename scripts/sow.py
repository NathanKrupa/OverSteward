#!/usr/bin/env python3
# ABOUTME: OUTER entrypoint for sow — deploys the canonical shared/scripts/dev/ family as sync PRs.
# ABOUTME: Thin: parse args, hold the lock, call the service, print, map failures to distinct exit codes.

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from oversteward.dev_family import canonical_family
from oversteward.gather import default_paths
from oversteward.sow.apply import Runners, apply_plan, deploy_shared
from oversteward.sow.canon import CanonHistory, canonical_blobs, observe_registry
from oversteward.sow.plan import (
    EXIT_COULD_NOT_LOOK,
    EXIT_MEASURED,
    exit_code,
    gate_lock,
    plan,
)
from oversteward.sow.render import render_plan, render_report
from oversteward.sow.runners import GhCommand, GitCommand, RuffCommand, SowError, SowLock

LOCK_NAME = ".sow.lock"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy the canonical shared/scripts/dev/ family to every managed repo."
    )
    parser.add_argument("--apply", action="store_true", help="Write. Without it, sow measures only.")
    parser.add_argument("--verify", action="store_true", help="Run the target's make verify first.")
    parser.add_argument("--only", nargs="*", default=[], metavar="ID", help="Limit to these ids.")
    parser.add_argument("--deploy-shared", action="store_true", help="Mirror shared/ to both homes.")
    parser.add_argument("--no-fetch", action="store_true", help="Trust the local remote refs.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    return parser


def _fail(message: str) -> int:
    print(f"ERROR: could not look — {message}", file=sys.stderr)
    return EXIT_COULD_NOT_LOOK


def _deploy_shared(paths: dict, apply_requested: bool) -> int:
    if not apply_requested:
        print("dry run — --deploy-shared writes nothing without --apply")
        return EXIT_MEASURED
    results = deploy_shared(paths["canonical_shared"], list(paths["deploy_targets"].values()))
    for result in results:
        state = "unreachable" if not result.reachable else "ok"
        print(
            f"{result.target}: {state} — {result.copied} copied, "
            f"{result.unchanged} unchanged, {result.skipped} skipped"
        )
    return EXIT_MEASURED if all(r.reachable for r in results) else EXIT_COULD_NOT_LOOK


def _build_plan(paths: dict, args: argparse.Namespace, registry: dict):
    git = GitCommand()
    members = sorted(canonical_family(paths["canonical_shared"]))
    canonical = canonical_blobs(paths["repo_root"], paths["canonical_shared"], git)
    history = CanonHistory(paths["repo_root"], git).history(members)
    observations, without_checkout = observe_registry(
        registry, members, git, GhCommand(), only=args.only, fetch=not args.no_fetch
    )
    return plan(
        observations,
        canonical,
        history,
        date=datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        apply_requested=args.apply,
        registered_ids=[ctx.get("id") for ctx in registry.get("contexts", [])],
        requested_ids=args.only,
        without_checkout=without_checkout,
    )


def _run(paths: dict, args: argparse.Namespace, registry: dict) -> int:
    sow_plan = _build_plan(paths, args, registry)
    report = apply_plan(
        sow_plan,
        canonical_shared=paths["canonical_shared"],
        runners=Runners(git=GitCommand(), gh=GhCommand(), ruff=RuffCommand()),
        reports_dir=paths["repo_root"] / "reports" / "sow",
        now=datetime.now(tz=UTC),
        verify=args.verify,
    )
    if args.json:
        json.dump(asdict(report), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_plan(sow_plan), end="")
        if report.applied:
            print(render_report(report), end="")
    return exit_code(report)


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    paths = default_paths()
    if args.deploy_shared:
        return _deploy_shared(paths, args.apply)
    registry_path = Path(paths["repo_root"]) / "registry.yaml"
    if not registry_path.is_file():
        return _fail(f"no registry at {registry_path}")
    if not canonical_family(paths["canonical_shared"]):
        return _fail(f"no canonical family under {paths['canonical_shared']}/scripts/dev")
    lock = SowLock(Path(paths["repo_root"]) / LOCK_NAME)
    if not lock.acquire():
        return _fail(gate_lock(False, str(Path(paths["repo_root"]) / LOCK_NAME)).detail)
    try:
        return _run(paths, args, yaml.safe_load(registry_path.read_text(encoding="utf-8")))
    except SowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
