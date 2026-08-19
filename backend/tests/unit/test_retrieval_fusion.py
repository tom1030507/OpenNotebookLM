"""Unit tests for the lexical scoring and rank fusion used by hybrid retrieval."""
from app.services import retrieval


class TestTokenize:
    """The tokenizer has to work for Chinese, not just for English."""

    def test_latin_words_are_lowercased(self):
        assert retrieval.tokenize("Positional Encoding") == ["positional", "encoding"]

    def test_hyphenated_terms_stay_one_token(self):
        assert "query-key" in retrieval.tokenize("the query-key mechanism")

    def test_chinese_becomes_character_bigrams(self):
        # A whitespace split returns the whole run as one token, which is why the
        # old keyword score was always zero for Chinese.
        assert retrieval.tokenize("注意力機制") == ["注意", "意力", "力機", "機制"]

    def test_mixed_script_yields_both_kinds(self):
        tokens = retrieval.tokenize("專家混合（Mixture of Experts）架構")
        assert "mixture" in tokens and "experts" in tokens
        assert "專家" in tokens

    def test_single_character_run_survives(self):
        assert retrieval.tokenize("值") == ["值"]

    def test_empty_text_yields_nothing(self):
        assert retrieval.tokenize("") == []


class TestBm25:
    """BM25 has to rank the document that actually contains the rare term."""

    def test_rare_term_outranks_common_ones(self):
        documents = [
            retrieval.tokenize("transformers use attention over sequences"),
            retrieval.tokenize("the Longformer extends attention to long context"),
            retrieval.tokenize("attention is computed over sequences of tokens"),
        ]
        scores = retrieval.bm25_scores(retrieval.tokenize("Longformer"), documents)
        assert scores[1] > scores[0]
        assert scores[1] > scores[2]

    def test_chinese_query_scores_the_chinese_document(self):
        documents = [
            retrieval.tokenize("旋轉位置編碼把位置資訊寫進注意力"),
            retrieval.tokenize("byte pair encoding splits text into tokens"),
        ]
        scores = retrieval.bm25_scores(retrieval.tokenize("什麼是旋轉位置編碼"), documents)
        assert scores[0] > scores[1]

    def test_unmatched_query_scores_zero(self):
        documents = [retrieval.tokenize("attention over sequences")]
        assert retrieval.bm25_scores(retrieval.tokenize("Longformer"), documents) == [0.0]

    def test_empty_inputs_are_safe(self):
        assert retrieval.bm25_scores([], [["a"], ["b"]]) == [0.0, 0.0]
        assert retrieval.bm25_scores(["a"], []) == []


class TestFusion:
    """Fusion must not let list agreement bury a strong single-list hit."""

    def test_summed_rrf_rewards_agreement(self):
        scores = retrieval.reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
        assert scores["a"] == scores["b"]

    def test_best_rank_beats_a_pile_of_mid_ranked_agreement(self):
        # "answer" is rank 1 in the lexical list only. The others sit mid-list in
        # both, so plain summed RRF ranks them all above it — the failure this
        # fusion exists to avoid.
        dense = ["d%d" % i for i in range(1, 16)]
        lexical = ["answer"] + dense[3:]

        summed = retrieval.reciprocal_rank_fusion([dense, lexical])
        assert sum(1 for key, value in summed.items()
                   if key != "answer" and value > summed["answer"]) > 5

        # Under best-rank fusion nothing outranks it: only another list's rank-1
        # can tie, and no amount of mid-list agreement gets above that.
        fused = retrieval.fuse_rankings([dense, lexical])
        better = [key for key, value in fused.items() if value > fused["answer"]]
        assert better == [], better
        assert fused["answer"] == fused["d1"]

    def test_agreement_still_breaks_ties(self):
        # Both are rank 1 somewhere, so the sum decides: "b" also appears second
        # in the other list.
        fused = retrieval.fuse_rankings([["a", "x"], ["b", "a"]])
        assert fused["a"] > fused["b"]

    def test_unknown_ids_are_absent(self):
        assert "z" not in retrieval.fuse_rankings([["a"], ["b"]])


class TestDedupe:
    """Chunk overlap must not spend several slots on one passage."""

    @staticmethod
    def _tokens(item):
        return retrieval.tokenize(item["text"])

    def test_near_duplicate_is_dropped(self):
        items = [
            {"text": "attention assigns soft weights to the input tokens"},
            {"text": "attention assigns soft weights to the input tokens too"},
            {"text": "byte pair encoding splits text into subword units"},
        ]
        kept = retrieval.dedupe_near_duplicates(items, self._tokens, threshold=0.8)
        assert len(kept) == 2
        assert kept[0] is items[0] and kept[1] is items[2]

    def test_order_is_preserved(self):
        items = [{"text": "alpha one"}, {"text": "beta two"}, {"text": "gamma three"}]
        kept = retrieval.dedupe_near_duplicates(items, self._tokens, threshold=0.9)
        assert [item["text"] for item in kept] == [item["text"] for item in items]

    def test_threshold_of_one_disables_dedupe(self):
        items = [{"text": "same text"}, {"text": "same text"}]
        assert len(retrieval.dedupe_near_duplicates(items, self._tokens, threshold=1.0)) == 2
