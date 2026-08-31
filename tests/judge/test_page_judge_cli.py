# ABOUTME: Tests scripts/page_judge.py — the three exit codes are the contract.
# ABOUTME: 0 measured, 1 could not read, 2 not configured; a missing key never tracebacks.

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from oversteward.judge.config import JudgeConfigError
from oversteward.probe.config import ProbeConfigError
from oversteward.probe.models import ProbeResult
from tests.judge.fakes import FakeJudge

REPO_ROOT = Path(__file__).resolve().parents[2]

_EXIT_OK = 0
_EXIT_COULD_NOT_LOOK = 1
_EXIT_MISCONFIGURED = 2

_A = "https://app.example.test/foundations/pa/example/"
_B = "https://app.example.test/grants-for/housing/"
_BODY = "<html><head><title>T</title></head><body><h1>H</h1><p>Words.</p></body></html>"


def _module():
    spec = importlib.util.spec_from_file_location(
        "page_judge", REPO_ROOT / "scripts" / "page_judge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        "name: unit\n"
        "samples: 1\n"
        "page_types:\n"
        f"  foundation: [{_A}]\n"
        "pairs:\n"
        f"  - [{_A}, {_B}]\n",
        encoding="utf-8",
    )
    return path


def _fetch_ok(url, token, **_kwargs):
    return ProbeResult(url=url, status=200, title="T", challenged=False, body=_BODY)


def _fetch_challenged(url, token, **_kwargs):
    return ProbeResult(url=url, status=403, title="", challenged=True, body="")


def _run(argv, tmp_path, **overrides):
    kwargs = {
        "judge_factory": FakeJudge,
        "token_factory": lambda: "probe-token",
        "fetcher": _fetch_ok,
        "reports_dir": tmp_path / "out",
    }
    kwargs.update(overrides)
    return _module().main(argv, **kwargs)


class TestNotConfigured:
    def test_a_missing_gemini_key_exits_two_with_a_message(self, tmp_path, capsys):
        def missing_key():
            raise JudgeConfigError("GEMINI_API_KEY is not set")

        code = _run(["score", str(_manifest(tmp_path))], tmp_path, judge_factory=missing_key)

        assert code == _EXIT_MISCONFIGURED
        assert "GEMINI_API_KEY" in capsys.readouterr().err

    def test_a_missing_probe_token_exits_two(self, tmp_path, capsys):
        def missing_token():
            raise ProbeConfigError("STEWARD_PROBE_TOKEN is unset")

        code = _run(["score", str(_manifest(tmp_path))], tmp_path, token_factory=missing_token)

        assert code == _EXIT_MISCONFIGURED
        assert "STEWARD_PROBE_TOKEN" in capsys.readouterr().err


class TestCouldNotRead:
    def test_a_challenged_page_exits_one_and_says_so(self, tmp_path, capsys):
        code = _run(["score", str(_manifest(tmp_path))], tmp_path, fetcher=_fetch_challenged)

        assert code == _EXIT_COULD_NOT_LOOK
        err = capsys.readouterr().err
        assert "challenge" in err.lower()

    def test_an_exhausted_budget_exits_one_and_reports_the_spend(self, tmp_path, capsys):
        code = _run(
            ["compare", str(_manifest(tmp_path)), "--budget-usd", "0.0005"],
            tmp_path,
        )

        assert code == _EXIT_COULD_NOT_LOOK
        err = capsys.readouterr().err
        assert "budget" in err.lower()
        assert "spent" in err.lower()


class TestMeasuredAnswer:
    def test_a_scored_manifest_exits_zero_and_writes_both_reports(self, tmp_path):
        code = _run(["score", str(_manifest(tmp_path)), "--name", "unit"], tmp_path)

        assert code == _EXIT_OK
        written = sorted(p.name for p in (tmp_path / "out").iterdir())
        assert [name.endswith("-unit.json") for name in written].count(True) == 1
        assert [name.endswith("-unit.md") for name in written].count(True) == 1

    def test_the_json_report_carries_the_scores_and_the_spend(self, tmp_path):
        _run(["score", str(_manifest(tmp_path)), "--name", "unit"], tmp_path)

        payload = json.loads(next((tmp_path / "out").glob("*.json")).read_text(encoding="utf-8"))
        page = payload["pages"][0]
        assert page["url"] == _A
        assert page["page_type"] == "foundation"
        assert page["scores"]["thin_smell"]["score"] == 3
        assert payload["usage"]["cost_usd"] == pytest.approx(0.001125)

    def test_compare_writes_a_tally(self, tmp_path):
        code = _run(["compare", str(_manifest(tmp_path)), "--name", "unit"], tmp_path)

        assert code == _EXIT_OK
        payload = json.loads(next((tmp_path / "out").glob("*.json")).read_text(encoding="utf-8"))
        tally = payload["tallies"][0]
        assert (tally["a_wins"], tally["b_wins"], tally["ties"]) == (1, 1, 0)
