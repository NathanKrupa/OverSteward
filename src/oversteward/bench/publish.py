# ABOUTME: MIDDLE layer — orchestrates one publish to the bench: check the directory, refuse or upload, report URLs.
# ABOUTME: The uploader is injected so the sequence is testable; a refusal happens before it is ever called.

"""Publish a directory of static renders to the design bench.

The order is the control: every check in :mod:`oversteward.bench.checks` runs
first, and one failure means the uploader is never called — a page that
Google could index must not exist on the bench even for the seconds a
rollback would take.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from oversteward.bench.checks import refusals
from oversteward.bench.manifest import page_urls
from oversteward.bench.wrangler import Deployment, UploadError

#: ``(directory, branch) -> where it landed``; the wrangler connector, bound to its credentials, in production.
Uploader = Callable[[Path, str], Deployment]


class RefusedError(RuntimeError):
    """The directory may not be published; ``reasons`` names every problem."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__("refusing to publish:\n" + "\n".join(f"  - {reason}" for reason in reasons))


@dataclass(frozen=True, slots=True)
class PublishReport:
    """What was published and where each page can be read."""

    directory: Path
    branch: str
    deployment: Deployment
    page_urls: tuple[str, ...]


def publish(directory: Path, *, branch: str, upload: Uploader) -> PublishReport:
    """Check ``directory``, then upload it to ``branch``; refuse before uploading on any problem."""
    reasons = refusals(directory)
    if reasons:
        raise RefusedError(reasons)
    deployment = upload(directory, branch)
    if not deployment.url:
        raise UploadError("the uploader reported no deployment URL")
    base = deployment.alias or deployment.url
    return PublishReport(
        directory=directory, branch=branch, deployment=deployment, page_urls=page_urls(base, directory),
    )


__all__ = ["PublishReport", "RefusedError", "Uploader", "publish"]
