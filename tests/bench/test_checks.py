# ABOUTME: Tests for the bench's fail-closed publish checks — noindex meta on every page, _headers, robots.txt.
# ABOUTME: Each refusal reason is provoked by one negative fixture; a clean bench directory yields none.

from __future__ import annotations

from pathlib import Path

import pytest

from oversteward.bench.checks import has_noindex_meta, refusals

NOINDEX_PAGE = '<html><head><meta name="robots" content="noindex, nofollow"><title>a</title></head><body>a</body></html>'
INDEXABLE_PAGE = "<html><head><title>a</title></head><body>a</body></html>"
HEADERS = "/*\n  X-Robots-Tag: noindex, nofollow, noarchive\n"
ROBOTS = "User-agent: *\nDisallow: /\n"


def _bench(tmp_path: Path, **pages: str) -> Path:
    """A publishable bench directory: every page noindexed, _headers and robots.txt in place."""
    for name, html in pages.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    (tmp_path / "_headers").write_text(HEADERS, encoding="utf-8")
    (tmp_path / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    return tmp_path


class TestHasNoindexMeta:
    def test_reads_the_robots_meta_whatever_the_attribute_order(self):
        assert has_noindex_meta('<meta content="NOINDEX,nofollow" name="Robots">')

    def test_a_page_without_the_meta_is_indexable(self):
        assert not has_noindex_meta(INDEXABLE_PAGE)

    def test_a_robots_meta_that_allows_indexing_does_not_count(self):
        assert not has_noindex_meta('<meta name="robots" content="index, follow">')

    def test_noindex_must_be_a_whole_directive_not_a_substring(self):
        assert not has_noindex_meta('<meta name="robots" content="max-snippet:-1, noindexing">')

    def test_a_googlebot_meta_is_not_the_robots_meta(self):
        assert not has_noindex_meta('<meta name="googlebot" content="noindex">')


class TestRefusals:
    def test_a_clean_bench_directory_has_no_refusals(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, "b/index.html": NOINDEX_PAGE})
        assert refusals(bench) == ()

    def test_one_indexable_page_anywhere_in_the_tree_refuses_and_names_it(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, "deep/b.html": INDEXABLE_PAGE})
        reasons = refusals(bench)
        assert len(reasons) == 1
        assert "deep/b.html" in reasons[0]
        assert "noindex" in reasons[0]

    def test_a_missing_headers_file_refuses(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "_headers").unlink()
        assert any("_headers is missing" in reason for reason in refusals(bench))

    def test_a_headers_file_without_the_noindex_tag_refuses(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "_headers").write_text("/*\n  Cache-Control: no-store\n", encoding="utf-8")
        assert any("X-Robots-Tag" in reason for reason in refusals(bench))

    def test_a_noindex_tag_scoped_to_a_subpath_leaves_the_rest_indexable_and_refuses(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "_headers").write_text("/drafts/*\n  X-Robots-Tag: noindex\n", encoding="utf-8")
        assert any("X-Robots-Tag" in reason and "/*" in reason for reason in refusals(bench))

    def test_a_noindex_tag_under_the_catch_all_block_passes_whatever_else_is_there(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "_headers").write_text(
            "# bench headers\n/drafts/*\n  Cache-Control: no-store\n/*\n  Cache-Control: no-store\n  X-Robots-Tag: noindex, nofollow\n",
            encoding="utf-8",
        )
        assert refusals(bench) == ()

    def test_a_missing_robots_txt_refuses(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "robots.txt").unlink()
        assert any("robots.txt is missing" in reason for reason in refusals(bench))

    def test_a_robots_txt_that_does_not_disallow_everything_refuses(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "robots.txt").write_text("User-agent: *\nDisallow: /private/\n", encoding="utf-8")
        assert any("Disallow: /" in reason for reason in refusals(bench))

    def test_a_disallow_all_for_one_bot_only_leaves_every_other_crawler_in_and_refuses(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "robots.txt").write_text("User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n", encoding="utf-8")
        assert any("Disallow: /" in reason and "User-agent: *" in reason for reason in refusals(bench))

    def test_a_disallow_all_in_a_group_that_names_every_agent_passes(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "robots.txt").write_text(
            "# bench\nUser-agent: Googlebot\nUser-agent: *\nDisallow: /\n\nSitemap: https://x/s.xml\n", encoding="utf-8"
        )
        assert refusals(bench) == ()

    @pytest.mark.parametrize("name", ["v2.htm", "V2.HTML", "deep/Page.Htm"])
    def test_a_page_served_as_html_under_any_extension_spelling_is_checked(self, tmp_path, name):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, name: INDEXABLE_PAGE})
        reasons = refusals(bench)
        assert len(reasons) == 1
        assert name in reasons[0]

    def test_a_directory_with_no_html_at_all_refuses(self, tmp_path):
        bench = _bench(tmp_path)
        assert any("no .html" in reason for reason in refusals(bench))

    def test_every_problem_is_reported_not_just_the_first(self, tmp_path):
        bench = _bench(tmp_path, **{"a.html": INDEXABLE_PAGE, "b.html": INDEXABLE_PAGE})
        (bench / "_headers").unlink()
        (bench / "robots.txt").unlink()
        assert len(refusals(bench)) == 4

    def test_a_path_that_is_not_a_directory_refuses(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            refusals(tmp_path / "absent")
