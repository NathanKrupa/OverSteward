# ABOUTME: grantspider's scripts/ci/ci_red_alert.py is canonical; aigranthelper's is its byte-copy.
# ABOUTME: Compares the two committed blobs on each repo's shipping branch; red on any byte of drift.

"""The ci-red watchdog script must be the same bytes in both repos that run it.

Each repo's ``ci-red-alert`` job runs its own copy of
``scripts/ci/ci_red_alert.py``. GS is fixed first and the file re-copied to AG,
so a drift means one repo's watchdog files issues the other's would not.

The blobs are read from ``origin/<branch>`` through ``dev_family.GitRepo``, as
the refs stand: the test never fetches, so it measures whatever the last
``git fetch`` left. A sibling checkout absent from this machine (CI) skips, with
the reason; a checkout that is present but cannot yield the blob fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from oversteward.dev_family import GitRepo

REPO_ROOT = Path(__file__).resolve().parents[1]
ALERT_SCRIPT = "scripts/ci/ci_red_alert.py"
CANONICAL = "grantspider"
COPY = "aigranthelper"


def _context(context_id: str) -> dict:
    registry = yaml.safe_load((REPO_ROOT / "registry.yaml").read_text(encoding="utf-8"))
    return next(c for c in registry["contexts"] if c.get("id") == context_id)


def _committed_blob(context_id: str) -> bytes:
    ctx = _context(context_id)
    root = Path(ctx["local_path"])
    if not root.is_dir():
        pytest.skip(f"{context_id} checkout absent at {root}; nothing to compare here")
    ref = f"origin/{ctx['branch']}"
    blob = GitRepo(root).blob(ref, ALERT_SCRIPT)
    assert blob is not None, f"{context_id}: no {ALERT_SCRIPT} readable at {ref} in {root}"
    return blob


def assert_same_bytes(canonical: bytes, copy: bytes) -> None:
    if canonical == copy:
        return
    offset = next(
        (i for i, (a, b) in enumerate(zip(canonical, copy, strict=False)) if a != b),
        min(len(canonical), len(copy)),
    )
    raise AssertionError(
        f"{COPY}'s {ALERT_SCRIPT} has drifted from {CANONICAL}'s: first difference at "
        f"byte {offset} ({len(canonical)} vs {len(copy)} bytes). Fix it in {CANONICAL}, "
        f"then re-copy it to {COPY}."
    )


def test_aigranthelper_copy_matches_grantspider_canonical():
    assert_same_bytes(_committed_blob(CANONICAL), _committed_blob(COPY))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda b: b[:-1] + bytes([b[-1] ^ 1]), id="last-byte-flipped"),
        pytest.param(lambda b: bytes([b[0] ^ 1]) + b[1:], id="first-byte-flipped"),
        pytest.param(lambda b: b + b"\n", id="one-byte-appended"),
        pytest.param(lambda b: b[:-1], id="one-byte-dropped"),
    ],
)
def test_a_one_byte_difference_is_red(mutate):
    canonical = b"#!/usr/bin/env python\n# the ci-red alert\nprint('ci red')\n"
    with pytest.raises(AssertionError, match="has drifted"):
        assert_same_bytes(canonical, mutate(canonical))
