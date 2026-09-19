# ABOUTME: Tests for the provisioning sequence — a dry run touches nothing; apply creates, commits, then verifies.
# ABOUTME: Railway is a recording fake; the contract is what gets called, with what, and what refuses.

from __future__ import annotations

import copy

import pytest

from oversteward.railway_cron.plan import CronSpec, PlanError
from oversteward.railway_cron.provision import RailwayCalls, VerifyError, provision

_SIBLING = {
    "source": {"repo": "NathanKrupa/aigranthelper", "branch": "main"},
    "build": {"builder": "RAILPACK"},
    "deploy": {"startCommand": "python manage.py submit_seo_urls", "cronSchedule": "0 3 * * *"},
    "variables": {"SECRET_KEY": {"value": "${{shared.SECRET_KEY}}"}},
}
_SPEC = CronSpec(
    name="monitor_indexation",
    like="submit_seo_urls",
    start_command="python manage.py monitor_indexation",
    schedule="0 4 * * 1",
    variables={"GSC_SITE_URL": "sc-domain:example.com"},
)


class _Railway:
    """Records every call; the config it reports back grows as patches are committed."""

    def __init__(self, *, verify_shows: bool = True, mangle=None):
        self.configs = {"env-production": {"services": {"sib-1": _SIBLING}}}
        self.services = [{"id": "sib-1", "name": "submit_seo_urls"}]
        self.environments = [{"id": "env-staging", "name": "staging"}, {"id": "env-production", "name": "production"}]
        self.created: list[tuple[str, str]] = []
        self.commits: list[tuple[str, dict, str]] = []
        self.config_reads: list[str] = []
        self.verify_shows = verify_shows
        self.mangle = mangle

    def calls(self) -> RailwayCalls:
        return RailwayCalls(
            read_project=lambda _p: (self.services, self.environments),
            read_config=self._read_config,
            create_service=self._create,
            apply_patch=self._apply,
        )

    def _read_config(self, environment_id):
        self.config_reads.append(environment_id)
        return self.configs[environment_id]

    def _create(self, project, name):
        self.created.append((project, name))
        return "new-1"

    def _apply(self, environment_id, patch, *, message):
        self.commits.append((environment_id, copy.deepcopy(patch), message))
        if self.verify_shows:
            # What Railway stores is what the read-back reports; ``mangle``
            # edits the stored copy so the committed patch and the read-back
            # can disagree, which is the case _verify exists to catch.
            stored = copy.deepcopy(patch)
            if self.mangle:
                self.mangle(stored)
            current = self.configs[environment_id]
            self.configs[environment_id] = {"services": {**current["services"], **stored["services"]}}


class TestDryRun:
    def test_creates_and_commits_nothing(self):
        railway = _Railway()
        text = provision(_SPEC, project_id="p1", environment="production", apply=False, calls=railway.calls())
        assert railway.created == []
        assert railway.commits == []
        assert "dry run" in text
        assert "0 4 * * 1" in text

    def test_reads_the_named_environment_not_the_first(self):
        railway = _Railway()
        provision(_SPEC, project_id="p1", environment="production", apply=False, calls=railway.calls())
        assert railway.config_reads == ["env-production"]

    def test_an_unknown_environment_is_a_plan_error(self):
        railway = _Railway()
        with pytest.raises(PlanError, match="no environment named 'qa'"):
            provision(_SPEC, project_id="p1", environment="qa", apply=False, calls=railway.calls())


class TestApply:
    def test_creates_the_service_then_commits_the_patch_keyed_by_its_id(self):
        railway = _Railway()
        text = provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())
        assert railway.created == [("p1", "monitor_indexation")]
        environment_id, patch, message = railway.commits[0]
        assert environment_id == "env-production"
        assert list(patch["services"]) == ["new-1"]
        assert patch["services"]["new-1"]["deploy"]["cronSchedule"] == "0 4 * * 1"
        assert patch["services"]["new-1"]["variables"]["GSC_SITE_URL"] == {"value": "sc-domain:example.com"}
        assert "monitor_indexation" in message
        assert "applied: service monitor_indexation = new-1" in text

    def test_re_reads_the_config_after_the_commit(self):
        railway = _Railway()
        provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())
        assert railway.config_reads == ["env-production", "env-production"]

    def test_refuses_to_report_success_when_the_read_back_lacks_the_service(self):
        railway = _Railway(verify_shows=False)
        with pytest.raises(VerifyError, match="absent from the re-read config"):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())

    def test_refuses_when_the_read_back_schedule_differs(self):
        def _wrong_schedule(patch):
            patch["services"]["new-1"]["deploy"]["cronSchedule"] = "0 3 * * *"

        railway = _Railway(mangle=_wrong_schedule)
        with pytest.raises(VerifyError, match="re-read deploy.cronSchedule"):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())

    def test_refuses_when_the_read_back_lacks_a_variable(self):
        def _drop_var(patch):
            del patch["services"]["new-1"]["variables"]["GSC_SITE_URL"]

        railway = _Railway(mangle=_drop_var)
        with pytest.raises(VerifyError, match="lacks variables: GSC_SITE_URL"):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())

    def test_refuses_when_the_read_back_lacks_a_cloned_variable(self):
        def _drop_cloned(patch):
            del patch["services"]["new-1"]["variables"]["SECRET_KEY"]

        railway = _Railway(mangle=_drop_cloned)
        with pytest.raises(VerifyError, match="lacks variables: SECRET_KEY"):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())

    def test_refuses_when_the_read_back_start_command_is_the_siblings(self):
        def _siblings_command(patch):
            patch["services"]["new-1"]["deploy"]["startCommand"] = "python manage.py submit_seo_urls"

        railway = _Railway(mangle=_siblings_command)
        with pytest.raises(VerifyError, match="re-read deploy.startCommand"):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())

    def test_refuses_when_the_read_back_restart_policy_is_not_never(self):
        def _restarts(patch):
            patch["services"]["new-1"]["deploy"]["restartPolicyType"] = "ON_FAILURE"

        railway = _Railway(mangle=_restarts)
        with pytest.raises(VerifyError, match="re-read deploy.restartPolicyType"):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())


class TestAdoption:
    """A service created by an earlier run whose commit failed is adopted, not clashed with."""

    def test_an_empty_service_of_that_name_is_adopted_without_a_create(self):
        railway = _Railway()
        railway.services = [*railway.services, {"id": "left-1", "name": "monitor_indexation"}]
        text = provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())
        assert railway.created == []
        assert list(railway.commits[0][1]["services"]) == ["left-1"]
        assert "adopted empty service monitor_indexation = left-1" in text

    def test_a_configured_service_of_that_name_is_a_plan_error_before_any_write(self):
        railway = _Railway()
        railway.services = [*railway.services, {"id": "busy-1", "name": "monitor_indexation"}]
        railway.configs["env-production"]["services"]["busy-1"] = {"deploy": {"startCommand": "x"}}
        with pytest.raises(PlanError, match="already exists and is configured"):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())
        assert railway.created == []
        assert railway.commits == []

    def test_a_failed_commit_leaves_the_created_service_for_the_next_run_to_adopt(self):
        railway = _Railway()

        def _fail(environment_id, patch, *, message):
            raise RuntimeError("commit failed")

        calls = RailwayCalls(
            read_project=lambda _p: (railway.services, railway.environments),
            read_config=railway._read_config,
            create_service=railway._create,
            apply_patch=_fail,
        )
        with pytest.raises(RuntimeError):
            provision(_SPEC, project_id="p1", environment="production", apply=True, calls=calls)
        railway.services = [*railway.services, {"id": "new-1", "name": "monitor_indexation"}]
        text = provision(_SPEC, project_id="p1", environment="production", apply=True, calls=railway.calls())
        assert railway.created == [("p1", "monitor_indexation")]  # created once, not twice
        assert "adopted empty service monitor_indexation = new-1" in text
