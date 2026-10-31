# ABOUTME: Tests on the committed estate-map.yaml itself — it validates, the migrated rows are all present,
# ABOUTME: the digest and every repo slice match a fresh render within budget, and OS coverage meets its floor.

from __future__ import annotations

from pathlib import Path

import yaml

from oversteward.estate_map.checkouts import TreeReader, checkouts
from oversteward.estate_map.checks import registry_ids
from oversteward.estate_map.coverage import coverage_outcome
from oversteward.estate_map.model import EstateMap, load, parse
from oversteward.estate_map.outcome import EXIT_CLEAN
from oversteward.estate_map.render import (
    budget_findings,
    digest,
    repo_slice,
    slice_budget_findings,
    slice_name,
    slice_repos,
)
from oversteward.estate_map.validate import validate
from oversteward.sow.runners import GitCommand

ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = ROOT / "estate-map.yaml"
DIGEST_PATH = ROOT / "data" / "estate-map-digest.md"
SLICES_DIR = ROOT / "shared" / "references" / "estate-map"
REGISTRY_PATH = ROOT / "registry.yaml"

#: Every ID the 2026-10-31 snapshot (OS#638) carried. IDs are never renumbered,
#: so this set only grows; a row may retire but never vanish.
MIGRATED_INVARIANTS = frozenset(f"I-{n}" for n in range(1, 23))
MIGRATED_LIABILITIES = frozenset(
    {
        "G1", "G4", "G5", "H1-2", "L-OD-1", "L-DISP-1", "L-AG-2", "L-AG-3",
        "L-AA-1", "L-DEV-1", "L-FI-1", "L-EX-1", "L-WSL-1", "L-DOC-1",
    }
)
MIGRATED_SEAMS = (
    "grantspider → aigranthelper (data)",
    "grantspider → aigranthelper (code)",
    "grantspider → aigranthelper (schema drift)",
    "aigranthelper → grantspider",
    "wphelper → aigranthelper, ai-assistants",
    "oversteward → all repos",
    "aigranthelper → fiscus",
    "oversteward → fiscus",
    "pickup repos → fiscus",
    "fiscus → oversteward",
    "grantspider → oversteward",
    "aigranthelper → oversteward",
    "Railway, Sentry → oversteward",
    "billing APIs, GA4 → exchequer",
)


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def digest_is_current(map_path: Path, digest_path: Path) -> bool:
    return digest(load(map_path)) == digest_path.read_text(encoding="utf-8")


def stale_slices(estate: EstateMap, slices_dir: Path) -> list[str]:
    """Each slice file that differs from a fresh render, is missing, or renders from nothing."""
    expected = {slice_name(repo): repo_slice(estate, repo) for repo in slice_repos(estate)}
    present = {p.name for p in slices_dir.iterdir() if p.is_file()} if slices_dir.is_dir() else set()
    stale = sorted(present - set(expected)) + sorted(set(expected) - present)
    stale += [
        name
        for name in sorted(present & set(expected))
        if (slices_dir / name).read_text(encoding="utf-8") != expected[name]
    ]
    return stale


def _copy_slices(tmp_path: Path) -> Path:
    copied = tmp_path / "slices"
    copied.mkdir()
    for path in SLICES_DIR.iterdir():
        (copied / path.name).write_bytes(path.read_bytes())
    return copied


def test_committed_map_validates_against_the_registry():
    findings = validate(load(MAP_PATH), registry_ids(_registry()))
    assert findings == []


def test_every_migrated_row_is_present():
    estate = load(MAP_PATH)
    assert {i.id for i in estate.invariants} >= MIGRATED_INVARIANTS
    assert {i.id for i in estate.invariants if i.status == "retired"} >= {"I-14"}
    assert {item.id for item in estate.liabilities} >= MIGRATED_LIABILITIES
    labels = tuple(s.label for s in estate.seams)
    assert labels[: len(MIGRATED_SEAMS)] == MIGRATED_SEAMS


def test_every_migrated_row_carries_a_cite():
    estate = load(MAP_PATH)
    assert all(i.cite.strip() for i in estate.invariants)
    assert all(s.cite.strip() for s in estate.seams)
    assert all(item.tracking.strip() for item in estate.liabilities)


def test_digest_is_current_and_within_budget():
    estate = load(MAP_PATH)
    assert digest_is_current(MAP_PATH, DIGEST_PATH), (
        "data/estate-map-digest.md is stale: run `scripts/estate_map.py render --write`"
    )
    assert budget_findings(estate, DIGEST_PATH.read_text(encoding="utf-8")) == []


def test_a_hand_edited_digest_is_not_current(tmp_path):
    edited = tmp_path / "digest.md"
    text = DIGEST_PATH.read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("- `os.janitor`"))
    edited.write_text(text.replace(line, line + " (tidied by hand)"), encoding="utf-8")
    assert not digest_is_current(MAP_PATH, edited)


def test_digest_budget_is_the_agreed_ceiling():
    # Nathan's agreed range for an always-loaded digest is about 3-5k tokens; the GS
    # seed left 462 bytes under the 14,000-byte budget (OS#640).
    assert load(MAP_PATH).policy.digest_budget_bytes == 20000


def test_slice_budget_is_the_agreed_ceiling():
    # Each slice is loaded into its repo's sessions at start, so it is held to the
    # digest's ceiling (OS#640); the GS slice is the largest.
    assert load(MAP_PATH).policy.slice_budget_bytes == 20000


def test_every_slice_is_current_and_within_budget():
    estate = load(MAP_PATH)
    assert stale_slices(estate, SLICES_DIR) == [], (
        "shared/references/estate-map/ is stale: run `scripts/estate_map.py render --write`"
    )
    for repo in slice_repos(estate):
        text = (SLICES_DIR / slice_name(repo)).read_text(encoding="utf-8")
        assert slice_budget_findings(estate, repo, text) == []


def test_the_dispatch_repos_have_slices():
    # A slice set that silently lost AG or GS would leave every agent reading nothing.
    assert {"aigranthelper", "grantspider", "oversteward"} <= set(slice_repos(load(MAP_PATH)))


def test_a_hand_edited_slice_is_stale(tmp_path):
    copied = _copy_slices(tmp_path)
    path = copied / "grantspider.md"
    path.write_text(path.read_text(encoding="utf-8") + "- tidied by hand\n", encoding="utf-8")
    assert stale_slices(load(MAP_PATH), copied) == ["grantspider.md"]


def test_a_map_edit_without_render_leaves_the_slices_stale(tmp_path):
    raw = yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))
    cap = next(c for c in raw["capabilities"] if c["id"].startswith("gs."))
    cap["purpose"] += " (edited)"
    assert stale_slices(parse(raw), _copy_slices(tmp_path)) == ["grantspider.md"]


def test_a_missing_or_orphaned_slice_is_stale(tmp_path):
    copied = _copy_slices(tmp_path)
    (copied / "fiscus.md").unlink()
    (copied / "nobody.md").write_text("x", encoding="utf-8")
    assert stale_slices(load(MAP_PATH), copied) == ["nobody.md", "fiscus.md"]


def test_claude_md_loads_the_digest():
    assert "@data/estate-map-digest.md" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


def test_claude_md_runs_the_estate_map_check_as_a_session_start_sweep():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Session start — the seven sweeps" in text
    section = text.split("## Session start", 1)[1].split("\n## ", 1)[0]
    block = section.split("```bash", 1)[1].split("```", 1)[0]
    lines = [line for line in block.splitlines() if "estate_map.py" in line]
    assert lines == [
        ".venv/bin/python scripts/estate_map.py check        # whether the map still matches the code"
    ]


def test_aigranthelper_floor_is_measured_so_the_sweep_reads_it():
    # `check` measures only repos whose floor is not null, so a null floor would
    # silently drop AG from the seventh sweep. The AG tree is not in CI, so the
    # sweep, not this test, compares the floor with the code.
    floor = load(MAP_PATH).policy.coverage_floor["aigranthelper"]
    assert floor is not None
    assert (floor.orphans, floor.overlaps) == (0, 0)


def test_grantspider_floor_is_measured_so_the_sweep_reads_it():
    # Same reason as AG: a null floor drops GS from `check`. The two orphans are
    # `services/matcher.py` and `services/sqlite_migrate.py`, which belong to no
    # capability; the sweep compares the floor with GS origin/main.
    floor = load(MAP_PATH).policy.coverage_floor["grantspider"]
    assert floor is not None
    assert (floor.orphans, floor.overlaps) == (2, 0)


def test_grantspider_services_and_connectors_are_claimed_file_by_file():
    # The explicit-only policy is what keeps GS coverage from being vacuous; a map
    # that dropped it would let one `services/` claim cover 380 modules.
    roots = load(MAP_PATH).policy.explicit_only["grantspider"]
    assert set(roots) == {"src/grantspider/services", "src/grantspider/connectors"}


def test_oversteward_coverage_meets_its_floor_on_this_checkout():
    estate = load(MAP_PATH)
    found = checkouts(_registry(), home_repo="oversteward", home_root=ROOT)
    outcome = coverage_outcome(estate, "oversteward", TreeReader(GitCommand(), found).files)
    assert outcome.exit_code == EXIT_CLEAN, (outcome.findings, outcome.could_not_look)
    assert estate.policy.coverage_floor["oversteward"] is not None
