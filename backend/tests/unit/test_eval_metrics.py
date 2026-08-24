"""Unit tests for the retrieval-evaluation metrics.

The eval harness itself needs the network and the ML stack; the arithmetic it
reports does not, so it is pinned here in the ordinary suite.
"""
from scripts import eval_metrics


class TestJudge:
    """Ground truth is answer-bearing text, so matching must survive re-chunking."""

    def test_needle_present(self):
        assert eval_metrics.judge("uses positional encoding for order",
                                  ["positional encoding"])

    def test_needle_absent(self):
        assert not eval_metrics.judge("uses recurrence for order", ["positional encoding"])

    def test_any_needle_is_enough(self):
        assert eval_metrics.judge("BEIR is a benchmark suite", ["Natural Questions", "BEIR"])

    def test_case_and_width_are_ignored(self):
        assert eval_metrics.judge("ALiBi biases attention", ["alibi"])
        assert eval_metrics.judge("ＢＥＩＲ", ["BEIR"])

    def test_whitespace_placement_is_ignored(self):
        # Extraction injects a separator between inline elements, which lands
        # inside Chinese sentences. Both forms have to count as the same text.
        assert eval_metrics.judge("類神經網路 中一種模仿", ["類神經網路中一種"])
        assert eval_metrics.judge("類神經網路中一種模仿", ["類神經網路 中一種"])


class TestRankMetrics:
    """Recall here is a hit rate; the cutoff has to be respected exactly."""

    def test_hit_at_k_respects_the_cutoff(self):
        relevance = [False, False, True]
        assert eval_metrics.hit_at_k(relevance, 2) == 0.0
        assert eval_metrics.hit_at_k(relevance, 3) == 1.0

    def test_hit_at_k_on_nothing_retrieved(self):
        assert eval_metrics.hit_at_k([], 5) == 0.0

    def test_precision_at_k(self):
        assert eval_metrics.precision_at_k([True, False, True, False], 4) == 0.5
        assert eval_metrics.precision_at_k([], 5) == 0.0

    def test_precision_divides_by_what_was_retrieved(self):
        # Only two results, one relevant: precision is 0.5, not 0.2.
        assert eval_metrics.precision_at_k([True, False], 5) == 0.5

    def test_reciprocal_rank(self):
        assert eval_metrics.reciprocal_rank([False, True, True]) == 0.5
        assert eval_metrics.reciprocal_rank([False, False]) == 0.0

    def test_reciprocal_rank_ignores_hits_past_the_cutoff(self):
        assert eval_metrics.reciprocal_rank([False, False, True], k=2) == 0.0

    def test_summarise_averages_over_queries(self):
        summary = eval_metrics.summarise({
            "a": [True, False],
            "b": [False, False],
        })
        assert summary["queries"] == 2
        assert summary["recall_at_1"] == 0.5
        assert summary["mrr_at_10"] == 0.5

    def test_percentile_uses_nearest_rank(self):
        assert eval_metrics.percentile([1, 2, 3, 4, 5], 0.5) == 3
        assert eval_metrics.percentile([], 0.5) == 0.0


class TestPollutionSignals:
    """The two things that outranked real passages before this work."""

    def test_navigation_is_boilerplate(self):
        assert eval_metrics.is_boilerplate("Toggle the table of contents Transformer")

    def test_prose_is_not_boilerplate(self):
        assert not eval_metrics.is_boilerplate("A transformer is a neural architecture.")

    def test_bibliography_entry_is_citation_like(self):
        assert eval_metrics.is_citation_like(
            "Vaswani, Ashish. Attention Is All You Need. arXiv:1706.03762 . doi:10.5555/1"
        )

    def test_one_marker_alone_is_not_enough(self):
        # An article may legitimately mention a DOI once; two markers is the bar.
        assert not eval_metrics.is_citation_like("The paper is registered under a doi: prefix.")


class TestIndexHealth:
    """The shape of the index the retriever has to work with."""

    def test_reports_lengths_and_problem_shares(self):
        health = eval_metrics.index_health(
            ["x" * 500, "y" * 40, "z" * 1200],
            chunk_size=512,
            headings=["A > B", None, "A"],
        )
        assert health["chunks"] == 3
        assert health["len_max"] == 1200
        assert health["share_tiny_lt_80"] == 1 / 3
        assert health["share_oversize_gt_2x"] == 1 / 3
        assert health["share_with_heading_path"] == 2 / 3

    def test_empty_index_does_not_divide_by_zero(self):
        health = eval_metrics.index_health([], chunk_size=512, headings=[])
        assert health["chunks"] == 0
        assert health["share_boilerplate"] == 0.0


class TestRetrievalPerformance:
    """Candidate pool and latency summaries stay comparable between runs."""

    def test_reports_latency_percentiles_and_candidate_means(self):
        summary = eval_metrics.retrieval_performance([
            {
                "latency_ms": 10.0,
                "dense_candidates": 6,
                "lexical_candidates": 2,
                "fused_candidates": 7,
            },
            {
                "latency_ms": 30.0,
                "dense_candidates": 10,
                "lexical_candidates": 4,
                "fused_candidates": 11,
            },
        ])

        assert summary["latency_ms_p50"] == 10.0
        assert summary["latency_ms_p95"] == 30.0
        assert summary["latency_ms_max"] == 30.0
        assert summary["dense_candidates_mean"] == 8.0
        assert summary["lexical_candidates_mean"] == 3.0
        assert summary["fused_candidates_mean"] == 9.0

    def test_empty_run_reports_zeroes(self):
        summary = eval_metrics.retrieval_performance([])
        assert summary["latency_ms_p95"] == 0.0
        assert summary["dense_candidates_mean"] == 0.0
