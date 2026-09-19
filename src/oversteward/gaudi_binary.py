# ABOUTME: Resolves the gaudi beside the running interpreter — never a stranger found on PATH.
# ABOUTME: A gate that resolves someone else's binary is measuring someone else's opinion.

"""Where `gaudi` is, for anything in this estate that gates on it (OS#424).

`shutil.which("gaudi")` finds `~/.local/bin/gaudi` — a *different* installation
on a different interpreter. In aigranthelper that one runs Python 3.11, whose
parser cannot read PEP 758 `except A, B:`; it skipped roughly three dozen files
including `billing/services.py` and `accounts/magic_link.py`, exiting 0 with
output indistinguishable from a clean run. Those files had a false-green local
error gate for months. GrantSpider PR#2234 fixed the same class by resolving the
sibling of `sys.executable`, and this is that resolution, shared.

The interpreter path is used **as given**, never `resolve()`d: a venv's
`bin/python` is a symlink to a system interpreter, so resolving it walks out of
the venv into `/usr/bin` and finds no gaudi at all — which fails the other way,
silently reporting the tool absent on every real venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Windows carries the `.exe`; the estate is WSL2 but the byte-copy travels.
GAUDI_NAMES = ("gaudi", "gaudi.exe")


def gaudi_binary(executable: str | None = None) -> Path | None:
    """The gaudi installed beside ``executable``, or None when there is none.

    Returning None rather than falling back to PATH is deliberate: "the venv has
    no gaudi" is a fact a caller must be able to act on loudly, and a fallback
    would restore exactly the silent wrong-binary resolution this exists to
    remove.
    """
    bindir = Path(executable or sys.executable).parent
    for name in GAUDI_NAMES:
        candidate = bindir / name
        if candidate.is_file():
            return candidate
    return None
