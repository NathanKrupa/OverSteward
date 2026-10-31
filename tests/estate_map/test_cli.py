# ABOUTME: Tests for scripts/estate_map.py — the exit codes are the contract: 0 clean, 1 findings, 2 could not look.
# ABOUTME: Each runs the real script on a temp copy of the map, reading this checkout's own git tree.

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("estate_map_cli", ROOT / "scripts" / "estate_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def real() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "estate-map.yaml").read_text(encoding="utf-8"))


def _write(tmp_path: Path, data: dict[str, Any], name: str = "map.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _cap(data: dict[str, Any], cap_id: str) -> dict[str, Any]:
    return next(c for c in data["capabilities"] if c["id"] == cap_id)


def test_validate_on_the_committed_map_is_clean(cli, capsys):
    assert cli.main(["validate"]) == 0
    assert "estate-map: clean" in capsys.readouterr().out


def test_locations_naming_a_missing_path_exits_1_and_names_it(cli, capsys, tmp_path, real):
    _cap(real, "os.janitor")["claims"]["oversteward"].append("src/oversteward/nope.py")
    assert cli.main(["--map", str(_write(tmp_path, real)), "locations"]) == 1
    out = capsys.readouterr().out
    assert "missing-path: os.janitor" in out and "oversteward:src/oversteward/nope.py" in out


def test_locations_with_an_absent_checkout_exits_2(cli, capsys, tmp_path, real):
    _cap(real, "gs.crawl")["claims"] = {"grantspider": ["src/grantspider/cli/"]}
    registry = yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8"))
    for ctx in registry["contexts"]:
        if ctx["id"] == "grantspider":
            ctx["local_path"] = str(tmp_path / "no-such-checkout")
    args = ["--map", str(_write(tmp_path, real)), "--registry", str(_write(tmp_path, registry, "reg.yaml"))]
    assert cli.main([*args, "locations"]) == 2
    out = capsys.readouterr().out
    assert "COULD NOT LOOK - grantspider: checkout" in out
    assert "estate-map: clean" not in out


def test_coverage_with_an_unclaimed_module_exits_1(cli, capsys, tmp_path, real):
    _cap(real, "os.janitor")["claims"]["oversteward"] = ["scripts/scratchpad_janitor.py"]
    assert cli.main(["--map", str(_write(tmp_path, real)), "coverage", "--repo", "oversteward"]) == 1
    out = capsys.readouterr().out
    assert "orphans 2 above floor 0" in out and "src/oversteward/janitor/" in out


def test_coverage_below_a_stale_floor_exits_1(cli, capsys, tmp_path, real):
    real["policy"]["coverage_floor"]["oversteward"]["orphans"] = 5
    assert cli.main(["--map", str(_write(tmp_path, real)), "coverage"]) == 1
    assert "lower the floor to 0" in capsys.readouterr().out


def test_coverage_on_the_committed_map_is_clean(cli, capsys):
    assert cli.main(["coverage", "--repo", "oversteward"]) == 0
    assert "0 orphans, 0 overlaps" in capsys.readouterr().out


def test_malformed_map_exits_1(cli, capsys, tmp_path, real):
    del real["capabilities"][0]["kind"]
    assert cli.main(["--map", str(_write(tmp_path, real)), "validate"]) == 1
    assert "malformed" in capsys.readouterr().out


def test_missing_map_exits_2(cli, capsys, tmp_path):
    assert cli.main(["--map", str(tmp_path / "absent.yaml"), "check"]) == 2
    assert "COULD NOT LOOK" in capsys.readouterr().out


def test_render_write_produces_the_committed_digest(cli, tmp_path):
    target = tmp_path / "digest.md"
    assert cli.main(["--digest", str(target), "render", "--write"]) == 0
    assert target.read_text(encoding="utf-8") == (ROOT / "data" / "estate-map-digest.md").read_text(
        encoding="utf-8"
    )


def test_render_over_budget_exits_1(cli, capsys, tmp_path, real):
    real["policy"]["digest_budget_bytes"] = 100
    assert cli.main(["--map", str(_write(tmp_path, real)), "render"]) == 1
    assert "digest-budget" in capsys.readouterr().err


class _CrashingGit:
    def run(self, cwd, *args):
        raise RuntimeError("synthetic git crash")


def test_a_crash_mid_check_exits_2(cli, capsys):
    assert cli.main(["check"], git=_CrashingGit()) == 2
    out = capsys.readouterr().out
    assert "COULD NOT LOOK - check crashed: RuntimeError: synthetic git crash" in out
    assert "Traceback" not in out


def test_a_render_that_cannot_write_exits_2(cli, capsys, tmp_path):
    assert cli.main(["--digest", str(tmp_path), "render", "--write"]) == 2
    out = capsys.readouterr().out
    assert "COULD NOT LOOK - render crashed: IsADirectoryError" in out
