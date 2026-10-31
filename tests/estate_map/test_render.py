# ABOUTME: Tests for the rendered digest and its byte budget.
# ABOUTME: The budget is read from the map's policy, so a test oversizes the map rather than trusting a constant.

from __future__ import annotations

import copy

from oversteward.estate_map.model import parse
from oversteward.estate_map.render import budget_findings, digest


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
