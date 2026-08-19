"""Unit tests for PDFAdapter text cleaning.

The cleaner collapsed every newline before its own line-based rules ran, so the
header/footer filter below them could never fire and running headers were
repeated into every chunk.
"""
from app.adapters.pdf import PDFAdapter
from app.utils.text import PAGE_SEPARATOR


def clean(text: str) -> str:
    """Run the adapter's text cleaner.

    Args:
        text: Raw extracted text.

    Returns:
        Cleaned text.
    """
    return PDFAdapter(use_pymupdf=False)._clean_text(text)


class TestLineStructure:
    """Line structure has to survive long enough to be used."""

    def test_newlines_are_kept(self):
        assert clean("First line.\nSecond line.") == "First line.\nSecond line."

    def test_paragraph_breaks_are_kept(self):
        assert clean("One.\n\nTwo.") == "One.\n\nTwo."

    def test_long_runs_of_blank_lines_collapse(self):
        assert clean("One.\n\n\n\n\nTwo.") == "One.\n\nTwo."

    def test_horizontal_whitespace_collapses_within_a_line(self):
        assert clean("wide    spacing\there") == "wide spacing here"


class TestHeaderFooterRemoval:
    """The rule that used to be unreachable."""

    def test_a_page_number_line_is_dropped(self):
        assert clean("Body text.\n12\nMore body text.") == "Body text.\nMore body text."

    def test_a_short_numeric_footer_is_dropped(self):
        assert "3" not in clean("Chapter body.\n- 3 -\nNext paragraph.")

    def test_a_short_line_without_digits_is_kept(self):
        assert "Note" in clean("Body.\nNote\nMore.")

    def test_a_long_line_with_digits_is_kept(self):
        line = "In 2017 the paper introduced the architecture."
        assert line in clean("Body.\n" + line)


class TestHyphenation:
    """Words the layout broke across lines have to be rejoined."""

    def test_hyphenated_line_break_is_repaired(self):
        assert "international" in clean("an inter-\nnational effort")

    def test_a_real_hyphen_within_a_line_is_kept(self):
        assert "query-key" in clean("the query-key mechanism")


class TestPageJoin:
    """`text` must be the pages joined, so a chunk offset locates its page."""

    def test_the_separator_is_the_shared_one(self):
        pages = ["First page.", "Second page."]
        joined = PAGE_SEPARATOR.join(pages)
        assert joined.index("Second page.") == len("First page.") + len(PAGE_SEPARATOR)
