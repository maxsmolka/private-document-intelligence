from pdi.search.benchmark import retrieval_metrics


def test_retrieval_metrics_calculate_rank_quality() -> None:
    metrics = retrieval_metrics(
        [["a", "b"], ["x", "c"], []],
        [{"a"}, {"c"}, {"missing"}],
    )
    assert metrics["recall_at_1"] == 1 / 3
    assert metrics["recall_at_5"] == 2 / 3
    assert metrics["mrr"] == 0.5
    assert 0 < metrics["ndcg_at_10"] < 1
    assert metrics["zero_result_rate"] == 1 / 3
    assert metrics["wrong_top_result_rate"] == 1 / 3
