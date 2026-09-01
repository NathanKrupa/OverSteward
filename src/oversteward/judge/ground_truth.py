# ABOUTME: INNER — reads the facts a manifest names, from an inline mapping or a JSON fixture on disk.
# ABOUTME: One external system: the filesystem. A path that does not exist is a read error, never empty facts.

"""Resolve a manifest's ``ground_truth`` block into facts the judge can be handed.

An entry is either the facts themselves, written inline in the manifest, or a
path to the JSON fixture holding them. Relative paths resolve against the
manifest's own directory, so a manifest and its fixtures travel together.

The whole block is resolved **before the first model call**. An operator who
mistyped a fixture path then pays an exit code, not a round of billed calls
judged against facts that were never loaded — and a missing file can never be
mistaken for an empty fact set, which would silently mark every claim on the
page unsupported.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from oversteward.judge.models import JudgeReadError

#: Every complaint below names the URL whose facts could not be read.
_FOR = "the ground truth for"


def resolve_ground_truth(
    entries: Mapping[str, Mapping | str],
    base_dir: Path,
) -> dict[str, Mapping]:
    """Read every entry up front, so a bad path fails before any call is issued."""
    return {url: _facts(url, entry, base_dir) for url, entry in entries.items()}


def _facts(url: str, entry: Mapping | str, base_dir: Path) -> Mapping:
    """One entry's facts — inline as written, or parsed from the fixture it names."""
    if isinstance(entry, Mapping):
        return dict(entry)
    path = Path(str(entry)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        raise JudgeReadError(f"{_FOR} {url} names {path}, which does not exist — no call was issued")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JudgeReadError(f"{_FOR} {url} at {path} could not be read: {exc}") from exc
    if not isinstance(data, Mapping):
        raise JudgeReadError(
            f"{_FOR} {url} at {path} is a {type(data).__name__}, not a JSON object"
        )
    return data


__all__ = ["resolve_ground_truth"]
