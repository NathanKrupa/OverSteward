# ABOUTME: Tests for the cron-service plan — cloning a sibling's config, overriding the schedule, adding sealed vars.
# ABOUTME: The contract under test: values are copied verbatim into the patch and never into the preview.

from __future__ import annotations

import pytest

from oversteward.railway_cron.plan import (
    CronSpec,
    PlanError,
    build_patch,
    service_id_for,
)
from oversteward.railway_cron.render import render_preview

_SIBLING_ID = "sib-1"
_CONFIG = {
    "services": {
        _SIBLING_ID: {
            "source": {"repo": "NathanKrupa/aigranthelper", "branch": "main", "checkSuites": False},
            "build": {"builder": "RAILPACK", "buildEnvironment": "V3"},
            "deploy": {
                "startCommand": "python manage.py submit_seo_urls",
                "cronSchedule": "0 3 * * *",
                # A sibling that restarts: the plan must set NEVER, not inherit it.
                "restartPolicyType": "ON_FAILURE",
                "multiRegionConfig": {"us-west2": {"numReplicas": 1}},
            },
            "variables": {
                "SECRET_KEY": {"value": "${{shared.SECRET_KEY}}"},
                "DB_DSN": {"value": "postgresql://u:hunter2@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/railway"},
            },
        }
    },
    "sharedVariables": {"SECRET_KEY": {"value": "s3cret"}},
}
_SERVICES = [{"id": _SIBLING_ID, "name": "submit_seo_urls"}, {"id": "web-1", "name": "aigranthelper"}]


def _spec(**overrides) -> CronSpec:
    base = dict(
        name="monitor_indexation",
        like="submit_seo_urls",
        start_command="python manage.py monitor_indexation",
        schedule="0 4 * * 1",
        variables={"GSC_SITE_URL": "sc-domain:example.com", "GSC_CREDENTIALS_JSON": '{"type":"service_account"}'},
        sealed=frozenset({"GSC_CREDENTIALS_JSON"}),
    )
    base.update(overrides)
    return CronSpec(**base)


class TestServiceIdFor:
    def test_resolves_a_name_to_its_id(self):
        assert service_id_for(_SERVICES, "submit_seo_urls") == _SIBLING_ID

    def test_an_unknown_name_is_an_error_not_none(self):
        with pytest.raises(PlanError, match="no service named 'nope'"):
            service_id_for(_SERVICES, "nope")


class TestBuildPatch:
    def test_clones_source_and_build_from_the_sibling(self):
        patch = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")
        svc = patch["services"]["new-1"]
        assert svc["source"] == _CONFIG["services"][_SIBLING_ID]["source"]
        assert svc["build"] == _CONFIG["services"][_SIBLING_ID]["build"]

    def test_overrides_start_command_and_schedule_and_never_restarts(self):
        svc = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")["services"]["new-1"]
        assert svc["deploy"]["startCommand"] == "python manage.py monitor_indexation"
        assert svc["deploy"]["cronSchedule"] == "0 4 * * 1"
        assert svc["deploy"]["restartPolicyType"] == "NEVER"
        assert svc["deploy"]["multiRegionConfig"] == {"us-west2": {"numReplicas": 1}}

    def test_copies_every_sibling_variable_verbatim(self):
        svc = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")["services"]["new-1"]
        assert svc["variables"]["SECRET_KEY"] == {"value": "${{shared.SECRET_KEY}}"}
        assert svc["variables"]["DB_DSN"]["value"].startswith("postgresql://u:hunter2@")

    def test_adds_the_spec_variables_sealing_the_named_ones(self):
        svc = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")["services"]["new-1"]
        assert svc["variables"]["GSC_SITE_URL"] == {"value": "sc-domain:example.com"}
        assert svc["variables"]["GSC_CREDENTIALS_JSON"] == {
            "value": '{"type":"service_account"}',
            "isSealed": True,
        }

    def test_a_spec_variable_shadowing_a_sibling_one_wins(self):
        spec = _spec(variables={"SECRET_KEY": "override"}, sealed=frozenset())
        svc = build_patch(_CONFIG, _SERVICES, spec, new_service_id="new-1")["services"]["new-1"]
        assert svc["variables"]["SECRET_KEY"] == {"value": "override"}

    def test_sealing_a_name_that_is_not_a_variable_is_an_error(self):
        with pytest.raises(PlanError, match="sealed but not set: NOPE"):
            build_patch(_CONFIG, _SERVICES, _spec(sealed=frozenset({"NOPE"})), new_service_id="new-1")

    def test_a_name_already_taken_is_an_error(self):
        with pytest.raises(PlanError, match="already exists"):
            build_patch(_CONFIG, _SERVICES, _spec(name="aigranthelper"), new_service_id="new-1")

    def test_a_sibling_without_config_in_this_environment_is_an_error(self):
        with pytest.raises(PlanError, match="no config in this environment"):
            build_patch({"services": {}}, _SERVICES, _spec(), new_service_id="new-1")

    def test_touches_only_the_new_service(self):
        patch = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")
        assert list(patch) == ["services"]
        assert list(patch["services"]) == ["new-1"]


class TestRenderPreview:
    def test_names_every_variable_and_prints_no_literal_value(self):
        patch = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")
        text = render_preview(patch, "new-1", _spec())
        for name in ("SECRET_KEY", "DB_DSN", "GSC_SITE_URL", "GSC_CREDENTIALS_JSON"):
            assert name in text
        assert "${{shared.SECRET_KEY}}" in text
        assert "hunter2" not in text
        assert "service_account" not in text
        assert "sc-domain:example.com" not in text

    def test_marks_sealed_variables_and_literal_lengths(self):
        patch = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")
        text = render_preview(patch, "new-1", _spec())
        assert "GSC_CREDENTIALS_JSON" in text and "sealed" in text
        assert "literal (26 chars)" in text  # '{"type":"service_account"}'

    def test_shows_the_schedule_and_start_command(self):
        patch = build_patch(_CONFIG, _SERVICES, _spec(), new_service_id="new-1")
        text = render_preview(patch, "new-1", _spec())
        assert "0 4 * * 1" in text
        assert "python manage.py monitor_indexation" in text
