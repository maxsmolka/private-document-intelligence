import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from pdi.intelligence.providers import DeterministicIntelligenceProvider, DocumentContext
from pdi.intelligence.schemas import IntelligenceResult

DEADLINE_FIELDS = {"payment_due_date", "cancellation_deadline", "renewal_date"}
BUDGETS = {
    "classification_precision": 0.90,
    "extraction_precision": 0.90,
    "field_recall": 0.85,
    "deadline_recall": 0.90,
    "maximum_false_contract_rate": 0.0,
    "maximum_organization_false_positives": 0,
    "maximum_proposal_noise_per_document": 0.50,
}


def score_sets(expected: set[str], actual: set[str]) -> tuple[int, int, int]:
    return len(expected & actual), len(actual - expected), len(expected - actual)


def extracted_fields(result: IntelligenceResult) -> set[str]:
    candidates = [
        *result.organizations,
        *result.dates,
        *result.amounts,
        *result.identifiers,
        *result.semantic_facts,
    ]
    return {f"{item.field_name}={item.normalized_value}" for item in candidates}


def expected_fields(expected: dict[str, Any]) -> set[str]:
    fields = set(expected.get("fields", []))
    fields.update(f"organization={value}" for value in expected.get("organizations", []))
    fields.update(f"identifier={value}" for value in expected.get("identifiers", []))
    return fields


def predicts_contract(result: IntelligenceResult, text: str) -> bool:
    document_type = result.document_type.normalized_value if result.document_type else ""
    if document_type in {"contract", "rental_contract", "insurance_policy"}:
        return True
    explicit = bool(
        re.search(
            r"\b(?:Mietvertrag|Mietverhältnis|Versicherungsvertrag|Versicherungsbeginn|"
            r"Vertragsbeginn|Vertragsende|Versicherungsschein|Police|Arbeitsvertrag|"
            r"Altersvorsorgevertrag)\b",
            text,
            re.I,
        )
    )
    if explicit:
        return True
    has_contract_identifier = any(
        str(item.structured_value.get("kind", ""))
        .casefold()
        .startswith(("vertrag", "versicherungsschein", "police"))
        for item in result.identifiers
    )
    return has_contract_identifier and document_type in {
        "insurance_notice",
        "insurance_statement",
        "pension_statement",
    }


async def run(corpus_path: Path) -> dict[str, Any]:
    corpus: list[dict[str, Any]] = json.loads(
        await asyncio.to_thread(corpus_path.read_text, encoding="utf-8")
    )
    provider = DeterministicIntelligenceProvider()
    classification_correct = field_tp = field_fp = field_fn = 0
    deadline_tp = deadline_fn = false_contracts = contract_negatives = 0
    organization_false_positives = 0
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for sample in corpus:
        text = str(sample["text"])
        result = await provider.analyze(
            DocumentContext(
                text=text,
                pages=[text],
                original_filename=f"{sample['id']}.txt",
                extraction_method=str(sample.get("extraction_method", "native")),
            )
        )
        expected = sample["expected"]
        expected_type = expected.get("document_type")
        actual_type = result.document_type.normalized_value if result.document_type else None
        classification_correct += actual_type == expected_type
        expected_values = expected_fields(expected)
        actual_values = extracted_fields(result)
        tp, fp, fn = score_sets(expected_values, actual_values)
        field_tp += tp
        field_fp += fp
        field_fn += fn
        expected_deadlines = {
            item for item in expected_values if item.split("=", 1)[0] in DEADLINE_FIELDS
        }
        actual_deadlines = {
            item for item in actual_values if item.split("=", 1)[0] in DEADLINE_FIELDS
        }
        deadline_match, _, deadline_missing = score_sets(expected_deadlines, actual_deadlines)
        deadline_tp += deadline_match
        deadline_fn += deadline_missing
        predicted_contract = predicts_contract(result, text)
        expected_contract = bool(expected.get("contract", False))
        if not expected_contract:
            contract_negatives += 1
            false_contracts += predicted_contract
        expected_organizations = set(expected.get("organizations", []))
        actual_organizations = {item.normalized_value for item in result.organizations}
        organization_false_positives += len(actual_organizations - expected_organizations)
        rows.append(
            {
                "id": sample["id"],
                "expected_type": expected_type,
                "actual_type": actual_type,
                "field_tp": tp,
                "field_fp": fp,
                "field_fn": fn,
                "expected_contract": expected_contract,
                "predicted_contract": predicted_contract,
            }
        )
    precision = field_tp / (field_tp + field_fp) if field_tp + field_fp else 1.0
    recall = field_tp / (field_tp + field_fn) if field_tp + field_fn else 1.0
    deadline_recall = (
        deadline_tp / (deadline_tp + deadline_fn) if deadline_tp + deadline_fn else 1.0
    )
    metrics = {
        "classification_precision": classification_correct / len(corpus),
        "extraction_precision": precision,
        "field_recall": recall,
        "field_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_contract_rate": false_contracts / contract_negatives if contract_negatives else 0.0,
        "deadline_recall": deadline_recall,
        "organization_false_positives": organization_false_positives,
        "proposal_noise_per_document": field_fp / len(corpus),
    }
    budget_pass = (
        metrics["classification_precision"] >= BUDGETS["classification_precision"]
        and metrics["extraction_precision"] >= BUDGETS["extraction_precision"]
        and metrics["field_recall"] >= BUDGETS["field_recall"]
        and metrics["deadline_recall"] >= BUDGETS["deadline_recall"]
        and metrics["false_contract_rate"] <= BUDGETS["maximum_false_contract_rate"]
        and metrics["organization_false_positives"]
        <= BUDGETS["maximum_organization_false_positives"]
        and metrics["proposal_noise_per_document"] <= BUDGETS["maximum_proposal_noise_per_document"]
    )
    return {
        "corpus_version": "1",
        "provider": provider.name,
        "provider_version": provider.provider_version,
        "schema_version": provider.schema_version,
        "samples": len(corpus),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "metrics": metrics,
        "budgets": BUDGETS,
        "budget_pass": budget_pass,
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="pdi-benchmark-intelligence")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--enforce-budgets", action="store_true")
    arguments = parser.parse_args()
    report = asyncio.run(run(arguments.corpus))
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if arguments.enforce_budgets and not report["budget_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
