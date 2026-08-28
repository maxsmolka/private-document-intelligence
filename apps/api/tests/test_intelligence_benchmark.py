from pathlib import Path

from pdi.intelligence.benchmark import run


async def test_versioned_intelligence_corpus_stays_within_quality_budgets() -> None:
    report = await run(Path(__file__).parent / "fixtures" / "intelligence_corpus_v1.json")

    assert report["corpus_version"] == "1"
    assert report["budget_pass"] is True
    assert report["metrics"]["false_contract_rate"] == 0
    assert report["metrics"]["organization_false_positives"] == 0
