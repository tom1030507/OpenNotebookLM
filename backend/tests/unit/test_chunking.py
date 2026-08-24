"""Unit tests for ChunkingService.

The chunker had no tests at all, which is how a Chinese page could become one
5,536-character chunk and a single sentence could reach 4,968 characters without
anything noticing.
"""
import pytest

from app.services.chunking import MIN_CHUNK_CHARS, ChunkingService
from app.utils.text import PAGE_SEPARATOR


ENGLISH = (
    "Attention assigns soft weights to the input tokens. "
    "The weights change at run time rather than being fixed. "
    "A query-key mechanism computes them from the token embeddings."
)

CHINESE = (
    "注意力機制是類神經網路中一種模仿認知注意力的技術。"
    "這種機制可以增強輸入資料中某些部分的權重，同時減弱其他部分的權重。"
    "資料中哪些部分更重要取決於上下文。"
    "可以透過梯度下降法對注意力機制進行訓練。"
)


class FakeDocument:
    """Stand-in for the Document row the chunker reads."""

    def __init__(self, content, source_type="url", meta_json=None, title="Doc"):
        self.content = content
        self.source_type = source_type
        self.meta_json = meta_json or {}
        self.title = title


class TestSentenceSplitting:
    """Splitting has to work in every language this app indexes."""

    def test_english_sentences_split_on_terminators(self):
        service = ChunkingService(chunk_size=512, chunk_overlap=0)
        assert len(service._split_sentences(ENGLISH)) == 3

    def test_chinese_sentences_split_on_ideographic_terminators(self):
        # The old regex needed `[.!?]` plus an ASCII capital, so this returned one
        # sentence and the whole page became a single chunk.
        service = ChunkingService(chunk_size=512, chunk_overlap=0)
        assert len(service._split_sentences(CHINESE)) == 4

    def test_abbreviation_does_not_end_a_sentence(self):
        service = ChunkingService()
        sentences = service._split_sentences("Dr. Vaswani wrote it. It was 2017.")
        assert sentences[0] == "Dr. Vaswani wrote it."

    def test_abbreviation_suffix_inside_a_word_ends_a_sentence(self):
        service = ChunkingService()

        assert service._split_sentences("fooApprox. Next.") == [
            "fooApprox.",
            "Next.",
        ]

    def test_initials_do_not_end_a_sentence(self):
        service = ChunkingService()
        assert len(service._split_sentences("The U.S. team shipped it.")) == 1

    def test_decimals_do_not_end_a_sentence(self):
        service = ChunkingService()
        assert len(service._split_sentences("It scored 3.14 overall.")) == 1

    def test_closing_quote_stays_with_its_sentence(self):
        service = ChunkingService()
        sentences = service._split_sentences("他說「這樣可以。」然後離開了。")
        assert sentences == ["他說「這樣可以。」", "然後離開了。"]

    def test_bounded_scanner_preserves_language_boundary_semantics(self):
        service = ChunkingService(chunk_size=20, chunk_overlap=0)
        text = "Dr. Ada met the U.S. team. The score was 3.14 overall. Done!"

        chunks = service._chunk_text_content(text)

        assert [chunk["text"] for chunk in chunks] == [
            "Dr. Ada met the",
            "U.S. team.",
            "The score was 3.14",
            "overall.\nDone!",
        ]

    def test_cjk_closing_marks_continue_as_a_separate_bounded_piece(self):
        service = ChunkingService(chunk_size=10, chunk_overlap=0)
        text = "a" * 9 + "。』NEXT."

        assert list(service._iter_sentences(text)) == [
            "a" * 9 + "。",
            "』",
            "NEXT.",
        ]
        assert [chunk["text"] for chunk in service._chunk_text_content(text)] == [
            "a" * 9 + "。",
            "』\nNEXT.",
        ]


class TestChunkSize:
    """No chunk may exceed the configured size."""

    def test_chinese_text_is_split_into_several_chunks(self):
        service = ChunkingService(chunk_size=60, chunk_overlap=0)
        chunks = service._chunk_text_content(CHINESE)
        assert len(chunks) > 1
        assert all(len(chunk["text"]) <= 60 for chunk in chunks)

    def test_an_oversized_single_sentence_is_cut(self):
        # One sentence, no internal terminator: the old code let it through whole.
        sentence = " ".join(["alpha"] * 400) + "."
        service = ChunkingService(chunk_size=200, chunk_overlap=0)
        chunks = service._chunk_text_content(sentence)
        assert len(chunks) > 1
        assert max(len(chunk["text"]) for chunk in chunks) <= 200

    def test_a_sentence_with_no_break_at_all_is_still_cut(self):
        service = ChunkingService(chunk_size=100, chunk_overlap=0)
        chunks = service._chunk_text_content("x" * 350)
        assert all(len(chunk["text"]) <= 100 for chunk in chunks)

    def test_hard_split_preserves_word_and_comma_boundaries(self):
        service = ChunkingService(chunk_size=10, chunk_overlap=0)

        assert list(service._hard_split("abcdefgh,ijklmnop")) == [
            "abcdefgh",
            ",ijklmnop",
        ]
        assert list(service._hard_split("alpha beta gamma")) == [
            "alpha",
            "beta gamma",
        ]

    def test_the_limit_holds_with_overlap_enabled(self):
        # The overlap used to be prepended to a fresh chunk without rechecking
        # that the piece which forced the flush still fitted, so a chunk could run
        # `chunk_overlap` characters over the limit.
        paragraphs = "\n".join(
            " ".join(["sentence %d word" % index] * 30) + "." for index in range(12)
        )
        service = ChunkingService(chunk_size=200, chunk_overlap=50)
        chunks = service._chunk_text_content(paragraphs)
        assert len(chunks) > 1
        assert max(len(chunk["text"]) for chunk in chunks) <= 200

    def test_the_limit_holds_for_chinese_with_overlap(self):
        service = ChunkingService(chunk_size=120, chunk_overlap=30)
        chunks = service._chunk_text_content(CHINESE * 4)
        assert len(chunks) > 1
        assert max(len(chunk["text"]) for chunk in chunks) <= 120

    def test_empty_content_yields_no_chunks(self):
        assert ChunkingService()._chunk_text_content("   ") == []


class TestOverlap:
    """The configured overlap must actually be used."""

    def test_overlap_carries_text_between_chunks(self):
        service = ChunkingService(chunk_size=120, chunk_overlap=40)
        chunks = service._chunk_text_content(ENGLISH)
        assert len(chunks) > 1
        # Something from the end of chunk one reappears at the start of chunk two.
        tail_word = chunks[0]["text"].split()[-1]
        assert tail_word in chunks[1]["text"]

    def test_zero_overlap_carries_nothing(self):
        service = ChunkingService(chunk_size=120, chunk_overlap=0)
        chunks = service._chunk_text_content(ENGLISH)
        joined = "".join(chunk["text"] for chunk in chunks)
        # With no overlap the pieces do not repeat, so the join is no longer than
        # the source plus the separators the packer inserts.
        assert len(joined) <= len(ENGLISH) + len(chunks)


class TestHeadings:
    """Section context is stored, not thrown away."""

    SECTIONED = (
        "# Transformer\n"
        "An intro paragraph that is long enough to stand as its own chunk here.\n"
        "\n"
        "## Architecture\n"
        "The encoder and the decoder each stack identical blocks of layers.\n"
        "\n"
        "### Attention\n"
        "Scaled dot-product attention compares queries against keys.\n"
    )

    def test_heading_path_is_a_path_not_a_title(self):
        chunks = ChunkingService(chunk_size=512, chunk_overlap=0)._chunk_text_content(self.SECTIONED)
        paths = [chunk["metadata"]["heading_path"] for chunk in chunks]
        assert "Transformer > Architecture > Attention" in paths

    def test_section_is_the_last_heading(self):
        chunks = ChunkingService(chunk_size=512, chunk_overlap=0)._chunk_text_content(self.SECTIONED)
        sections = {chunk["metadata"]["section"] for chunk in chunks}
        assert "Attention" in sections

    def test_a_chunk_never_straddles_a_section(self):
        chunks = ChunkingService(chunk_size=4000, chunk_overlap=0)._chunk_text_content(self.SECTIONED)
        assert len(chunks) == 3

    def test_heading_lines_are_not_indexed_as_content(self):
        chunks = ChunkingService(chunk_size=512, chunk_overlap=0)._chunk_text_content(self.SECTIONED)
        assert not any(chunk["text"].startswith("#") for chunk in chunks)

    def test_attacker_sized_heading_candidate_is_bounded_content(self):
        service = ChunkingService(chunk_size=100, chunk_overlap=0)
        text = "# " + "x" * 250

        chunks = service._chunk_text_content(text)

        assert chunks[0]["text"].startswith("# ")
        assert all(chunk["metadata"]["heading_path"] is None for chunk in chunks)


class TestOffsets:
    """Offsets have to be usable, which means monotonic."""

    def test_start_offsets_do_not_go_backwards(self):
        service = ChunkingService(chunk_size=100, chunk_overlap=20)
        chunks = service._chunk_text_content(ENGLISH + " " + ENGLISH)
        starts = [chunk["metadata"]["start_char"] for chunk in chunks]
        assert starts == sorted(starts)

    def test_offsets_point_inside_the_source(self):
        text = ENGLISH
        chunks = ChunkingService(chunk_size=100, chunk_overlap=0)._chunk_text_content(text)
        for chunk in chunks:
            assert 0 <= chunk["metadata"]["start_char"] <= len(text)
            assert chunk["metadata"]["end_char"] <= len(text) + 1

    def test_short_line_passes_through_with_its_original_end_offset(self):
        text = "First sentence. Second sentence."
        service = ChunkingService(chunk_size=512, chunk_overlap=0)

        chunks = service._chunk_text_content(text)

        assert [chunk["text"] for chunk in chunks] == [text]
        assert chunks[0]["metadata"]["start_char"] == 0
        assert chunks[0]["metadata"]["end_char"] == len(text)

    @pytest.mark.parametrize(
        ("text", "chunk_size"),
        [
            ("First sentence. Second sentence.", 16),
            ("alpha beta gamma delta", 6),
        ],
    )
    def test_long_line_fragment_offsets_select_their_exact_source_text(
        self,
        text,
        chunk_size,
    ):
        service = ChunkingService(chunk_size=chunk_size, chunk_overlap=0)

        blocks = list(service._to_blocks(text))
        chunks = service._chunk_text_content(text)

        assert len(blocks) >= 2
        for block in blocks:
            assert text[block.start:block.end] == block.text
        for chunk in chunks:
            start = chunk["metadata"]["start_char"]
            end = chunk["metadata"]["end_char"]
            assert text[start:end] == chunk["text"]


class TestRuntMerging:
    """A fragment too short to answer anything is folded into a neighbour."""

    def test_short_trailing_line_is_merged(self):
        text = "A paragraph long enough to become a chunk of its own here.\nok\n"
        chunks = ChunkingService(chunk_size=512, chunk_overlap=0)._chunk_text_content(text)
        assert len(chunks) == 1
        assert "ok" in chunks[0]["text"]

    def test_a_single_short_document_is_still_indexed(self):
        chunks = ChunkingService()._chunk_text_content("Short.")
        assert len(chunks) == 1
        assert len(chunks[0]["text"]) < MIN_CHUNK_CHARS


class TestPdfPages:
    """page_num comes from the pages array, not from a guess."""

    def test_page_number_is_looked_up_by_offset(self):
        pages = [
            {"page_num": 1, "text": "First page prose that runs on for a while here."},
            {"page_num": 2, "text": "Second page prose that also runs on for a while."},
            {"page_num": 3, "text": "Third page prose closing out the little document."},
        ]
        document = FakeDocument(
            content=PAGE_SEPARATOR.join(page["text"] for page in pages),
            source_type="pdf",
            meta_json={"pages": pages},
        )
        service = ChunkingService(chunk_size=60, chunk_overlap=0)
        chunks = service._chunk_pdf_content(document)

        for block in service._to_blocks(document.content):
            assert document.content[block.start:block.end] == block.text

        assert {chunk["metadata"]["page_num"] for chunk in chunks} == {1, 2, 3}
        assert chunks[0]["metadata"]["page_num"] == 1
        assert chunks[-1]["metadata"]["page_num"] == 3

    def test_without_a_pages_array_page_num_stays_unset(self):
        document = FakeDocument(content=ENGLISH, source_type="pdf", meta_json={"num_pages": 2})
        chunks = ChunkingService()._chunk_pdf_content(document)
        assert all(chunk["metadata"].get("page_num") is None for chunk in chunks)


class TestUrlChunking:
    """URL chunks fall back to the page title only above the first heading."""

    def test_title_is_used_when_there_is_no_heading(self):
        document = FakeDocument(content=ENGLISH, title="Attention (machine learning)")
        chunks = ChunkingService()._chunk_url_content(document)
        assert chunks[0]["metadata"]["heading_path"] == "Attention (machine learning)"

    def test_a_real_heading_path_is_not_overwritten(self):
        document = FakeDocument(
            content="## Architecture\nThe encoder and decoder stack identical blocks.\n",
            title="Transformer",
        )
        chunks = ChunkingService()._chunk_url_content(document)
        assert chunks[0]["metadata"]["heading_path"] == "Architecture"
