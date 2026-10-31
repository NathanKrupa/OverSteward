#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the estate capability map — validate, locations, coverage, render, check.
# ABOUTME: Thin: parse arguments, call oversteward.estate_map, print, map the outcome to an exit code.

"""Check and render `estate-map.yaml`, the estate's capability map.

`check` runs validate, locations and coverage in one pass. Exit codes carry
meaning and must not be collapsed:

* **0** — clean: every check looked and found nothing.
* **1** — findings: the map disagrees with itself, the registry, or a tree.
* **2** — could not look: the map, the registry, a checkout, a fetch or a ref
  could not be read, or nothing was claimed to check. Outranks 1, and a crash
  is 2, so no failure to read ever exits like a pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "estate-map.yaml"
DIGEST_PATH = ROOT / "data" / "estate-map-digest.md"
SLICES_DIR = ROOT / "shared" / "references" / "estate-map"
HOME_REPO = "oversteward"
EXIT_COULD_NOT_LOOK = 2
EXIT_FINDINGS = 1


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--map", type=Path, default=MAP_PATH)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--digest", type=Path, default=DIGEST_PATH)
    parser.add_argument("--slices", type=Path, default=SLICES_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("locations")
    coverage = sub.add_parser("coverage")
    coverage.add_argument("--repo", default=None)
    render = sub.add_parser("render")
    render.add_argument("--write", action="store_true")
    sub.add_parser("check")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, git=None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        # Imported here so a broken venv reads as could-not-look with a reason, not a traceback.
        from registry import REGISTRY_PATH, load_registry

        from oversteward.estate_map import checks, model, render
        from oversteward.estate_map.checkouts import TreeReader, checkouts
        from oversteward.sow.runners import GitCommand
    except Exception as exc:  # noqa: BLE001 — a crash must read as could-not-look, never clean
        print(f"COULD NOT LOOK - {type(exc).__name__}: {exc}")
        return EXIT_COULD_NOT_LOOK
    try:
        estate = model.load(args.map)
        registry = load_registry(args.registry or REGISTRY_PATH)
    except model.MapError as exc:
        print(f"FINDING - estate map is malformed: {exc}")
        return EXIT_FINDINGS
    except Exception as exc:  # noqa: BLE001 — an unreadable map or registry is could-not-look
        print(f"COULD NOT LOOK - {type(exc).__name__}: {exc}")
        return EXIT_COULD_NOT_LOOK

    try:
        if args.command == "render":
            return _render(args, estate, render)
        reader = TreeReader(git or GitCommand(), checkouts(registry, home_repo=HOME_REPO, home_root=ROOT))
        outcome = checks.run(args.command, estate, registry, reader, repo=getattr(args, "repo", None))
    except Exception as exc:  # noqa: BLE001 — a crash mid-check is could-not-look, never clean
        print(f"COULD NOT LOOK - {args.command} crashed: {type(exc).__name__}: {exc}")
        return EXIT_COULD_NOT_LOOK
    _print(outcome)
    return outcome.exit_code


def _render(args: argparse.Namespace, estate, render) -> int:
    text = render.digest(estate)
    slices = {repo: render.repo_slice(estate, repo) for repo in render.slice_repos(estate)}
    findings = render.budget_findings(estate, text) + [
        finding
        for repo, body in slices.items()
        for finding in render.slice_budget_findings(estate, repo, body)
    ]
    if args.write:
        _write(args.digest, text)
        args.slices.mkdir(parents=True, exist_ok=True)
        for repo, body in slices.items():
            _write(args.slices / render.slice_name(repo), body)
        present = [p.name for p in args.slices.iterdir() if p.is_file()]
        for name in render.stale_slices(present, estate):
            (args.slices / name).unlink()
            print(f"removed {args.slices / name} (no capability belongs to that repo)")
    else:
        print(text, end="")
    for finding in findings:
        print(f"FINDING - {finding}", file=sys.stderr)
    return EXIT_FINDINGS if findings else 0


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(text.encode('utf-8'))} bytes)")


def _print(outcome) -> None:
    for reason in outcome.could_not_look:
        print(f"COULD NOT LOOK - {reason}")
    for finding in outcome.findings:
        print(f"FINDING - {finding}")
    for note in outcome.notes:
        print(note)
    verdict = {0: "clean", 1: f"{len(outcome.findings)} findings", 2: "could not look"}
    print(f"estate-map: {verdict[outcome.exit_code]}")


if __name__ == "__main__":
    sys.exit(main())
