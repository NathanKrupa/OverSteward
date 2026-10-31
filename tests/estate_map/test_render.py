# ABOUTME: Tests for the rendered digest, the per-repo slices, and their byte budgets.
# ABOUTME: Budgets are read from the map's policy, so a test resizes the map rather than trusting a constant.

from __future__ import annotations

import copy

from oversteward.estate_map.model import parse
from oversteward.estate_map.render import (
    budget_findings,
    digest,
    repo_slice,
    slice_budget_findings,
    slice_repos,
)


def test_digest_carries_the_north_star_and_one_line_per_capability(raw):
    text = digest(parse(raw))
    assert "A+ grant-writing tools for the servants of the poor." in text
    assert "- `os.sow` · live · Deploys the dev family." in text
    lines = [line for line in text.splitlines() if line.startswith("- `")]
    assert len(lines) == len(raw["capabilities"])


def test_digest_is_deterministic(raw):
    assert digest(parse(raw)) == digest(parse(copy.deepcopy(raw)))


def test_digest_within_budget_is_clean(raw):
    estate = parse(raw)
    assert budget_findings(estate, digest(estate)) == []


def test_digest_over_budget_is_a_finding(raw):
    template = raw["capabilities"][2]
    for n in range(600):
        cap = copy.deepcopy(template)
        cap["id"] = f"os.capability-{n}"
        raw["capabilities"].append(cap)
    estate = parse(raw)
    text = digest(estate)
    assert len(text.encode()) > 14000
    findings = budget_findings(estate, text)
    assert [(f.check, f.subject) for f in findings] == [("digest-budget", "digest")]


def test_digest_exactly_at_the_budget_is_clean(raw):
    text = digest(parse(raw))
    raw["policy"]["digest_budget_bytes"] = len(text.encode("utf-8"))
    estate = parse(raw)
    assert digest(estate) == text
    assert budget_findings(estate, text) == []


def test_budget_is_read_from_the_policy(raw):
    raw["policy"]["digest_budget_bytes"] = 100
    estate = parse(raw)
    assert budget_findings(estate, digest(estate))


def test_budget_counts_bytes_not_characters(raw):
    text = digest(parse(raw))
    # Room for two more bytes. " →" is two characters but four bytes, so a
    # character count fits the budget and a byte count does not.
    raw["policy"]["digest_budget_bytes"] = len(text.encode("utf-8")) + 2
    raw["mission"]["north_star"] += " →"
    grown = parse(raw)
    grown_text = digest(grown)
    assert len(grown_text) == len(text) + 2
    assert len(grown_text.encode("utf-8")) == len(text.encode("utf-8")) + 4
    assert [f.check for f in budget_findings(grown, grown_text)] == ["digest-budget"]


# --- per-repo slices ----------------------------------------------------------


def _cap_ids(text: str) -> list[str]:
    return [line.split("`")[1] for line in text.splitlines() if line.startswith("- `")]


def test_slice_repos_are_the_repos_capabilities_belong_to_or_claim(raw):
    raw["capabilities"][0]["claims"] = {"oversteward": ["docs/"]}
    raw["mission"]["products"].append({"id": "wp", "serves": "clients", "repo": "wphelper"})
    assert slice_repos(parse(raw)) == ("aigranthelper", "grantspider", "oversteward")


def test_slice_carries_the_north_star_and_only_that_repos_capabilities(raw):
    text = repo_slice(parse(raw), "grantspider")
    assert "A+ grant-writing tools for the servants of the poor." in text
    assert "# Estate map — grantspider" in text
    assert _cap_ids(text) == ["gs.website-resolution"]
    assert "- `gs.website-resolution` · live · Finds each funder's website." in text
    assert "  - one module → hold" in text


def test_slice_includes_a_capability_that_claims_paths_in_the_repo(raw):
    raw["capabilities"][1]["claims"]["oversteward"] = ["docs/funders.md"]
    assert _cap_ids(repo_slice(parse(raw), "oversteward")) == ["gs.website-resolution", "os.sow"]


def test_slice_names_the_target_shape_when_one_is_planned(raw):
    text = repo_slice(parse(raw), "oversteward")
    assert "  - six modules → fold the deploy into one verb" in text


def test_slice_lists_seams_the_repo_produces_or_consumes(raw):
    raw["seams"].append(
        {
            "id": "S-2",
            "label": "oversteward → fiscus",
            "producer": ["oversteward"],
            "consumer": ["fiscus"],
            "flows": "lessons",
            "cite": "c",
        }
    )
    gs = repo_slice(parse(raw), "grantspider")
    ag = repo_slice(parse(raw), "aigranthelper")
    os_ = repo_slice(parse(raw), "oversteward")
    assert "- S-1 grantspider → aigranthelper (data): views" in gs
    assert "- S-1 grantspider → aigranthelper (data): views" in ag
    assert "S-1" not in os_
    assert "- S-2 oversteward → fiscus: lessons" in os_
    assert "S-2" not in gs


def test_slice_lists_invariants_its_capabilities_or_seams_cite(raw):
    ag = repo_slice(parse(raw), "aigranthelper")
    assert "- I-1: a (x)" in ag  # cited by ag.research
    assert "- I-2: b (y)" in ag  # cited by seam S-1, which AG consumes
    os_ = repo_slice(parse(raw), "oversteward")
    assert "I-1" not in os_ and "I-2" not in os_


def test_slice_omits_a_retired_invariant_even_when_cited(raw):
    raw["seams"][0]["invariants"].append("I-3")
    assert "I-3" not in repo_slice(parse(raw), "grantspider")


def test_slice_lists_liabilities_by_capability_seam_or_owner(raw):
    raw["liabilities"] += [
        {"id": "G2", "text": "seam rot", "owner": "fiscus", "tracking": "t2"},
        {"id": "G3", "text": "ops debt", "owner": "oversteward (ops)", "tracking": "t3"},
    ]
    raw["seams"][0]["liabilities"] = ["G2"]
    gs = repo_slice(parse(raw), "grantspider")
    assert "- G1 (aigranthelper; t): drift" in gs  # via gs.website-resolution
    assert "- G2 (fiscus; t2): seam rot" in gs  # via seam S-1
    os_ = repo_slice(parse(raw), "oversteward")
    assert "- G3 (oversteward (ops); t3): ops debt" in os_  # via owner
    assert "G1" not in os_ and "G2" not in os_
    assert "G3" not in gs


def test_slice_with_nothing_touching_says_so(raw):
    text = repo_slice(parse(raw), "oversteward")
    assert "## Seams\n\nnone\n" in text
    assert "## Invariants\n\nnone\n" in text
    assert "## Liabilities\n\nnone\n" in text


def test_slice_is_deterministic(raw):
    assert repo_slice(parse(raw), "grantspider") == repo_slice(
        parse(copy.deepcopy(raw)), "grantspider"
    )


def test_slice_within_budget_is_clean(raw):
    estate = parse(raw)
    assert slice_budget_findings(estate, "grantspider", repo_slice(estate, "grantspider")) == []


def test_slice_exactly_at_the_budget_is_clean(raw):
    text = repo_slice(parse(raw), "grantspider")
    raw["policy"]["slice_budget_bytes"] = len(text.encode("utf-8"))
    estate = parse(raw)
    assert slice_budget_findings(estate, "grantspider", text) == []


def test_slice_one_byte_over_the_budget_is_a_finding_naming_the_repo(raw):
    text = repo_slice(parse(raw), "grantspider")
    raw["policy"]["slice_budget_bytes"] = len(text.encode("utf-8")) - 1
    estate = parse(raw)
    findings = slice_budget_findings(estate, "grantspider", text)
    assert [(f.check, f.subject) for f in findings] == [("slice-budget", "grantspider")]


def test_slice_budget_is_separate_from_the_digest_budget(raw):
    raw["policy"]["digest_budget_bytes"] = 100
    estate = parse(raw)
    assert slice_budget_findings(estate, "grantspider", repo_slice(estate, "grantspider")) == []


def test_slice_keeps_the_first_sentence_of_the_current_shape(raw):
    raw["capabilities"][1]["current_shape"] = (
        "3 modules, 900 lines; 4 feature PRs in 90 days. `resolver.py` is 600 lines of it."
    )
    text = repo_slice(parse(raw), "grantspider")
    assert "  - 3 modules, 900 lines; 4 feature PRs in 90 days. → hold" in text
    assert "resolver.py" not in text


def test_slice_keeps_a_single_sentence_shape_whole(raw):
    # A version number, a decimal and a lower-case "e.g. two" are not sentence ends.
    shape = "v2.0 of one module, 1.5 kB; e.g. two files"
    raw["capabilities"][1]["current_shape"] = shape
    assert f"  - {shape} → hold" in repo_slice(parse(raw), "grantspider")


def test_slice_cuts_before_a_parenthesis_or_code_span_opening_a_sentence(raw):
    for second in ("(L-GS-3) has none.", "`x.py` has none."):
        raw["capabilities"][1]["current_shape"] = f"one module. {second}"
        assert "  - one module. → hold" in repo_slice(parse(raw), "grantspider")
