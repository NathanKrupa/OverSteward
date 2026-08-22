# ABOUTME: Fixture envelopes captured from aigranthelper's ops producer, plus an in-memory fake seam.
# ABOUTME: No network, no token, no environment reads — the seam is the client's three methods.

"""The producer's wire shapes, transcribed from ``apps/ops`` on AG ``staging``.

Every envelope here mirrors what ``views_internal._envelope`` /
``_verdict_envelope`` build and what ``apps/feedback/queues.py`` serializes, so
a drift in the real producer shows up as these fixtures disagreeing with it
rather than as a consumer that quietly misreads a new shape.
"""

from __future__ import annotations

from oversteward.ag_ops.client import AgOpsConfigError, AgOpsNotFoundError, AgOpsUnavailableError

CONTRACT_VERSION = 1
BASE_URL = "https://ag.test"

FEEDBACK_QUEUE = "feedback_queue"
CORRECTIONS_QUEUE = "corrections_queue"
KPI_OVERVIEW = "kpi_overview"

FEEDBACK_ID = "1f4a3c2e-0000-4000-8000-000000000001"
CORRECTION_ID = "1f4a3c2e-0000-4000-8000-000000000002"

UNCONFIGURED_MESSAGE = "ops reports endpoint not configured"
DEAD_SOURCE = "feedback.Feedback"

MANIFEST_ENTRIES = [
    {"name": FEEDBACK_QUEUE, "description": "Untriaged in-app feedback, oldest first."},
    {"name": CORRECTIONS_QUEUE, "description": "Untriaged visitor-reported data corrections."},
    {"name": KPI_OVERVIEW, "description": "Platform overview KPIs."},
]


def manifest(entries=None) -> dict:
    """The manifest envelope: the contract version and every registered report."""
    return {
        "contract_version": CONTRACT_VERSION,
        "reports": MANIFEST_ENTRIES if entries is None else entries,
    }


def queue_envelope(name: str, rows: list[dict], *, scanned: int | None = None, complete: bool = True) -> dict:
    """A paged report envelope — ``items`` plus what the page was drawn from."""
    return {
        "report": name,
        "contract_version": CONTRACT_VERSION,
        "complete": complete,
        "scanned": len(rows) if scanned is None else scanned,
        "items": rows,
    }


def computed_envelope(name: str, body: dict) -> dict:
    """A computed report envelope — a ``body`` rather than a row list."""
    return {
        "report": name,
        "contract_version": CONTRACT_VERSION,
        "complete": True,
        "scanned": len(body),
        "body": body,
    }


def feedback_row(item_id: str = FEEDBACK_ID) -> dict:
    """One untriaged feedback submission, as ``_serialize_feedback`` emits it."""
    return {
        "id": item_id,
        "created_at": "2026-08-20T14:03:00+00:00",
        "subject": "Deadline sort is backwards",
        "body": "The deadline column sorts oldest first.",
        "category": "bug",
        "status": "open",
        "page_url": "https://www.aigranthelper.com/grants/",
        "from_beta_org": True,
        "organization_id": "1f4a3c2e-0000-4000-8000-00000000000a",
    }


def correction_row(item_id: str = CORRECTION_ID) -> dict:
    """One untriaged visitor-reported correction."""
    return {
        "id": item_id,
        "created_at": "2026-08-20T15:10:00+00:00",
        "field_name": "website",
        "status": "open",
        "page_url": "https://www.aigranthelper.com/foundations/x/",
    }


def verdict_envelope(results: list[dict]) -> dict:
    """The verdicts envelope: the contract, the counts, and every per-item answer."""
    recorded = sum(1 for result in results if result.get("ok"))
    return {
        "contract_version": CONTRACT_VERSION,
        "recorded": recorded,
        "failed": len(results) - recorded,
        "results": results,
    }


def recorded_result(kind: str, item_id: str, status: str) -> dict:
    """The per-item shape a landed verdict answers with."""
    return {
        "kind": kind,
        "id": item_id,
        "requested_status": status,
        "ok": True,
        "outcome": "recorded",
        "status": status,
    }


def refused_result(kind: str, item_id: str, status: str, detail: str = "not reachable") -> dict:
    """The per-item shape a refusal answers with — no ``status``, a ``detail``."""
    return {
        "kind": kind,
        "id": item_id,
        "requested_status": status,
        "ok": False,
        "outcome": "refused",
        "detail": detail,
    }


class FakeSeam:
    """An in-memory stand-in for AgOpsClient, recording what was asked of it."""

    def __init__(
        self,
        *,
        manifest_envelope: dict | None = None,
        reports: dict[str, dict] | None = None,
        verdicts: dict | None = None,
        fail_with: Exception | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._manifest = manifest_envelope if manifest_envelope is not None else manifest()
        self._reports = reports if reports is not None else default_reports()
        self._verdicts = verdicts
        self._fail_with = fail_with
        self.base_url = base_url
        self.posted: list[list[dict]] = []
        self.requested: list[str] = []

    def manifest(self) -> dict:
        self._check()
        return self._manifest

    def report(self, name: str, *, since: str = "", limit: int = 0) -> dict:
        self._check()
        self.requested.append(name)
        try:
            return self._reports[name]
        except KeyError:
            raise AgOpsNotFoundError(f"AG ops has no such path (HTTP 404) (GET /{name}/): ") from None

    def post_verdicts(self, verdicts: list[dict]) -> dict:
        self._check()
        self.posted.append(verdicts)
        if self._verdicts is not None:
            return self._verdicts
        return verdict_envelope(
            [recorded_result(item["kind"], item["id"], item["status"]) for item in verdicts]
        )

    def _check(self) -> None:
        if self._fail_with is not None:
            raise self._fail_with


def default_reports() -> dict[str, dict]:
    """Every report the default manifest names, all of them empty."""
    return {
        FEEDBACK_QUEUE: queue_envelope(FEEDBACK_QUEUE, []),
        CORRECTIONS_QUEUE: queue_envelope(CORRECTIONS_QUEUE, []),
        KPI_OVERVIEW: computed_envelope(KPI_OVERVIEW, {"users": 42, "orgs": 7}),
    }


def waiting_reports() -> dict[str, dict]:
    """The shape of a real sweep: one feedback row and one correction waiting."""
    reports = default_reports()
    reports[FEEDBACK_QUEUE] = queue_envelope(FEEDBACK_QUEUE, [feedback_row()])
    reports[CORRECTIONS_QUEUE] = queue_envelope(CORRECTIONS_QUEUE, [correction_row()])
    return reports


def clean_seam() -> FakeSeam:
    """A reachable seam with every queue drained."""
    return FakeSeam()


def busy_seam() -> FakeSeam:
    """A reachable seam with items awaiting a verdict."""
    return FakeSeam(reports=waiting_reports())


class UnmountedSeam(FakeSeam):
    """A producer whose ``/internal/ops/`` mount is not deployed at all."""

    def manifest(self) -> dict:
        raise AgOpsNotFoundError("AG ops has no such path (HTTP 404) (GET /internal/ops/reports/): ")


def unmounted_seam() -> UnmountedSeam:
    """The consumer pointed at a producer that has not shipped this surface yet."""
    return UnmountedSeam()


def blind_seam() -> FakeSeam:
    """A seam that could not be read — the "could not look" case."""
    return FakeSeam(fail_with=AgOpsUnavailableError(f"AG ops source unreadable (HTTP 503): {DEAD_SOURCE}"))


def unconfigured_seam() -> FakeSeam:
    """A producer that has not been given its token — nothing configured to look."""
    return FakeSeam(fail_with=AgOpsConfigError(f"the producer is not configured (HTTP 503): {UNCONFIGURED_MESSAGE}"))
