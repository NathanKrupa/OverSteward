# ABOUTME: Tests for scripts/estate_map.py — the exit codes are the contract: 0 clean, 1 findings, 2 could not look.
# ABOUTME: Each runs the real script on a temp map and registry, reading this checkout's own git tree with real git.

from __future__ import annotations

import copy
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
def local(raw) -> dict[str, Any]:
    """The base map with no sibling-repo claims, and OverSteward's src/ claimed whole."""
    data = copy.deepcopy(raw)
    for cap in data["capabilities"]:
        cap["claims"] = {}
    _cap(data, "os.sow")["claims"] = {"oversteward": ["src/oversteward/"]}
    return data


def _cap(data: dict[str, Any], cap_id: str) -> dict[str, Any]:
    return next(c for c in data["capabilities"] if c["id"] == cap_id)


def _write(tmp_path: Path, data: dict[str, Any], name: str) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _args(tmp_path: Path, data: dict[str, Any], *, gs_path: Path | None = None) -> list[str]:
    registry = {
        "contexts": [
            {"id": "oversteward", "branch": "master", "local_path": str(ROOT)},
            {
                "id": "grantspider",
                "branch": "staging",
                "primary_branch": "main",
                "local_path": str(gs_path or tmp_path / "no-such-checkout"),
            },
            {"id": "aigranthelper", "branch": "staging", "local_path": str(tmp_path / "no-ag")},
        ]
    }
    return [
        "--map",
        str(_write(tmp_path, data, "map.yaml")),
        "--registry",
        str(_write(tmp_path, registry, "registry.yaml")),
        "--digest",
        str(tmp_path / "digest.md"),
        "--slices",
        str(tmp_path / "slices"),
    ]


def test_check_on_a_map_this_checkout_satisfies_is_clean(cli, capsys, tmp_path, local):
    assert cli.main([*_args(tmp_path, local), "check"]) == 0
    out = capsys.readouterr().out
    assert "0 orphans, 0 overlaps" in out
    assert "coverage grantspider: unmeasured" in out
    assert out.rstrip().endswith("estate-map: clean")


def test_check_runs_validate(cli, capsys, tmp_path, local):
    _cap(local, "gs.website-resolution")["serves"] = ["ag.nope"]
    assert cli.main([*_args(tmp_path, local), "check"]) == 1
    assert "dangling-ref: gs.website-resolution" in capsys.readouterr().out


def test_check_runs_locations(cli, capsys, tmp_path, local):
    _cap(local, "os.sow")["claims"]["oversteward"].append("src/oversteward/nope.py")
    assert cli.main([*_args(tmp_path, local), "check"]) == 1
    assert "missing-path: os.sow" in capsys.readouterr().out


def test_coverage_with_no_measured_floor_exits_2(cli, capsys, tmp_path, local):
    local["policy"]["coverage_floor"]["oversteward"] = None
    assert cli.main([*_args(tmp_path, local), "coverage"]) == 2
    assert "COULD NOT LOOK - coverage: no repo has a measured floor" in capsys.readouterr().out


def test_coverage_repo_flag_measures_the_named_repo(cli, capsys, tmp_path, local):
    # Without --repo only oversteward (measured) is read; naming grantspider
    # sends coverage to its checkout, which this registry says is absent.
    _cap(local, "gs.website-resolution")["claims"] = {"grantspider": ["src/grantspider/cli/x.py"]}
    assert cli.main([*_args(tmp_path, local), "coverage", "--repo", "grantspider"]) == 2
    assert "COULD NOT LOOK - grantspider: checkout" in capsys.readouterr().out


def test_validate_finding_exits_1(cli, capsys, tmp_path, local):
    _cap(local, "gs.website-resolution")["serves"] = ["ag.nope"]
    assert cli.main([*_args(tmp_path, local), "validate"]) == 1
    assert "dangling-ref: gs.website-resolution" in capsys.readouterr().out


def test_locations_naming_a_missing_path_exits_1_and_names_it(cli, capsys, tmp_path, local):
    _cap(local, "os.sow")["claims"]["oversteward"].append("src/oversteward/nope.py")
    assert cli.main([*_args(tmp_path, local), "locations"]) == 1
    out = capsys.readouterr().out
    assert "missing-path: os.sow" in out and "oversteward:src/oversteward/nope.py" in out


def test_locations_with_an_absent_checkout_exits_2(cli, capsys, tmp_path, local):
    _cap(local, "gs.website-resolution")["claims"] = {"grantspider": ["src/grantspider/cli/"]}
    assert cli.main([*_args(tmp_path, local), "locations"]) == 2
    out = capsys.readouterr().out
    assert "COULD NOT LOOK - grantspider: checkout" in out
    assert "estate-map: clean" not in out


def test_coverage_with_an_unclaimed_module_exits_1(cli, capsys, tmp_path, local):
    _cap(local, "os.sow")["claims"] = {"oversteward": ["src/oversteward/sow/"]}
    assert cli.main([*_args(tmp_path, local), "coverage", "--repo", "oversteward"]) == 1
    out = capsys.readouterr().out
    assert "above floor 0" in out and "src/oversteward/dev_family.py" in out


def test_coverage_below_a_stale_floor_exits_1(cli, capsys, tmp_path, local):
    local["policy"]["coverage_floor"]["oversteward"]["orphans"] = 5
    assert cli.main([*_args(tmp_path, local), "coverage"]) == 1
    assert "lower the floor to 0" in capsys.readouterr().out


def test_malformed_map_exits_1(cli, capsys, tmp_path, local):
    del local["capabilities"][0]["kind"]
    assert cli.main([*_args(tmp_path, local), "validate"]) == 1
    assert "malformed" in capsys.readouterr().out


def test_missing_map_exits_2(cli, capsys, tmp_path):
    assert cli.main(["--map", str(tmp_path / "absent.yaml"), "check"]) == 2
    assert "COULD NOT LOOK" in capsys.readouterr().out


def test_render_write_writes_what_render_prints(cli, capsys, tmp_path, local):
    args = _args(tmp_path, local)
    assert cli.main([*args, "render"]) == 0
    printed = capsys.readouterr().out
    assert cli.main([*args, "render", "--write"]) == 0
    assert (tmp_path / "digest.md").read_text(encoding="utf-8") == printed


def test_render_over_budget_exits_1(cli, capsys, tmp_path, local):
    local["policy"]["digest_budget_bytes"] = 100
    assert cli.main([*_args(tmp_path, local), "render"]) == 1
    assert "digest-budget" in capsys.readouterr().err


def test_render_write_writes_one_slice_per_repo_with_capabilities(cli, capsys, tmp_path, local):
    from oversteward.estate_map.model import parse
    from oversteward.estate_map.render import repo_slice

    assert cli.main([*_args(tmp_path, local), "render", "--write"]) == 0
    slices = tmp_path / "slices"
    names = sorted(p.name for p in slices.iterdir())
    assert names == ["aigranthelper.md", "grantspider.md", "oversteward.md"]
    estate = parse(local)
    for name in names:
        repo = name.removesuffix(".md")
        assert (slices / name).read_text(encoding="utf-8") == repo_slice(estate, repo)
    assert "grantspider.md" in capsys.readouterr().out


def test_render_without_write_writes_no_slices(cli, capsys, tmp_path, local):
    assert cli.main([*_args(tmp_path, local), "render"]) == 0
    assert not (tmp_path / "slices").exists()


def test_render_write_removes_a_slice_for_a_repo_that_lost_its_capabilities(
    cli, capsys, tmp_path, local
):
    slices = tmp_path / "slices"
    slices.mkdir()
    (slices / "wphelper.md").write_text("stale", encoding="utf-8")
    assert cli.main([*_args(tmp_path, local), "render", "--write"]) == 0
    assert not (slices / "wphelper.md").exists()
    assert "removed" in capsys.readouterr().out


def test_render_write_leaves_files_that_are_not_slices(cli, capsys, tmp_path, local):
    slices = tmp_path / "slices"
    (slices / "notes").mkdir(parents=True)
    keep = [slices / "README.txt", slices / "notes" / "wphelper.md"]
    for path in keep:
        path.write_text("kept", encoding="utf-8")
    assert cli.main([*_args(tmp_path, local), "render", "--write"]) == 0
    assert all(path.read_text(encoding="utf-8") == "kept" for path in keep)


def test_render_over_the_slice_budget_exits_1_naming_the_repo(cli, capsys, tmp_path, local):
    local["policy"]["slice_budget_bytes"] = 100
    assert cli.main([*_args(tmp_path, local), "render"]) == 1
    err = capsys.readouterr().err
    assert "slice-budget" in err and "grantspider" in err


class _CrashingGit:
    def run(self, cwd, *args):
        raise RuntimeError("synthetic git crash")


def test_a_crash_mid_check_exits_2(cli, capsys, tmp_path, local):
    assert cli.main([*_args(tmp_path, local), "check"], git=_CrashingGit()) == 2
    out = capsys.readouterr().out
    assert "COULD NOT LOOK - check crashed: RuntimeError: synthetic git crash" in out
    assert "Traceback" not in out


def test_a_render_that_cannot_write_exits_2(cli, capsys, tmp_path, local):
    args = _args(tmp_path, local)
    args[args.index("--digest") + 1] = str(tmp_path)
    assert cli.main([*args, "render", "--write"]) == 2
    assert "COULD NOT LOOK - render crashed: IsADirectoryError" in capsys.readouterr().out
