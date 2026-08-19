"""Unit tests for URLAdapter text extraction.

Extraction had no tests, which is how a `from readability import Readability`
that raises ImportError went unnoticed: the flag it set was simply False, so
every page fell back to `soup.body` and the index filled up with navigation,
language lists and reference entries.
"""
from bs4 import BeautifulSoup

from app.adapters.url import URLAdapter


# A miniature of the structure that caused the trouble: chrome and a reference
# list wrapped around a short article.
WIKI_LIKE = """
<html><head><title>Transformer (deep learning) - Wikipedia</title></head>
<body>
  <nav id="p-lang"><ul><li>Afrikaans</li><li>العربية</li><li>日本語</li></ul></nav>
  <div id="toc">Toggle the table of contents</div>
  <div class="ambox"><p>This article needs more citations. Please help improve it.</p></div>
  <main>
    <div id="mw-content-text">
      <p>A <a href="/wiki/transformer">transformer</a> is a neural architecture.</p>
      <h2>Architecture<span class="mw-editsection">[edit]</span></h2>
      <p>The encoder and the decoder each stack identical blocks.<sup class="reference">[1]</sup></p>
      <table>
        <tr><th>Variant</th><th>Note</th></tr>
        <tr><td>Linformer</td><td>low-rank attention</td></tr>
      </table>
      <ol class="references">
        <li>Vaswani, Ashish. Attention Is All You Need. arXiv:1706.03762. doi:10.5555/1</li>
      </ol>
    </div>
  </main>
  <footer><p>Privacy Policy</p></footer>
</body></html>
"""

CHINESE_INLINE = """
<html><body><main><p>注意力機制是<a href="/x">類神經網路</a>中一種模仿認知注意力的技術。</p></main></body></html>
"""

MATH_PAGE = """
<html><body><main>
<p>網路計算出滿足
<span class="mwe-math-element"><math><annotation>{\\displaystyle \\sum _{i}w_{i}=1}</annotation></math></span>
的非負軟權重。</p>
</main></body></html>
"""

DIV_ONLY_PAGE = """
<html><body><main><div>Some sites put their prose straight inside a div with no
paragraph element at all, and it still has to be extracted.</div></main></body></html>
"""


def extract(html: str) -> str:
    """Run the adapter's extraction over a literal document.

    Args:
        html: Page source.

    Returns:
        Extracted text.
    """
    adapter = URLAdapter()
    soup = BeautifulSoup(html, "html.parser")
    adapter._strip_non_content(soup)
    adapter._inline_math(soup)
    return adapter._extract_main_content(soup, "test://page")["text"]


class TestBoilerplateRemoval:
    """The furniture that used to outrank real passages has to be gone."""

    def test_language_list_is_dropped(self):
        text = extract(WIKI_LIKE)
        assert "Afrikaans" not in text
        assert "日本語" not in text

    def test_table_of_contents_toggle_is_dropped(self):
        assert "Toggle the table of contents" not in extract(WIKI_LIKE)

    def test_maintenance_banner_is_dropped(self):
        assert "needs more citations" not in extract(WIKI_LIKE)

    def test_reference_list_is_dropped(self):
        # Reference entries were the single worst pollutant: dense, numerous and
        # topically close to the article, so they filled the top of every result.
        text = extract(WIKI_LIKE)
        assert "arXiv:1706.03762" not in text
        assert "Vaswani" not in text

    def test_edit_link_is_dropped_from_the_heading(self):
        assert "[edit]" not in extract(WIKI_LIKE)

    def test_footer_boilerplate_is_dropped(self):
        assert "Privacy Policy" not in extract(WIKI_LIKE)


class TestContentPreservation:
    """Stripping furniture must not take content with it."""

    def test_prose_survives(self):
        assert "is a neural architecture" in extract(WIKI_LIKE)

    def test_headings_become_markdown(self):
        # The chunker reads these back to rebuild a section path.
        assert "## Architecture" in extract(WIKI_LIKE)

    def test_table_content_survives(self):
        # readability discards tables outright, which is why an explicit content
        # container is preferred over it.
        assert "Linformer" in extract(WIKI_LIKE)

    def test_table_row_is_one_line_with_its_cells(self):
        lines = extract(WIKI_LIKE).split("\n")
        assert any("Linformer | low-rank attention" == line for line in lines)

    def test_prose_inside_a_bare_div_is_not_lost(self):
        assert "straight inside a div" in extract(DIV_ONLY_PAGE)


class TestChineseSpacing:
    """A separator between inline elements lands inside Chinese sentences."""

    def test_inline_link_does_not_split_a_chinese_term(self):
        text = extract(CHINESE_INLINE)
        assert "注意力機制是類神經網路中一種模仿認知注意力的技術。" in text

    def test_math_is_folded_inline_instead_of_becoming_its_own_lines(self):
        text = extract(MATH_PAGE)
        # One line, not four one-character ones.
        assert len([line for line in text.split("\n") if line.strip()]) == 1
        assert "非負軟權重" in text
        assert "displaystyle" not in text


class TestNoiseLines:
    """Line-level filtering, never mid-sentence substitution."""

    def test_a_whole_line_of_boilerplate_is_dropped(self):
        adapter = URLAdapter()
        assert adapter._is_noise_line("Privacy Policy")
        assert adapter._is_noise_line("Jump to content")
        assert adapter._is_noise_line("12")

    def test_a_sentence_about_boilerplate_is_kept(self):
        # Substituting these globally used to delete the phrase out of an article
        # that was about privacy policies.
        adapter = URLAdapter()
        line = "The Privacy Policy of a data broker is rarely read in full."
        assert not adapter._is_noise_line(line)
        assert adapter._clean_text(line) == line

    def test_a_bibliography_line_needs_two_markers(self):
        adapter = URLAdapter()
        assert adapter._is_noise_line("Smith, J. Title. arXiv:1234.5678 . doi:10.1/x")
        assert not adapter._is_noise_line("The registry issues a doi: for each dataset.")

    def test_paragraph_breaks_survive_cleaning(self):
        adapter = URLAdapter()
        cleaned = adapter._clean_text("First paragraph.\n\nSecond paragraph.")
        assert cleaned == "First paragraph.\n\nSecond paragraph."
