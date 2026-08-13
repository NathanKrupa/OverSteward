# ABOUTME: Tests for the liveness classification — what a Railway state means.
# ABOUTME: The judgement lives in models, so this is where it is pinned.

from __future__ import annotations

import pytest

from oversteward.liveness.models import Health, LivenessReport, ServiceState

_PROJECT = "grantspider"


def _state(status: str, *, stopped: bool = False, name: str = "svc") -> ServiceState:
    return ServiceState(project=_PROJECT, name=name, status=status, stopped=stopped)


class TestHealthClassification:
    def test_running_service_is_running(self):
        assert _state("SUCCESS").health is Health.RUNNING

    def test_succeeded_and_stopped_is_a_completed_one_shot(self):
        # A scheduled job legitimately ends SUCCESS and stopped — not a finding.
        assert _state("SUCCESS", stopped=True).health is Health.COMPLETED

    @pytest.mark.parametrize("status", ["CRASHED", "FAILED"])
    def test_failed_statuses_are_down(self, status):
        assert _state(status).health is Health.DOWN

    def test_a_crashed_one_shot_is_still_down(self):
        # Stopped does not excuse a crash: the last run failed.
        assert _state("CRASHED", stopped=True).health is Health.DOWN

    @pytest.mark.parametrize("status", ["BUILDING", "DEPLOYING", "QUEUED"])
    def test_in_flight_statuses_are_not_findings(self, status):
        assert _state(status).health is Health.IN_FLIGHT

    def test_unrecognised_status_is_unknown_not_healthy(self):
        # An unknown state and a good state must never print the same.
        assert _state("SOMETHING_NEW").health is Health.UNKNOWN


class TestReportFindings:
    def test_down_and_unknown_are_findings(self):
        report = LivenessReport(
            states=(
                _state("SUCCESS", name="ok"),
                _state("SUCCESS", stopped=True, name="cron"),
                _state("BUILDING", name="deploying"),
                _state("CRASHED", name="dead"),
                _state("WAT", name="mystery"),
            )
        )
        assert [s.name for s in report.findings] == ["dead", "mystery"]

    def test_healthy_estate_reports_no_findings(self):
        report = LivenessReport(states=(_state("SUCCESS", name="ok"),))
        assert report.findings == ()
