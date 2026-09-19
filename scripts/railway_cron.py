#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — provision a Railway cron service cloned from a sibling service, plus its own variables.
# ABOUTME: Thin: parse flags into a CronSpec, call the provisioning service, print the redacted plan, map exit codes.

"""Provision a Railway cron service the way the existing ones are shaped.

Every AG cron (``submit_seo_urls``, ``render_sitemaps``, ``daily_lifecycle``…)
is the same repo and branch, the same shared-variable references,
``restartPolicyType: NEVER``, a start command and a schedule. This tool clones
that shape from a sibling that already runs and lays the new cron's own
command, schedule and variables over it — so a cron is never hand-built in
the dashboard with a variable forgotten.

A dry run is the default and touches nothing. ``--apply`` creates the service,
commits the config, then re-reads it and refuses to report success unless the
schedule and every variable name are there.

``--var`` is for non-secret values (a site URL, a path): its value is on this
tool's own command line, where shell history and ``ps`` can read it. A secret
goes through ``--var-file``, which reads the file in-process. Neither value
appears in the preview (a literal is shown only as a length), and the patch
travels to Railway on stdin.

Usage:
    scripts/railway_cron.py --project <id> --environment production \\
        --name monitor_indexation --like submit_seo_urls \\
        --start-command 'python manage.py monitor_indexation' --schedule '0 4 * * 1' \\
        --var GSC_SITE_URL=sc-domain:aigranthelper.com \\
        --var-file GSC_CREDENTIALS_JSON=~/.config/exchequer/ga4-the-almoner.json \\
        --seal GSC_CREDENTIALS_JSON [--apply]

Exit codes: 0 planned or applied; 1 Railway could not be read or the read-back
disagreed; 2 the spec cannot be planned (name clash, missing sibling, bad flag).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from oversteward.railway_cron.client import RailwayUnavailableError
from oversteward.railway_cron.plan import CronSpec, PlanError
from oversteward.railway_cron.provision import VerifyError, provision

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def _split_assignment(text: str) -> tuple[str, str]:
    """``NAME=value`` → (NAME, value); the value may itself contain ``=``."""
    name, sep, value = text.partition("=")
    if not sep or not name:
        raise PlanError(f"expected NAME=value, got {text!r}")
    return name, value


def spec_from_args(args: argparse.Namespace) -> CronSpec:
    """Turn the parsed flags into a CronSpec, reading ``--var-file`` contents in-process."""
    variables: dict[str, str] = {}
    for assignment in args.var:
        name, value = _split_assignment(assignment)
        variables[name] = value
    for assignment in args.var_file:
        name, path = _split_assignment(assignment)
        file = Path(path).expanduser()
        if not file.is_file():
            raise PlanError(f"--var-file {name}: no such file {file}")
        variables[name] = file.read_text(encoding="utf-8")
    return CronSpec(
        name=args.name,
        like=args.like,
        start_command=args.start_command,
        schedule=args.schedule,
        variables=variables,
        sealed=frozenset(args.seal),
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="Railway project id")
    parser.add_argument("--environment", required=True, help="environment name, e.g. production")
    parser.add_argument("--name", required=True, help="the new cron service's name")
    parser.add_argument("--like", required=True, help="an existing cron service to clone config from")
    parser.add_argument("--start-command", required=True)
    parser.add_argument("--schedule", required=True, help="crontab expression, UTC")
    parser.add_argument("--var", action="append", default=[], metavar="NAME=value")
    parser.add_argument("--var-file", action="append", default=[], metavar="NAME=path")
    parser.add_argument("--seal", action="append", default=[], metavar="NAME", help="mark a variable sealed")
    parser.add_argument("--apply", action="store_true", help="create and commit; default is a dry run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        spec = spec_from_args(args)
        report = provision(spec, project_id=args.project, environment=args.environment, apply=args.apply)
    except PlanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    except (RailwayUnavailableError, VerifyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    print(report)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
