# ABOUTME: Tests for the estate map's semantic checks — each guard has a fixture that makes it red.
# ABOUTME: A finding is asserted by its check name and subject, so a test cannot pass on an unrelated finding.

from __future__ import annotations

from typing import Any

import pytest

from oversteward.estate_map.model import MapError, parse
from oversteward.estate_map.validate import validate

from .conftest import REGISTRY_IDS


def _findings(raw: dict[str, Any], registry_ids=REGISTRY_IDS) -> list[tuple[str, str]]:
    return [(f.check, f.subject) for f in validate(parse(raw), registry_ids)]


def _cap(raw: dict[str, Any], cap_id: str) -> dict[str, Any]:
    return next(c for c in raw["capabilities"] if c["id"] == cap_id)


def test_base_fixture_is_clean(raw):
    assert _findings(raw) == []


class TestReferences:
    def test_dangling_serves_is_a_finding(self, raw):
        _cap(raw, "gs.website-resolution")["serves"] = ["ag.nope"]
        assert ("dangling-ref", "gs.website-resolution") in _findings(raw)

    @pytest.mark.parametrize("field", ["depends_on", "feeds"])
    def test_dangling_capability_link_is_a_finding(self, raw, field):
        _cap(raw, "os.sow")[field] = ["gs.nowhere"]
        assert ("dangling-ref", "os.sow") in _findings(raw)

    def test_capability_citing_an_undefined_invariant_is_a_finding(self, raw):
        _cap(raw, "os.sow")["invariants"] = ["I-99"]
        assert ("dangling-ref", "os.sow") in _findings(raw)

    def test_seam_citing_an_undefined_liability_is_a_finding(self, raw):
        raw["seams"][0]["liabilities"] = ["L-NOPE"]
        assert ("dangling-ref", "S-1") in _findings(raw)

    def test_seam_party_must_be_a_repo_or_external(self, raw):
        raw["seams"][0]["producer"] = ["grantsider"]
        assert ("dangling-ref", "S-1") in _findings(raw)

    def test_external_seam_party_is_accepted(self, raw):
        raw["seams"][0]["producer"] = ["ext:Railway"]
        assert _findings(raw) == []

    def test_claim_on_a_repo_not_in_the_map_is_a_finding(self, raw):
        _cap(raw, "os.sow")["claims"] = {"fiscus": ["src/fiscus/"]}
        assert ("dangling-ref", "os.sow") in _findings(raw)

    def test_invariant_naming_a_capability_that_does_not_cite_it_is_a_finding(self, raw):
        raw["invariants"][1]["capabilities"] = ["os.sow"]
        assert ("link-mismatch", "I-2") in _findings(raw)

    def test_capability_citing_a_liability_that_does_not_name_it_is_a_finding(self, raw):
        _cap(raw, "os.sow")["liabilities"] = ["G1"]
        assert ("link-mismatch", "G1") in _findings(raw)


class TestOrphans:
    def test_invariant_referenced_by_nothing_is_a_finding(self, raw):
        raw["invariants"].append({"id": "I-9", "status": "live", "text": "t", "cite": "c"})
        assert ("orphan", "I-9") in _findings(raw)

    def test_invariant_referenced_only_by_a_seam_is_not_orphaned(self, raw):
        # I-2 in the base map is cited by seam S-1 alone.
        assert ("orphan", "I-2") not in _findings(raw)

    def test_retired_invariant_needs_no_reference(self, raw):
        assert ("orphan", "I-3") not in _findings(raw)

    def test_liability_referenced_by_nothing_is_a_finding(self, raw):
        raw["liabilities"].append(
            {"id": "L-X-1", "text": "t", "owner": "o", "tracking": "k"}
        )
        assert ("orphan", "L-X-1") in _findings(raw)


class TestExplicitOnly:
    def test_directory_claim_under_an_explicit_root_is_a_finding(self, raw):
        _cap(raw, "gs.website-resolution")["claims"] = {"grantspider": ["src/grantspider/services"]}
        assert ("explicit-only", "gs.website-resolution") in _findings(raw)

    def test_subdirectory_claim_under_an_explicit_root_is_a_finding(self, raw):
        _cap(raw, "gs.website-resolution")["claims"] = {
            "grantspider": ["src/grantspider/services/verification/"]
        }
        assert ("explicit-only", "gs.website-resolution") in _findings(raw)

    def test_ancestor_of_an_explicit_root_is_a_finding(self, raw):
        # `src/grantspider` would claim the whole services subtree in one line.
        _cap(raw, "gs.website-resolution")["claims"] = {"grantspider": ["src/grantspider"]}
        assert ("explicit-only", "gs.website-resolution") in _findings(raw)

    def test_directory_claim_outside_the_explicit_roots_is_allowed(self, raw):
        _cap(raw, "gs.website-resolution")["claims"] = {"grantspider": ["src/grantspider/cli/"]}
        assert _findings(raw) == []

    def test_sibling_with_a_shared_prefix_is_not_under_the_root(self, raw):
        _cap(raw, "gs.website-resolution")["claims"] = {"grantspider": ["src/grantspider/services_old/"]}
        assert _findings(raw) == []

    def test_the_policy_is_per_repo(self, raw):
        _cap(raw, "os.sow")["claims"] = {"oversteward": ["src/grantspider/services"]}
        assert ("explicit-only", "os.sow") not in _findings(raw)


class TestRegistry:
    def test_repo_absent_from_the_registry_is_a_finding(self, raw):
        raw["repos"][1]["id"] = "grantsider"
        assert ("registry", "grantsider") in _findings(raw)

    def test_repo_ids_are_checked_against_the_registry_given(self, raw):
        assert ("registry", "aigranthelper") in _findings(raw, ("oversteward", "grantspider"))


class TestShape:
    def test_duplicate_capability_id_is_a_finding(self, raw):
        raw["capabilities"].append(dict(_cap(raw, "os.sow")))
        assert ("duplicate-id", "os.sow") in _findings(raw)

    def test_duplicate_invariant_id_is_a_finding(self, raw):
        raw["invariants"].append(dict(raw["invariants"][0]))
        assert ("duplicate-id", "I-1") in _findings(raw)

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_missing_target_shape_is_a_finding(self, raw, value):
        _cap(raw, "os.sow")["target_shape"] = value
        assert ("target-shape", "os.sow") in _findings(raw)

    def test_missing_current_shape_is_a_finding(self, raw):
        _cap(raw, "os.sow")["current_shape"] = ""
        assert ("current-shape", "os.sow") in _findings(raw)

    @pytest.mark.parametrize(
        ("field", "value"), [("kind", "service"), ("status", "shipped")]
    )
    def test_unknown_enum_is_a_finding(self, raw, field, value):
        _cap(raw, "os.sow")[field] = value
        assert ("unknown-value", "os.sow") in _findings(raw)

    def test_unknown_invariant_status_is_a_finding(self, raw):
        raw["invariants"][0]["status"] = "maybe"
        assert ("unknown-value", "I-1") in _findings(raw)

    @pytest.mark.parametrize("bad", ["OS.sow", "os_sow", "os.Sow", "xx.thing", "os."])
    def test_capability_id_must_be_product_dot_kebab(self, raw, bad):
        cap = _cap(raw, "os.sow")
        cap["id"] = bad
        assert ("id-format", bad) in _findings(raw)

    def test_product_naming_an_unknown_repo_is_a_finding(self, raw):
        raw["mission"]["products"][0]["repo"] = "nowhere"
        assert ("dangling-ref", "os") in _findings(raw)

    def test_a_list_field_given_a_string_is_refused_at_parse(self, raw):
        _cap(raw, "os.sow")["serves"] = "ag.research"
        with pytest.raises(MapError, match="serves"):
            parse(raw)


class TestLocations:
    def _marketing(self, locations: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": "ag.resource-page-outreach",
            "kind": "process",
            "purpose": "Monthly outreach to resource pages.",
            "status": "live",
            "locations": locations,
            "current_shape": "a timer and a vault note",
            "target_shape": "hold",
        }

    def test_marketing_capability_with_unverified_off_repo_locations_is_clean(self, raw):
        raw["capabilities"].append(
            self._marketing(
                [
                    {"type": "vault", "ref": "GTD/Projects/Outreach.md", "unverified": True},
                    {"type": "todoist", "ref": "Operator Steps", "unverified": True},
                    {"type": "dashboard", "ref": "Search Console", "unverified": True},
                    {"type": "timer", "ref": "oversteward:reports/x/brave.timer"},
                ]
            )
        )
        raw["capabilities"][-1]["kind"] = "content"
        assert _findings(raw) == []

    @pytest.mark.parametrize("loc_type", ["vault", "todoist", "dashboard"])
    def test_off_repo_location_must_be_marked_unverified(self, raw, loc_type):
        raw["capabilities"].append(self._marketing([{"type": loc_type, "ref": "somewhere"}]))
        assert ("location", "ag.resource-page-outreach") in _findings(raw)

    def test_repo_location_must_name_its_repo(self, raw):
        raw["capabilities"].append(
            self._marketing([{"type": "path", "ref": "reports/x/brave.timer"}])
        )
        assert ("location", "ag.resource-page-outreach") in _findings(raw)

    def test_repo_location_naming_an_unknown_repo_is_a_finding(self, raw):
        raw["capabilities"].append(
            self._marketing([{"type": "report", "ref": "nowhere:reports/x.md"}])
        )
        assert ("location", "ag.resource-page-outreach") in _findings(raw)

    def test_unknown_location_type_is_a_finding(self, raw):
        raw["capabilities"].append(self._marketing([{"type": "email", "ref": "x", "unverified": True}]))
        assert ("unknown-value", "ag.resource-page-outreach") in _findings(raw)
