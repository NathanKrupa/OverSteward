# ABOUTME: Tests for coverage — every module claimed exactly once, and the floor compared in both directions.
# ABOUTME: A floor that only a breach can fail never tightens, so a measured improvement is a finding too.

from __future__ import annotations

from typing import Any

import pytest

from oversteward.estate_map.coverage import compare, coverage_outcome, measure, modules
from oversteward.estate_map.model import Floor, parse
from oversteward.estate_map.outcome import EXIT_CLEAN, EXIT_COULD_NOT_LOOK, EXIT_FINDINGS

OS_FILES = [
    "src/oversteward/sow/plan.py",
    "src/oversteward/sow/canon.py",
    "src/oversteward/dev_family.py",
    "src/oversteward/README.md",
]


def _os_cap(raw: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in raw["capabilities"] if c["id"] == "os.sow")


class TestModules:
    def test_only_python_under_the_repo_roots_counts(self):
        files = [*OS_FILES, "scripts/sow.py", "tests/test_sow.py"]
        assert modules("oversteward", files) == [
            "src/oversteward/dev_family.py",
            "src/oversteward/sow/canon.py",
            "src/oversteward/sow/plan.py",
        ]

    def test_aigranthelper_excludes_migrations_and_tests(self):
        files = [
            "apps/research/views.py",
            "apps/research/migrations/0001_initial.py",
            "apps/research/tests/test_views.py",
            "config/settings/base.py",
        ]
        assert modules("aigranthelper", files) == ["apps/research/views.py"]

    def test_a_repo_without_roots_has_no_modules(self):
        with pytest.raises(KeyError):
            modules("gaudi", ["src/gaudi/x.py"])


class TestMeasure:
    def test_fully_claimed_repo_has_no_orphans(self, raw):
        cov = measure(parse(raw), "oversteward", OS_FILES)
        assert cov.orphans == () and cov.overlaps == {}
        assert len(cov.modules) == 3

    def test_unclaimed_module_is_an_orphan(self, raw):
        cov = measure(parse(raw), "oversteward", [*OS_FILES, "src/oversteward/gather.py"])
        assert cov.orphans == ("src/oversteward/gather.py",)

    def test_directory_claim_does_not_match_a_sibling_sharing_its_prefix(self, raw):
        cov = measure(parse(raw), "oversteward", [*OS_FILES, "src/oversteward/sowing.py"])
        assert cov.orphans == ("src/oversteward/sowing.py",)

    def test_module_claimed_twice_is_an_overlap_naming_both(self, raw):
        raw["capabilities"].append(
            {
                "id": "os.family",
                "kind": "code",
                "purpose": "p",
                "status": "live",
                "claims": {"oversteward": ["src/oversteward/dev_family.py"]},
                "current_shape": "c",
                "target_shape": "hold",
            }
        )
        cov = measure(parse(raw), "oversteward", OS_FILES)
        assert cov.overlaps == {"src/oversteward/dev_family.py": ("os.family", "os.sow")}
        assert cov.orphans == ()
        assert cov.holds == 1

    def test_largest_claims_are_ranked_by_module_count(self, raw):
        cov = measure(parse(raw), "oversteward", OS_FILES)
        assert cov.claim_sizes == (("os.sow", 3),)


class TestCompare:
    def test_measured_equal_to_floor_is_clean(self, raw):
        cov = measure(parse(raw), "oversteward", OS_FILES)
        assert compare(cov, Floor(orphans=0, overlaps=0)) == []

    def test_orphans_above_the_floor_is_a_finding(self, raw):
        cov = measure(parse(raw), "oversteward", [*OS_FILES, "src/oversteward/gather.py"])
        findings = compare(cov, Floor(orphans=0, overlaps=0))
        assert [(f.check, f.subject) for f in findings] == [("coverage-floor", "oversteward")]
        assert "above" in findings[0].message and "src/oversteward/gather.py" in findings[0].message

    @pytest.mark.parametrize(
        ("floor", "expect"),
        [(5, "lower the floor"), (2, "above"), (3, None)],
    )
    def test_orphan_floor_boundary_both_ways(self, raw, floor, expect):
        files = [*OS_FILES, "src/oversteward/a.py", "src/oversteward/b.py", "src/oversteward/c.py"]
        cov = measure(parse(raw), "oversteward", files)
        assert len(cov.orphans) == 3
        findings = compare(cov, Floor(orphans=floor, overlaps=0))
        if expect is None:
            assert findings == []
        else:
            assert len(findings) == 1 and expect in findings[0].message

    @pytest.mark.parametrize(("floor", "expect"), [(0, "above"), (2, "lower the floor"), (1, None)])
    def test_overlap_floor_boundary_both_ways(self, raw, floor, expect):
        raw["capabilities"].append(
            {
                "id": "os.family",
                "kind": "code",
                "purpose": "p",
                "status": "live",
                "claims": {"oversteward": ["src/oversteward/dev_family.py"]},
                "current_shape": "c",
                "target_shape": "hold",
            }
        )
        cov = measure(parse(raw), "oversteward", OS_FILES)
        findings = compare(cov, Floor(orphans=0, overlaps=floor))
        if expect is None:
            assert findings == []
        else:
            assert len(findings) == 1 and expect in findings[0].message


class TestOutcome:
    def _lister(self, files):
        def _list(repo: str, roots):
            return files
        return _list

    def test_floor_breach_exits_1(self, raw):
        outcome = coverage_outcome(
            parse(raw), "oversteward", self._lister([*OS_FILES, "src/oversteward/gather.py"])
        )
        assert outcome.exit_code == EXIT_FINDINGS

    def test_clean_repo_exits_0_and_names_the_count(self, raw):
        outcome = coverage_outcome(parse(raw), "oversteward", self._lister(OS_FILES))
        assert outcome.exit_code == EXIT_CLEAN
        assert any("3 modules" in note for note in outcome.notes)

    def test_unmeasured_floor_reports_without_comparing(self, raw):
        outcome = coverage_outcome(
            parse(raw), "grantspider", self._lister(["src/grantspider/services/x.py"])
        )
        assert outcome.exit_code == EXIT_CLEAN
        assert any("unmeasured" in note for note in outcome.notes)

    def test_repo_nothing_claims_exits_2(self, raw):
        for cap in raw["capabilities"]:
            cap.pop("claims", None)
        outcome = coverage_outcome(parse(raw), "oversteward", self._lister(OS_FILES))
        assert outcome.exit_code == EXIT_COULD_NOT_LOOK

    def test_empty_listing_exits_2(self, raw):
        outcome = coverage_outcome(parse(raw), "oversteward", self._lister([]))
        assert outcome.exit_code == EXIT_COULD_NOT_LOOK

    def test_listing_that_could_not_look_exits_2(self, raw):
        from oversteward.estate_map.checkouts import CouldNotLook

        def _blind(repo, roots):
            raise CouldNotLook("oversteward: fetch failed")

        outcome = coverage_outcome(parse(raw), "oversteward", _blind)
        assert outcome.exit_code == EXIT_COULD_NOT_LOOK
        assert outcome.could_not_look == ("oversteward: fetch failed",)

    def test_repo_with_no_coverage_roots_exits_2(self, raw):
        outcome = coverage_outcome(parse(raw), "gaudi", self._lister(["src/gaudi/x.py"]))
        assert outcome.exit_code == EXIT_COULD_NOT_LOOK
