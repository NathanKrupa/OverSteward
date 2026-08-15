# ABOUTME: Value objects shared by the Sentry connector, the triage service, and the renderer.
# ABOUTME: Frozen dataclasses only — no I/O, no wire parsing, no environment reads, no rules.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SentryProject:
    """One project in the Sentry organization.

    Projects are always *enumerated* rather than hardcoded: GS#2187 renames the
    `python` project to `grantspider`, and enumeration makes that a no-op here.
    """

    slug: str
    name: str


@dataclass(frozen=True)
class SentryIssue:
    """One unresolved Sentry issue — the unit of triage.

    ``short_id`` (e.g. ``AIGRANTHELPER-4F``) is the human-facing, stable handle
    and is what the ledger keys on; ``id`` is the numeric handle the write API
    needs.
    """

    id: str
    short_id: str
    project: str
    title: str
    first_seen: str
    permalink: str = ""
    count: int = 0
