#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the design bench — publish static renders to ab.aigranthelper.com, write judge manifests.
# ABOUTME: Thin: parse flags, call the bench services, print URLs or the manifest path, map failures to exit codes.

"""Publish page renders to the non-indexed design bench, and write the manifest that judges them.

``ab.aigranthelper.com`` is a static Cloudflare Pages project where mockup
variants and fixture renders land to be judged by ``scripts/page_judge.py``
(OS#421, Workstream B). Nothing may reach it that Google could index: every
``.html`` must carry the noindex meta, ``_headers`` must set ``X-Robots-Tag:
noindex`` and ``robots.txt`` must disallow everything — checked before a byte
uploads, refused as a whole list.

    scripts/dev/with_test_env.py -- .venv/bin/python scripts/design_bench.py \\
        publish reports/bench/round-1/ --branch round-1

    .venv/bin/python scripts/design_bench.py manifest reports/bench/round-1/ \\
        --base-url https://round-1.ab-aigranthelper.pages.dev \\
        --page-type foundation --pairs all [--facts reports/judge/manifests/facts/round-1.json]

``manifest`` takes a directory (with ``--base-url``) or a text file of URLs,
one per line, and writes ``reports/judge/manifests/<name>.yaml`` in the shape
``example.yaml`` documents — ``--pairs all`` lists every unordered pair, and
the judge runs each in both orders itself.

Credentials come from ``CF_PAGES_API_TOKEN`` and ``CF_ACCOUNT_ID``
(``CF_PAGES_PROJECT`` overrides the project), exported or in the repo-root
``.env`` read in-process.

Exit codes carry meaning and must not be collapsed:

* **0** — published, or the manifest was written.
* **1** — refused (an indexable page, a missing ``_headers`` or ``robots.txt``,
  a manifest that would overwrite one) or the upload failed.
* **2** — nothing was configured to look: no Pages token or account id.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import yaml

from oversteward.bench.config import BenchConfigError, PagesCredentials, credentials_from_env
from oversteward.bench.manifest import DEFAULT_RUBRIC, build_manifest, page_urls, urls_from_listing
from oversteward.bench.publish import RefusedError, Uploader, publish
from oversteward.bench.wrangler import UploadError, deploy
from oversteward.judge.models import DEFAULT_SAMPLES, Rubric

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFESTS_DIR = REPO_ROOT / "reports" / "judge" / "manifests"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_MISCONFIGURED = 2

#: Builds the uploader around the credentials; the wrangler connector in production, a fake in tests.
UploaderFactory = Callable[[PagesCredentials], Uploader]


def _wrangler_uploader(credentials: PagesCredentials) -> Uploader:
    return partial(deploy, credentials=credentials)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="design_bench.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    publish_cmd = commands.add_parser("publish", help="upload a directory of renders to the bench")
    publish_cmd.add_argument("directory", type=Path, help="the static renders, with _headers and robots.txt")
    publish_cmd.add_argument("--branch", help="Pages branch to deploy to (default: the directory's name, slugged)")

    manifest_cmd = commands.add_parser("manifest", help="write a page_judge manifest for published variants")
    manifest_cmd.add_argument("source", type=Path, help="a published directory, or a file of URLs one per line")
    manifest_cmd.add_argument("--page-type", required=True, help="the page_types key, e.g. foundation")
    manifest_cmd.add_argument("--pairs", choices=("all", "none"), default="none", help="pair every variant, or none")
    manifest_cmd.add_argument("--base-url", help="where the directory was published (required for a directory)")
    manifest_cmd.add_argument("--rubric", choices=[r.value for r in Rubric], default=DEFAULT_RUBRIC)
    manifest_cmd.add_argument("--samples", type=int, default=DEFAULT_SAMPLES, help="per ordering")
    manifest_cmd.add_argument("--facts", type=Path, help="JSON ground truth the variants were rendered from")
    manifest_cmd.add_argument("--name", help="manifest name and file stem (default: bench-<page-type>-<date>)")
    manifest_cmd.add_argument("--out-dir", type=Path, default=MANIFESTS_DIR, help="where the YAML is written")
    return parser


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "bench"


def _publish(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    dotenv_path: Path | None,
    uploader: UploaderFactory,
) -> int:
    try:
        credentials = credentials_from_env(env, dotenv_path)
    except BenchConfigError as exc:
        return _fail(str(exc), EXIT_MISCONFIGURED)
    branch = args.branch or _slug(args.directory.name)
    try:
        report = publish(args.directory, branch=branch, upload=uploader(credentials))
    except (RefusedError, UploadError, NotADirectoryError) as exc:
        return _fail(str(exc), EXIT_REFUSED)
    print(f"published {args.directory} to {credentials.project} on branch {branch}")
    print(f"deployment: {report.deployment.url}")
    if report.deployment.alias:
        print(f"alias:      {report.deployment.alias}")
    for url in report.page_urls:
        print(f"  {url}")
    return EXIT_OK


def _manifest_urls(args: argparse.Namespace) -> tuple[str, ...]:
    if args.source.is_dir():
        if not args.base_url:
            raise ValueError(f"{args.source} is a directory; --base-url names where it was published")
        return page_urls(args.base_url, args.source)
    return urls_from_listing(args.source.read_text(encoding="utf-8"))


def _facts_reference(facts: Path | None, out_dir: Path) -> str | None:
    """The ground-truth path as the manifest will carry it — relative to the manifest when it can be."""
    if facts is None:
        return None
    if not facts.is_file():
        raise ValueError(f"--facts {facts}: no such file")
    return os.path.relpath(facts.resolve(), out_dir.resolve())


def _manifest(args: argparse.Namespace) -> int:
    name = args.name or f"bench-{_slug(args.page_type)}-{datetime.now(UTC):%Y-%m-%d}"
    target = args.out_dir / f"{name}.yaml"
    if target.exists():
        return _fail(f"{target} already exists; pass --name to write a different manifest", EXIT_REFUSED)
    try:
        data = build_manifest(
            name=name,
            page_type=args.page_type,
            urls=_manifest_urls(args),
            pairs=args.pairs == "all",
            rubric=args.rubric,
            samples=args.samples,
            facts=_facts_reference(args.facts, args.out_dir),
        )
    except (ValueError, OSError) as exc:
        return _fail(str(exc), EXIT_REFUSED)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {target} ({len(data['page_types'][args.page_type])} URLs, {len(data['pairs'])} pairs)")
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    uploader: UploaderFactory = _wrangler_uploader,
) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "publish":
        return _publish(args, env=env, dotenv_path=dotenv_path, uploader=uploader)
    return _manifest(args)


if __name__ == "__main__":
    sys.exit(main())
