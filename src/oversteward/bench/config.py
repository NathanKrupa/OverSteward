# ABOUTME: The one place the bench reads its Cloudflare Pages credentials from the environment (ARCH-020).
# ABOUTME: A factory only — the connector takes the credentials as a parameter, and the token never reprs.

"""Credentials for the Pages bench.

An exported value wins; the repo-root ``.env`` is the fallback, parsed
in-process and never shell-sourced (credential-hygiene.md). A missing token or
account id is the "not configured to look" case — exit 2 at the edge, never a
stack trace.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# Repo root: src/oversteward/bench/config.py -> up three parents.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DOTENV_PATH = _REPO_ROOT / ".env"

TOKEN_VAR = "CF_PAGES_API_TOKEN"
ACCOUNT_VAR = "CF_ACCOUNT_ID"
PROJECT_VAR = "CF_PAGES_PROJECT"
#: The Pages project behind ab.aigranthelper.com (OS#421, operator step).
DEFAULT_PROJECT = "ab-aigranthelper"


class BenchConfigError(RuntimeError):
    """No Pages credentials are configured — the "could not look" case, exit 2 at the edge."""


@dataclass(frozen=True, slots=True)
class PagesCredentials:
    """What the uploader needs to speak to one Pages project."""

    token: str = field(repr=False)
    account_id: str
    project: str = DEFAULT_PROJECT


def credentials_from_env(
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> PagesCredentials:
    """Read the Pages token, account id and project name (ARCH-020).

    This is the only place that reads *configuration* from ``os.environ``
    (the connector inherits the process environment into wrangler's, for
    ``PATH`` and ``HOME``, and reads nothing from it). Matches
    ``load_dotenv``'s ``override=False`` default: an exported value wins over
    the file.
    """
    source = env if env is not None else os.environ
    from_file = _dotenv_values(dotenv_path)
    token = source.get(TOKEN_VAR) or from_file.get(TOKEN_VAR)
    account_id = source.get(ACCOUNT_VAR) or from_file.get(ACCOUNT_VAR)
    missing = [name for name, value in ((TOKEN_VAR, token), (ACCOUNT_VAR, account_id)) if not value]
    if missing:
        raise BenchConfigError(
            f"{', '.join(missing)} not set — publishing to the design bench needs a Cloudflare Pages "
            "token (Account · Cloudflare Pages · Edit) and the account id. Export them, or add them to "
            "the OverSteward repo-root .env and run through scripts/dev/with_test_env.py."
        )
    project = source.get(PROJECT_VAR) or from_file.get(PROJECT_VAR) or DEFAULT_PROJECT
    return PagesCredentials(token=str(token), account_id=str(account_id), project=project)


def _dotenv_values(dotenv_path: Path | None) -> Mapping[str, str]:
    """The repo-root ``.env`` parsed without mutating the process environment; empty if absent."""
    path = dotenv_path if dotenv_path is not None else _DEFAULT_DOTENV_PATH
    if not path.is_file():
        return {}
    from dotenv import dotenv_values  # noqa: PLC0415 — optional dep, imported lazily

    return {key: value for key, value in dotenv_values(path).items() if value}


__all__ = [
    "ACCOUNT_VAR",
    "DEFAULT_PROJECT",
    "PROJECT_VAR",
    "TOKEN_VAR",
    "BenchConfigError",
    "PagesCredentials",
    "credentials_from_env",
]
