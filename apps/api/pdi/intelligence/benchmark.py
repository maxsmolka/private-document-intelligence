import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from pdi.intelligence.providers import DeterministicIntelligenceProvider, DocumentContext


def score_sets(expected: set[str], actual: set[str]) -> tuple[int, int, int]:
    return len(expected & actual), len(actual - expected), len(expected - actual)


async def run(corpus_path: Path) -> dict[str, Any]:
    rendered = await asyncio.to_thread(corpus_path.read_text, encoding="utf-8")
    corpus: list[dict[str, Any]] = json.loads(rendered)
    provider = DeterministicIntelligenceProvider()
    classification_correct = 0
    classification_total = 0
    true_positive = false_positive = false_negative = 0
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for sample in corpus:
        text = str(sample["text"])
        result = await provider.analyze(
            DocumentContext(
                text=text, pages=[text], original_filename="sample.txt", extraction_method="native"
            )
        )
        expected = sample["expected"]
        expected_type = expected.get("document_type")
        actual_type = result.document_type.normalized_value if result.document_type else None
        if expected_type is not None:
            classification_total += 1
            classification_correct += actual_type == expected_type
        expected_values = set(expected.get("amounts", [])) | set(expected.get("identifiers", []))
        actual_values = {item.normalized_value for item in [*result.amounts, *result.identifiers]}
        tp, fp, fn = score_sets(expected_values, actual_values)
        true_positive += tp
        false_positive += fp
        false_negative += fn
        rows.append(
            {
                "id": sample["id"],
                "expected_type": expected_type,
                "actual_type": actual_type,
                "tp": tp,
                "fp": fp,
                "fn": fn,
            }
        )
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    )
    return {
        "provider": provider.name,
        "provider_version": provider.provider_version,
        "samples": len(corpus),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "classification_accuracy": classification_correct / classification_total,
        "field_precision": precision,
        "field_recall": recall,
        "field_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="pdi-benchmark-intelligence")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(run(arguments.corpus))
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
