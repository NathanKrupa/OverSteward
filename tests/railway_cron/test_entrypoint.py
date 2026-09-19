# ABOUTME: Tests for scripts/railway_cron.py — flag parsing into a CronSpec and exit-code mapping.
# ABOUTME: --var-file is read in-process; a bad flag exits 2, an unreadable Railway exits 1.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from oversteward.railway_cron.client import RailwayUnavailableError
from oversteward.railway_cron.plan import PlanError
from oversteward.railway_cron.provision import VerifyError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("railway_cron", REPO_ROOT / "scripts" / "railway_cron.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = [
    "--project", "p1", "--environment", "production",
    "--name", "monitor_indexation", "--like", "submit_seo_urls",
    "--start-command", "python manage.py monitor_indexation", "--schedule", "0 4 * * 1",
]


class TestSpecFromArgs:
    def test_reads_var_and_var_file_and_seal(self, tmp_path):
        module = _module()
        key = tmp_path / "sa.json"
        key.write_text('{"type":"service_account"}', encoding="utf-8")
        args = module._parse_args(
            [*_BASE, "--var", "GSC_SITE_URL=sc-domain:x.com", "--var-file", f"GSC_CREDENTIALS_JSON={key}",
             "--seal", "GSC_CREDENTIALS_JSON"]
        )
        spec = module.spec_from_args(args)
        assert spec.variables == {
            "GSC_SITE_URL": "sc-domain:x.com",
            "GSC_CREDENTIALS_JSON": '{"type":"service_account"}',
        }
        assert spec.sealed == frozenset({"GSC_CREDENTIALS_JSON"})
        assert spec.schedule == "0 4 * * 1"

    def test_a_value_may_contain_an_equals_sign(self):
        module = _module()
        spec = module.spec_from_args(module._parse_args([*_BASE, "--var", "X=a=b"]))
        assert spec.variables == {"X": "a=b"}

    def test_a_missing_var_file_is_a_plan_error(self, tmp_path):
        module = _module()
        with pytest.raises(PlanError, match="no such file"):
            module.spec_from_args(module._parse_args([*_BASE, "--var-file", f"K={tmp_path / 'absent'}"]))

    def test_an_assignment_without_equals_is_a_plan_error(self):
        module = _module()
        with pytest.raises(PlanError, match="expected NAME=value"):
            module.spec_from_args(module._parse_args([*_BASE, "--var", "NOEQUALS"]))


class TestExitCodes:
    def test_plan_error_exits_2(self, monkeypatch, capsys):
        module = _module()
        monkeypatch.setattr(module, "provision", lambda *a, **k: (_ for _ in ()).throw(PlanError("clash")))
        assert module.main(_BASE) == 2
        assert "clash" in capsys.readouterr().err

    def test_railway_unavailable_exits_1(self, monkeypatch, capsys):
        module = _module()
        monkeypatch.setattr(
            module, "provision", lambda *a, **k: (_ for _ in ()).throw(RailwayUnavailableError("down"))
        )
        assert module.main(_BASE) == 1
        assert "down" in capsys.readouterr().err

    def test_verify_error_exits_1(self, monkeypatch):
        module = _module()
        monkeypatch.setattr(module, "provision", lambda *a, **k: (_ for _ in ()).throw(VerifyError("absent")))
        assert module.main(_BASE) == 1

    def test_a_report_exits_0_and_prints_it(self, monkeypatch, capsys):
        module = _module()
        monkeypatch.setattr(module, "provision", lambda *a, **k: "planned")
        assert module.main(_BASE) == 0
        assert capsys.readouterr().out.strip() == "planned"
