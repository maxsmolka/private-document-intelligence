from pdi.search.benchmark import character_trigrams, retrieval_metrics, trigram_similarity


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


def test_character_trigram_candidate_is_deterministic() -> None:
    assert character_trigrams("Lohn-Abrechnung") == character_trigrams("lohn abrechnung")
    assert trigram_similarity("Versicherungspolice", "Versicherungsschein") > 0
    assert trigram_similarity("Kochrezept", "Versicherungsschein") == 0
