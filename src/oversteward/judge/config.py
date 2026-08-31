# ABOUTME: The one place the judge reads its API key from the environment (ARCH-020).
# ABOUTME: A factory only — GeminiJudge itself takes the key as a parameter.

from __future__ import annotations

import os
from pathlib import Path

from oversteward.judge.gemini import DEFAULT_MODEL, GeminiJudge

# Repo root: src/oversteward/judge/config.py -> up three parents.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DOTENV_PATH = _REPO_ROOT / ".env"

GEMINI_KEY_VAR = "GEMINI_API_KEY"
#: Google's own SDKs read this name, so a key already exported for another tool works.
FALLBACK_KEY_VAR = "GOOGLE_API_KEY"


class JudgeConfigError(RuntimeError):
    """No API key is configured — the "could not look" case, exit 2 at the edge."""


def resolve_api_key(
    env: dict[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> str:
    """Read the Gemini API key from the environment (ARCH-020).

    This is the only place that touches ``os.environ``. An exported value wins;
    the repo-root ``.env`` is the fallback, parsed in-process and never
    shell-sourced (credential-hygiene.md). Matches ``load_dotenv``'s
    ``override=False`` default.
    """
    source = env if env is not None else os.environ
    key = (
        source.get(GEMINI_KEY_VAR)
        or source.get(FALLBACK_KEY_VAR)
        or _key_from_dotenv(dotenv_path)
    )
    if not key:
        raise JudgeConfigError(
            f"{GEMINI_KEY_VAR} is not set — the page-judge pass needs a Gemini API key. "
            f"Export it (or {FALLBACK_KEY_VAR}), or add it to the OverSteward repo-root .env "
            "and run through scripts/dev/with_test_env.py."
        )
    return key


def judge_from_env(
    env: dict[str, str] | None = None,
    dotenv_path: Path | None = None,
    *,
    model: str = DEFAULT_MODEL,
) -> GeminiJudge:
    """Factory: build the judge around the configured key."""
    return GeminiJudge(resolve_api_key(env, dotenv_path), model=model)


def _key_from_dotenv(dotenv_path: Path | None) -> str | None:
    """The key from a ``.env`` file, or None if unavailable.

    ``dotenv_values`` parses without mutating the process environment; the
    exported-wins ordering is enforced by the caller.
    """
    path = dotenv_path if dotenv_path is not None else _DEFAULT_DOTENV_PATH
    if not path.is_file():
        return None
    from dotenv import dotenv_values  # noqa: PLC0415 — optional dep, imported lazily

    values = dotenv_values(path)
    return values.get(GEMINI_KEY_VAR) or values.get(FALLBACK_KEY_VAR) or None


__all__ = [
    "FALLBACK_KEY_VAR",
    "GEMINI_KEY_VAR",
    "JudgeConfigError",
    "judge_from_env",
    "resolve_api_key",
]
