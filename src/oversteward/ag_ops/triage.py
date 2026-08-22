# ABOUTME: MIDDLE service for the AG operator seam — sweeps every named report, records bulk verdicts.
# ABOUTME: Owns the contract tripwire: a producer that drifted must fail loudly, never be misread.

"""What the AG ops seam says, and what a session is allowed to say back.

Three rules shape this module:

- **The contract is pinned and checked on every envelope.** The producer stamps
  ``contract_version`` on every response precisely so a consumer can refuse a
  shape it does not understand. A missing key or a foreign major is drift, and
  drift is a red exit naming what moved — never a best-effort read of a body we
  no longer recognise.
- **A measured empty names what it looked at.** A sweep that found nothing
  carries every report's ``scanned`` count with it, because "0 waiting" and
  "we never asked" are different answers and must print differently.
- **The reachable-verdict vocabulary is mirrored here, not guessed.** The
  producer's allowlist is the authority; this copy exists so an unreachable
  verdict is refused before a token is ever spent on it, and so the two
  GrantSpider-only statuses stay visibly out of reach.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import AgOpsConfigError, AgOpsNotFoundError

#: The wire contract this consumer understands. The producer bumps
#: ``CONTRACT_VERSION`` when an envelope key or a report body changes shape, so
#: a foreign major means our reader is looking at something else entirely.
SUPPORTED_CONTRACT_MAJOR = 1

CONTRACT_VERSION_KEY = "contract_version"
REPORTS_KEY = "reports"
ITEMS_KEY = "items"
BODY_KEY = "body"
SCANNED_KEY = "scanned"
COMPLETE_KEY = "complete"
NAME_KEY = "name"
RESULTS_KEY = "results"
RECORDED_KEY = "recorded"
FAILED_KEY = "failed"

#: Envelope keys each surface must carry. Absence is drift, not a default.
MANIFEST_REQUIRED_KEYS = (CONTRACT_VERSION_KEY, REPORTS_KEY)
REPORT_REQUIRED_KEYS = (CONTRACT_VERSION_KEY, "report", COMPLETE_KEY, SCANNED_KEY)
VERDICT_REQUIRED_KEYS = (CONTRACT_VERSION_KEY, RECORDED_KEY, FAILED_KEY, RESULTS_KEY)

#: Separator for the vocabularies a refusal quotes back.
_JOIN = ", "

FEEDBACK = "feedback"
CORRECTION = "correction"

#: The verdicts the write token may set, mirroring ``apps.ops.verdicts``'
#: allowlist. ``applied`` and ``gs_dismissed`` are absent on purpose: they are
#: GrantSpider's acks on a row it has already consumed, reachable only by the GS
#: token, and a session that could set them would mail a submitter by accident.
REACHABLE_STATUSES: dict[str, tuple[str, ...]] = {
    FEEDBACK: ("responded", "closed"),
    CORRECTION: ("reviewed", "rejected"),
}

#: Statuses the producer owns but this token deliberately cannot reach — named
#: so a refusal can say why rather than merely that.
TOKEN_UNREACHABLE_STATUSES = ("applied", "gs_dismissed")


class ContractDriftError(RuntimeError):
    """The producer's envelope is not the shape this consumer is pinned to."""


class VerdictError(ValueError):
    """A verdict this token may not set, or one the producer has no vocabulary for."""


@dataclass(frozen=True)
class ReportResult:
    """One named report as it answered: what it examined, and what it says."""

    name: str
    description: str
    scanned: int
    complete: bool
    items: tuple[dict, ...] | None = None
    body: dict | None = None

    @property
    def is_queue(self) -> bool:
        """True for a row list — a computed body has nothing awaiting a verdict."""
        return self.items is not None

    @property
    def waiting(self) -> int:
        """How many rows this page carries; zero for a computed report."""
        return len(self.items) if self.items is not None else 0


@dataclass(frozen=True)
class SweepResult:
    """Every report the producer offered, in the order it published them."""

    reports: tuple[ReportResult, ...]
    base_url: str

    @property
    def total_waiting(self) -> int:
        """Rows sitting in queue reports across the whole sweep."""
        return sum(report.waiting for report in self.reports)

    @property
    def is_clean(self) -> bool:
        """True when every queue answered empty — a measured nothing, not a silence."""
        return self.total_waiting == 0


@dataclass(frozen=True)
class VerdictRequest:
    """One ruling a session wants recorded."""

    kind: str
    item_id: str
    status: str

    def as_wire(self) -> dict:
        """The per-item shape the producer parses."""
        return {"kind": self.kind, "id": self.item_id, "status": self.status}


@dataclass(frozen=True)
class RecordResult:
    """What the producer did with a batch: its counts, and every per-item answer."""

    recorded: int
    failed: int
    results: tuple[dict, ...]

    @property
    def all_ok(self) -> bool:
        return self.failed == 0


def sweep(client) -> SweepResult:
    """Pull the manifest, then every report it names.

    A 404 on the manifest means the surface is not mounted at all — nothing was
    configured to look, so it is raised as a config error rather than an outage.
    A 404 on a report the manifest just promised is the opposite: the producer
    is up and its registry moved under us, which is drift.
    """
    try:
        manifest = client.manifest()
    except AgOpsNotFoundError as exc:
        raise AgOpsConfigError(
            f"the AG ops reports surface is not mounted at {client.base_url} — {exc}"
        ) from None
    assert_contract(manifest, MANIFEST_REQUIRED_KEYS, "manifest")
    entries = manifest[REPORTS_KEY]
    if not isinstance(entries, list):
        raise ContractDriftError(f"manifest {REPORTS_KEY!r} is a {type(entries).__name__}, expected a list")
    return SweepResult(
        reports=tuple(_pull(client, entry) for entry in entries),
        base_url=client.base_url,
    )


def record(client, requests: list[VerdictRequest]) -> RecordResult:
    """Post a batch of verdicts and return the producer's per-item answers.

    Every request is checked against the reachable allowlist first: an
    unreachable verdict is refused here, before a write token is spent on a call
    the producer would refuse anyway.

    Safe to repeat: the producer's state machines no-op a row already at the
    requested status, so a retried batch answers ``recorded`` for it again
    rather than a conflict.
    """
    if not requests:
        raise VerdictError("no verdicts given — name at least one kind:id:status")
    for request in requests:
        _check_reachable(request)
    envelope = client.post_verdicts([request.as_wire() for request in requests])
    assert_contract(envelope, VERDICT_REQUIRED_KEYS, "verdicts")
    results = envelope[RESULTS_KEY]
    if not isinstance(results, list):
        raise ContractDriftError(f"verdicts {RESULTS_KEY!r} is a {type(results).__name__}, expected a list")
    return RecordResult(
        recorded=int(envelope[RECORDED_KEY]),
        failed=int(envelope[FAILED_KEY]),
        results=tuple(results),
    )


def parse_verdict(spec: str) -> VerdictRequest:
    """One ``kind:id:status`` triple from the command line."""
    parts = spec.split(":")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise VerdictError(f"{spec!r} is not a kind:id:status triple")
    kind, item_id, status = (part.strip() for part in parts)
    return VerdictRequest(kind=kind, item_id=item_id, status=status)


def assert_contract(envelope: dict, required_keys: tuple[str, ...], surface: str) -> None:
    """Refuse an envelope whose shape or version this consumer is not pinned to.

    Named the same way in both failure modes, because a consumer that reports
    "something went wrong" leaves the operator to diff two codebases by hand.
    """
    missing = [key for key in required_keys if key not in envelope]
    if missing:
        raise ContractDriftError(
            f"AG ops {surface} envelope is missing {_JOIN.join(sorted(missing))} — "
            f"the producer's contract moved; re-read apps/ops before trusting this sweep."
        )
    _assert_major(envelope[CONTRACT_VERSION_KEY], surface)


def _assert_major(version, surface: str) -> None:
    """The envelope's major must be the one this consumer was written against."""
    major = _major(version)
    if major != SUPPORTED_CONTRACT_MAJOR:
        raise ContractDriftError(
            f"AG ops {surface} declares contract_version {version!r}; this consumer is pinned "
            f"to major {SUPPORTED_CONTRACT_MAJOR}. Re-read apps/ops and update the pin."
        )


def _major(version) -> int:
    """The major of a contract version, however the producer spelled it."""
    try:
        return int(str(version).split(".")[0])
    except (TypeError, ValueError):
        raise ContractDriftError(f"contract_version {version!r} is not a version number") from None


def _pull(client, entry) -> ReportResult:
    """Fetch one manifest entry's report and check its envelope."""
    if not isinstance(entry, dict) or not entry.get(NAME_KEY):
        raise ContractDriftError(f"manifest entry {entry!r} carries no {NAME_KEY!r}")
    name = str(entry[NAME_KEY])
    try:
        envelope = client.report(name)
    except AgOpsNotFoundError as exc:
        raise ContractDriftError(
            f"the manifest lists {name!r} but the producer answers 404 for it — registry drift ({exc})"
        ) from None
    assert_contract(envelope, REPORT_REQUIRED_KEYS, f"report {name!r}")
    return _result(name, str(entry.get("description", "")), envelope)


def _result(name: str, description: str, envelope: dict) -> ReportResult:
    """One envelope as a report. Exactly one of items/body carries the answer."""
    items = envelope.get(ITEMS_KEY)
    body = envelope.get(BODY_KEY)
    if (items is None) == (body is None):
        raise ContractDriftError(
            f"report {name!r} carries {'both' if items is not None else 'neither'} "
            f"{ITEMS_KEY!r} and {BODY_KEY!r} — expected exactly one."
        )
    return ReportResult(
        name=name,
        description=description,
        scanned=int(envelope[SCANNED_KEY]),
        complete=bool(envelope[COMPLETE_KEY]),
        items=tuple(items) if items is not None else None,
        body=body,
    )


def _check_reachable(request: VerdictRequest) -> None:
    """Refuse a verdict this token may not set, saying which ones it may."""
    reachable = REACHABLE_STATUSES.get(request.kind)
    if reachable is None:
        raise VerdictError(
            f"unknown kind {request.kind!r} — this seam rules on {_JOIN.join(sorted(REACHABLE_STATUSES))}"
        )
    if request.status not in reachable:
        raise VerdictError(
            f"{request.status!r} is not reachable by the ops verdicts token; "
            f"{request.kind} accepts {_JOIN.join(reachable)}"
            f"{_unreachable_note(request.status)}"
        )


def _unreachable_note(status: str) -> str:
    """Why a GrantSpider-owned status is refused, when that is what was asked for."""
    if status not in TOKEN_UNREACHABLE_STATUSES:
        return "."
    return f". {status!r} is GrantSpider's ack and is reachable only by the GS token, by design."
