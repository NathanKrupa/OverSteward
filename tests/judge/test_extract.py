# ABOUTME: Tests HTML → visible text — what the judge actually reads instead of markup.
# ABOUTME: Script/style bodies must never reach the model, and structure must survive as breaks.

from __future__ import annotations

from oversteward.judge.extract import visible_text


class TestNonVisibleContent:
    def test_script_bodies_are_dropped(self):
        html = "<p>Real words.</p><script>var tracker = 'analytics junk';</script>"
        text = visible_text(html)
        assert "Real words." in text
        assert "analytics junk" not in text
        assert "tracker" not in text

    def test_style_noscript_and_template_bodies_are_dropped(self):
        html = (
            "<style>.foundation{color:red}</style>"
            "<noscript>Enable JavaScript</noscript>"
            "<template><span>hidden clone</span></template>"
            "<p>Visible.</p>"
        )
        text = visible_text(html)
        assert text.strip() == "Visible."


class TestStructure:
    def test_headings_and_paragraphs_survive_as_line_breaks(self):
        html = "<h1>Grants for Housing</h1><p>First para.</p><p>Second para.</p>"
        lines = [line for line in visible_text(html).splitlines() if line]
        assert lines == ["Grants for Housing", "First para.", "Second para."]

    def test_inline_whitespace_is_collapsed(self):
        html = "<p>Too    many\n\n  spaces</p>"
        assert visible_text(html).strip() == "Too many spaces"

    def test_entities_are_unescaped(self):
        assert visible_text("<p>Smith &amp; Sons</p>").strip() == "Smith & Sons"

    def test_a_run_of_empty_blocks_never_becomes_a_wall_of_newlines(self):
        html = "<p>A</p><div></div><div></div><div></div><p>B</p>"
        assert "\n\n\n" not in visible_text(html)
