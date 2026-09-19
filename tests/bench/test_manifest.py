# ABOUTME: Tests for judge-manifest building — the output validates through the judge's own reader.
# ABOUTME: Pairs are every unordered combination (n·(n−1)/2); the judge runs each in both orders itself.

from __future__ import annotations

import pytest
import yaml

from oversteward.bench.manifest import all_pairs, build_manifest, page_urls, urls_from_listing
from oversteward.judge.models import Rubric, manifest_from_mapping
from tests.bench.test_checks import NOINDEX_PAGE, _bench

URLS = (
    "https://smoke.ab-aigranthelper.pages.dev/v1/",
    "https://smoke.ab-aigranthelper.pages.dev/v2/",
    "https://smoke.ab-aigranthelper.pages.dev/v3/",
    "https://smoke.ab-aigranthelper.pages.dev/v4/",
)


class TestAllPairs:
    def test_four_urls_give_six_unordered_pairs(self):
        pairs = all_pairs(URLS)
        assert len(pairs) == 6
        assert len({frozenset(pair) for pair in pairs}) == 6
        assert all(a != b for a, b in pairs)

    @pytest.mark.parametrize("n", [0, 1, 2, 5, 7])
    def test_n_urls_give_n_choose_2_pairs(self, n):
        assert len(all_pairs(tuple(f"https://x/{i}/" for i in range(n)))) == n * (n - 1) // 2

    def test_every_url_appears_in_n_minus_1_pairs(self):
        pairs = all_pairs(URLS)
        for url in URLS:
            assert sum(url in pair for pair in pairs) == 3


class TestBuildManifest:
    def test_the_manifest_validates_through_the_judges_own_reader(self):
        data = build_manifest(name="round-1", page_type="foundation", urls=URLS, pairs=True)
        manifest = manifest_from_mapping(yaml.safe_load(yaml.safe_dump(data)))
        assert manifest.name == "round-1"
        assert manifest.page_types == {"foundation": URLS}
        assert len(manifest.pairs) == 6
        assert manifest.rubric is Rubric.SEEKER
        assert manifest.samples == 3

    def test_pairs_none_writes_no_pairs(self):
        data = build_manifest(name="r", page_type="foundation", urls=URLS, pairs=False)
        assert manifest_from_mapping(data).pairs == ()

    def test_the_rubric_and_samples_are_honoured(self):
        data = build_manifest(name="r", page_type="foundation", urls=URLS, pairs=False, rubric="design", samples=5)
        manifest = manifest_from_mapping(data)
        assert manifest.rubric is Rubric.DESIGN
        assert manifest.samples == 5

    def test_facts_attach_to_every_url_by_path(self):
        data = build_manifest(name="r", page_type="foundation", urls=URLS[:2], pairs=True, facts="facts/f.json")
        manifest = manifest_from_mapping(data)
        assert manifest.ground_truth == {URLS[0]: "facts/f.json", URLS[1]: "facts/f.json"}

    def test_no_facts_means_no_ground_truth_key(self):
        data = build_manifest(name="r", page_type="foundation", urls=URLS, pairs=False)
        assert "ground_truth" not in data

    def test_the_key_order_matches_the_example_manifest(self):
        data = build_manifest(name="r", page_type="foundation", urls=URLS, pairs=True, facts="f.json")
        assert list(data) == ["name", "samples", "rubric", "page_types", "pairs", "ground_truth"]

    def test_an_unknown_rubric_is_refused_before_anything_is_written(self):
        with pytest.raises(ValueError, match="rubric must be one of"):
            build_manifest(name="r", page_type="foundation", urls=URLS, pairs=False, rubric="vibes")

    def test_no_urls_is_refused(self):
        with pytest.raises(ValueError, match="no URLs"):
            build_manifest(name="r", page_type="foundation", urls=(), pairs=False)

    def test_a_duplicate_url_is_refused(self):
        with pytest.raises(ValueError, match="duplicate"):
            build_manifest(name="r", page_type="foundation", urls=(URLS[0], URLS[0]), pairs=True)


class TestPageUrls:
    def test_maps_index_html_to_directories_and_other_pages_to_extensionless_paths(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, "v2/index.html": NOINDEX_PAGE, "v3.html": NOINDEX_PAGE})
        assert page_urls("https://smoke.ab-aigranthelper.pages.dev", bench) == (
            "https://smoke.ab-aigranthelper.pages.dev/",
            "https://smoke.ab-aigranthelper.pages.dev/v2/",
            "https://smoke.ab-aigranthelper.pages.dev/v3",
        )

    def test_a_trailing_slash_on_the_base_is_not_doubled(self, tmp_path):
        bench = _bench(tmp_path, **{"v2/index.html": NOINDEX_PAGE})
        assert page_urls("https://x.pages.dev/", bench) == ("https://x.pages.dev/v2/",)


class TestUrlsFromListing:
    def test_reads_one_url_per_line_skipping_blanks_and_comments(self):
        text = "# round one\nhttps://a/\n\n  https://b/  \n#https://c/\n"
        assert urls_from_listing(text) == ("https://a/", "https://b/")

    def test_a_line_that_is_not_a_url_is_refused(self):
        with pytest.raises(ValueError, match="not a URL"):
            urls_from_listing("https://a/\nnot a url\n")
