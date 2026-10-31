# ABOUTME: Tests for estate-map status — attributing open issues and PRs to capabilities, never storing it.
# ABOUTME: Priority is the contract: an explicit Capability line, then a PR's changed files, then named paths.

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from oversteward.estate_map import model
from oversteward.estate_map.checkouts import CouldNotLook
from oversteward.estate_map.status import (
    EXPLICIT,
    FILES,
    PATHS,
    UNMAPPED,
    Item,
    attribute,
    build,
    explicit_ids,
    gather,
    lines,
    mentioned_paths,
    status_repos,
    to_dict,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def estate(raw):
    raw["capabilities"].append(
        {
            "id": "gs.crawl",
            "kind": "code",
            "purpose": "Crawls funder sites.",
            "status": "live",
            "claims": {"grantspider": ["src/grantspider/services/crawl.py", "src/grantspider/cli"]},
            "current_shape": "x",
            "target_shape": "hold",
        }
    )
    return model.parse(raw)


def _issue(body: str = "", title: str = "t", repo: str = "grantspider", number: int = 1) -> Item:
    return Item(repo=repo, kind="issue", number=number, title=title, body=body)


def _pr(files: tuple[str, ...], body: str = "", number: int = 9) -> Item:
    return Item(repo="grantspider", kind="pr", number=number, title="t", body=body, files=files)


# --- explicit lines --------------------------------------------------------


def test_explicit_line_is_read_with_markdown_decoration():
    body = "## Scope\n- **Capability:** `gs.crawl`\nmore"
    assert explicit_ids(body) == ("gs.crawl",)


def test_explicit_line_may_name_several_capabilities():
    assert explicit_ids("Capability: gs.crawl, os.sow") == ("gs.crawl", "os.sow")


def test_explicit_line_mid_sentence_is_not_read():
    assert explicit_ids("this touches the Capability: gs.crawl in passing") == ()


def test_explicit_line_beats_path_inference(estate):
    item = _issue("Capability: gs.crawl\n\nEdit `src/grantspider/services/website_resolver.py`.")
    got = attribute(item, estate)
    assert got.capabilities == ("gs.crawl",)
    assert got.via == EXPLICIT


def test_an_unknown_explicit_id_is_reported_and_inference_still_runs(estate):
    item = _issue("Capability: gs.nope\n\nEdit services/website_resolver.py.")
    got = attribute(item, estate)
    assert got.unknown_ids == ("gs.nope",)
    assert got.capabilities == ("gs.website-resolution",)
    assert got.via == PATHS


# --- path inference --------------------------------------------------------


def test_a_body_naming_a_partial_path_maps_by_its_claim(estate):
    got = attribute(_issue("The bug is in `services/website_resolver.py:120`."), estate)
    assert got.capabilities == ("gs.website-resolution",)
    assert got.via == PATHS


def test_a_body_naming_services_website_resolver_maps_on_the_live_map():
    live = model.load(ROOT / "estate-map.yaml")
    got = attribute(_issue("Fix services/website_resolver.py"), live)
    assert got.capabilities == ("gs.website-resolution",)


def test_a_body_naming_nothing_is_unmapped(estate):
    got = attribute(_issue("Make the thing faster.", title="perf: faster"), estate)
    assert got.capabilities == ()
    assert got.via == UNMAPPED


def test_a_path_in_the_title_counts(estate):
    got = attribute(_issue(title="fix: src/grantspider/services/crawl.py drops pages"), estate)
    assert got.capabilities == ("gs.crawl",)


def test_a_path_under_a_directory_claim_maps(estate):
    got = attribute(_issue("see grantspider/cli/foundation.py"), estate)
    assert got.capabilities == ("gs.crawl",)


def test_the_longest_claim_wins(raw):
    raw["capabilities"][1]["claims"] = {"grantspider": ["src/grantspider/services"]}
    raw["policy"]["explicit_only"] = {}
    raw["capabilities"][2]["claims"] = {"grantspider": ["src/grantspider/services/crawl.py"]}
    estate = model.parse(raw)
    got = attribute(_issue("edit src/grantspider/services/crawl.py"), estate)
    assert got.capabilities == ("os.sow",)


def test_a_claim_in_another_repo_does_not_match(estate):
    got = attribute(_issue("Fix services/website_resolver.py", repo="aigranthelper"), estate)
    assert got.via == UNMAPPED


def test_a_github_blob_link_names_its_path(estate):
    body = "https://github.com/NathanKrupa/grantspider/blob/main/src/grantspider/services/crawl.py#L4"
    assert attribute(_issue(body), estate).capabilities == ("gs.crawl",)


def test_mentioned_paths_strip_punctuation_and_line_numbers():
    found = mentioned_paths("(`./services/a.py:12`), apps/x/, b.md.")
    assert found == ["services/a.py", "apps/x", "b.md"]


def test_an_item_naming_two_capabilities_maps_to_both(estate):
    got = attribute(_issue("services/website_resolver.py and services/crawl.py"), estate)
    assert got.capabilities == ("gs.website-resolution", "gs.crawl")


# --- PR changed files ------------------------------------------------------


def test_pr_changed_files_beat_body_paths(estate):
    item = _pr(("src/grantspider/services/crawl.py",), body="mentions services/website_resolver.py")
    got = attribute(item, estate)
    assert got.capabilities == ("gs.crawl",)
    assert got.via == FILES


def test_pr_changed_files_match_only_as_full_paths(estate):
    item = _pr(("services/website_resolver.py",))
    assert attribute(item, estate).via == UNMAPPED


def test_pr_files_matching_nothing_fall_back_to_body_paths(estate):
    item = _pr(("uv.lock",), body="services/crawl.py")
    got = attribute(item, estate)
    assert got.capabilities == ("gs.crawl",)
    assert got.via == PATHS


def test_explicit_beats_pr_files(estate):
    item = _pr(("src/grantspider/services/crawl.py",), body="Capability: os.sow")
    assert attribute(item, estate).capabilities == ("os.sow",)


# --- report ----------------------------------------------------------------


def test_report_counts_unmapped_and_multi_mapped_per_repo(estate):
    items = [
        _issue("services/website_resolver.py and services/crawl.py", number=1),
        _issue("nothing", number=2),
        _issue("services/crawl.py", number=3),
    ]
    report = build(estate, ["grantspider"], items)
    data = to_dict(report)
    assert data["repos"]["grantspider"] == {"issues": 3, "prs": 0, "unmapped": 1}
    assert data["multi_mapped"] == 1
    assert [e["number"] for e in data["capabilities"]["gs.crawl"]] == [1, 3]
    assert [e["number"] for e in data["unmapped"]] == [2]


def test_lines_print_the_unmapped_line_and_list_its_items(estate):
    report = build(estate, ["grantspider"], [_issue("nothing", title="lonely", number=42)])
    text = "\n".join(lines(report))
    assert "unmapped: 1" in text
    assert "#42 lonely" in text
    assert "grantspider: 1 open (1 issues, 0 PRs), 1 unmapped (100%)" in text


def test_lines_name_each_capability_with_its_items_by_repo(estate):
    report = build(estate, ["grantspider"], [_issue("services/crawl.py", title="crawl bug", number=7)])
    text = "\n".join(lines(report))
    assert "gs.crawl: 1 open" in text
    assert "  grantspider\n    issue #7 crawl bug [paths]" in text


def test_a_repo_with_no_open_items_reads_as_zero_measured(estate):
    text = "\n".join(lines(build(estate, ["grantspider"], [])))
    assert "grantspider: 0 open (0 issues, 0 PRs), 0 unmapped" in text


# --- gathering -------------------------------------------------------------


def test_gather_reports_a_failed_repo_as_could_not_look():
    def fetch(repo):
        raise CouldNotLook(f"{repo}: gh failed")

    items, blind = gather(["grantspider"], fetch)
    assert items == []
    assert blind == ["grantspider: gh failed"]


def test_status_repos_default_to_every_repo_with_claims(estate):
    assert status_repos(estate, None) == ["oversteward", "grantspider"]
    assert status_repos(estate, "aigranthelper") == ["aigranthelper"]


def test_an_absolute_path_maps_by_the_claim_it_contains(estate):
    body = "Traceback at /home/natha/grantspider/src/grantspider/services/crawl.py line 4"
    assert attribute(_issue(body), estate).capabilities == ("gs.crawl",)


def test_a_partial_path_with_an_unrelated_prefix_does_not_map(estate):
    assert attribute(_issue("see tests/services/website_resolver.py"), estate).via == UNMAPPED


def test_one_shared_directory_segment_is_not_a_match(raw):
    raw["capabilities"][2]["claims"] = {"grantspider": ["apps/docs/"]}
    got = attribute(_issue("see docs/STAGING_WORKFLOW.md"), model.parse(raw))
    assert got.via == UNMAPPED


def test_a_bare_filename_one_capability_claims_maps(estate):
    assert attribute(_issue("crawl.py is slow"), estate).capabilities == ("gs.crawl",)


def test_a_bare_filename_several_capabilities_claim_is_unmapped(raw):
    raw["capabilities"][2]["claims"] = {"grantspider": ["src/grantspider/other/website_resolver.py"]}
    got = attribute(_issue("website_resolver.py is slow"), model.parse(raw))
    assert got.via == UNMAPPED


# --- writers ---------------------------------------------------------------

_BODIES = [
    "Capability: gs.crawl",
    "## Scope\n  Capability: gs.crawl\n",
    "- **Capability:** `gs.crawl`",
    "> capability: gs.crawl",
    "no line here",
    "the Capability: gs.crawl mid-sentence",
    "Capabilities: gs.crawl",
]


def _preflight_pattern() -> str:
    skill = (ROOT / "shared" / "skills" / "dispatch" / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"grep -Eiq '([^']+)'`", skill)
    assert match, "the dispatch preflight no longer greps for the Capability line"
    return match.group(1)


@pytest.mark.parametrize("body", _BODIES)
def test_the_dispatch_preflight_grep_agrees_with_status(body):
    grep = subprocess.run(["grep", "-Eiq", _preflight_pattern()], input=body, text=True, check=False)
    assert (grep.returncode == 0) == bool(explicit_ids(body)), body


def test_the_architect_brief_template_carries_a_capability_line():
    card = (ROOT / "shared" / "agents" / "architect.md").read_text(encoding="utf-8")
    brief = card[card.rindex("Dispatch brief\n") :]
    assert explicit_ids(brief) == ("os.dispatch",)
