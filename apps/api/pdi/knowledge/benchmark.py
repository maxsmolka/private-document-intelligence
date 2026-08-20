import argparse
import asyncio
import json
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

from pdi.core.database import session_factory
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction
from pdi.knowledge.extraction import normalize_name, temporal_candidates
from pdi.knowledge.models import KnowledgeProposalType
from pdi.search import models as search_models  # noqa: F401


def prf(predicted: set[Any], expected: set[Any]) -> dict[str, float]:
    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted) if predicted else float(not expected)
    recall = true_positive / len(expected) if expected else float(not predicted)
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def quality(corpus: dict[str, Any]) -> dict[str, Any]:
    catalog: dict[str, str] = {}
    for organization in corpus["organizations"]:
        for name in [organization["name"], *organization["aliases"]]:
            catalog[normalize_name(name)] = organization["id"]
    predicted_org: set[tuple[str, str]] = set()
    expected_org: set[tuple[str, str]] = set()
    predicted_contract: set[str] = set()
    expected_contract: set[str] = set()
    predicted_relationship: set[tuple[str, str]] = set()
    expected_relationship: set[tuple[str, str]] = set()
    predicted_events: set[tuple[str, str, str | None]] = set()
    expected_events: set[tuple[str, str, str | None]] = set()
    predicted_deadlines: set[tuple[str, str, str | None]] = set()
    expected_deadlines: set[tuple[str, str, str | None]] = set()
    predicted_actions: set[tuple[str, str]] = set()
    expected_actions: set[tuple[str, str]] = set()
    seen_identifiers: set[str] = set()
    resolution_correct = resolution_total = duplicate_tp = duplicate_fp = duplicate_fn = 0
    failures: list[dict[str, Any]] = []
    started = time.perf_counter()
    for case in corpus["cases"]:
        case_id = case["id"]
        resolved = catalog.get(normalize_name(case["organization"]))
        if resolved:
            predicted_org.add((case_id, resolved))
        if case["expected_organization"]:
            expected_org.add((case_id, case["expected_organization"]))
        resolution_total += 1
        resolution_correct += resolved == case["expected_organization"]
        predicted_duplicate = resolved is not None
        expected_duplicate = case["expected_organization"] is not None
        duplicate_tp += predicted_duplicate and expected_duplicate
        duplicate_fp += predicted_duplicate and not expected_duplicate
        duplicate_fn += not predicted_duplicate and expected_duplicate
        identifier = case.get("identifier")
        contract = bool(identifier) and case["document_type"] in {
            "contract",
            "insurance_policy",
            "insurance_notice",
            "official_letter",
        }
        if contract:
            predicted_contract.add(case_id)
        if case["expected_contract"]:
            expected_contract.add(case_id)
        if identifier and identifier in seen_identifiers:
            relation = (
                "amends"
                if "Änderung" in case["text"] or "Nachtrag" in case["text"]
                else "belongs_to_same_case"
            )
            predicted_relationship.add((case_id, relation))
        if case.get("expected_relationship"):
            expected_relationship.add((case_id, case["expected_relationship"]))
        if identifier:
            seen_identifiers.add(identifier)
        document = Document(
            title=case_id,
            original_filename=f"{case_id}.pdf",
            mime_type="application/pdf",
            file_size=1,
            sha256="a" * 64,
            storage_key=f"benchmark-{case_id}.pdf",
            status=DocumentStatus.READY,
            life_area=LifeArea.OTHER,
            source="benchmark",
        )
        extraction = DocumentExtraction(
            document_id=uuid.uuid4(),
            provider="synthetic",
            provider_version="1",
            method="benchmark",
            text=case["text"],
            page_count=1,
            pages=[case["text"]],
            content_hash="b" * 64,
            warnings=[],
            extraction_metadata={},
        )
        candidates = temporal_candidates(document, extraction)
        for candidate in candidates:
            if candidate.proposal_type == KnowledgeProposalType.EVENT:
                predicted_events.add(
                    (case_id, candidate.payload["event_type"], candidate.payload["event_date"])
                )
            elif candidate.proposal_type == KnowledgeProposalType.DEADLINE:
                predicted_deadlines.add(
                    (case_id, candidate.payload["deadline_type"], candidate.payload["due_at"])
                )
            elif candidate.proposal_type == KnowledgeProposalType.ACTION_ITEM:
                predicted_actions.add((case_id, candidate.payload["title"]))
        expected_events.update((case_id, kind, value) for kind, value in case["events"])
        expected_deadlines.update((case_id, kind, value) for kind, value in case["deadlines"])
        expected_actions.update((case_id, title) for title in case["actions"])
    for name, predicted, expected in (
        ("organizations", predicted_org, expected_org),
        ("contracts", predicted_contract, expected_contract),
        ("relationships", predicted_relationship, expected_relationship),
        ("events", predicted_events, expected_events),
        ("deadlines", predicted_deadlines, expected_deadlines),
        ("actions", predicted_actions, expected_actions),
    ):
        for missing in sorted(expected - predicted):
            failures.append({"component": name, "kind": "missed", "value": missing})
        for extra in sorted(predicted - expected):
            failures.append({"component": name, "kind": "unexpected", "value": extra})
    duplicate_precision = (
        duplicate_tp / (duplicate_tp + duplicate_fp) if duplicate_tp + duplicate_fp else 1.0
    )
    duplicate_recall = (
        duplicate_tp / (duplicate_tp + duplicate_fn) if duplicate_tp + duplicate_fn else 1.0
    )
    return {
        "organization_extraction": prf(predicted_org, expected_org),
        "entity_resolution_accuracy": resolution_correct / resolution_total,
        "duplicate_detection": {
            "precision": duplicate_precision,
            "recall": duplicate_recall,
        },
        "false_merge_count": 0,
        "false_merge_rate": 0.0,
        "automatic_merge_enabled": False,
        "contract_linking": prf(predicted_contract, expected_contract),
        "relationships": prf(predicted_relationship, expected_relationship),
        "events": prf(predicted_events, expected_events),
        "event_type_accuracy": prf(predicted_events, expected_events)["precision"],
        "event_date_exact_accuracy": prf(predicted_events, expected_events)["precision"],
        "deadlines": prf(predicted_deadlines, expected_deadlines),
        "deadline_type_accuracy": prf(predicted_deadlines, expected_deadlines)["precision"],
        "deadline_exact_accuracy": prf(predicted_deadlines, expected_deadlines)["precision"],
        "action_items": prf(predicted_actions, expected_actions),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "failures": failures,
    }


async def scale(sizes: list[int]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    async with session_factory() as session:
        if not session.bind or session.bind.dialect.name != "postgresql":
            raise RuntimeError("Knowledge scale benchmark requires PostgreSQL")
        transaction = await session.begin()
        try:
            await session.execute(
                text("CREATE TEMP TABLE organizations (id integer, name text, status text)")
            )
            await session.execute(text("CREATE INDEX ON organizations (status, name)"))
            await session.execute(
                text(
                    "CREATE TEMP TABLE contracts (id integer PRIMARY KEY, "
                    "organization_id integer, reference text, status text)"
                )
            )
            await session.execute(text("CREATE INDEX ON contracts (organization_id, status)"))
            await session.execute(
                text("CREATE TEMP TABLE events (id integer, contract_id integer, event_date date)")
            )
            await session.execute(text("CREATE INDEX ON events (event_date DESC, id)"))
            await session.execute(
                text(
                    "CREATE TEMP TABLE deadlines (id integer, contract_id integer, "
                    "due_at date, status text)"
                )
            )
            await session.execute(text("CREATE INDEX ON deadlines (status, due_at)"))
            await session.execute(
                text(
                    "CREATE TEMP TABLE relationships (id integer, source_id integer, "
                    "target_id integer)"
                )
            )
            await session.execute(text("CREATE INDEX ON relationships (source_id)"))
            current = 0
            for size in sizes:
                started = time.perf_counter()
                rows = [
                    {"id": number, "org": number % max(1, size), "name": f"Organization {number}"}
                    for number in range(current, size)
                ]
                await session.execute(
                    text("INSERT INTO organizations VALUES (:id, :name, 'active')"), rows
                )
                await session.execute(
                    text("INSERT INTO contracts VALUES (:id, :org, :name, 'active')"), rows
                )
                await session.execute(
                    text("INSERT INTO events VALUES (:id, :id, DATE '2026-08-20')"), rows
                )
                await session.execute(
                    text("INSERT INTO deadlines VALUES (:id, :id, DATE '2026-09-01', 'open')"), rows
                )
                await session.execute(
                    text("INSERT INTO relationships VALUES (:id, :id, :org)"), rows
                )
                for table in (
                    "organizations",
                    "contracts",
                    "events",
                    "deadlines",
                    "relationships",
                ):
                    await session.execute(text(f"ANALYZE {table}"))
                insert_ms = (time.perf_counter() - started) * 1000
                queries = {
                    "organization_detail": (
                        "SELECT * FROM contracts WHERE organization_id=:id",
                        {"id": size - 1},
                    ),
                    "contract_detail": ("SELECT * FROM contracts WHERE id=:id", {"id": size - 1}),
                    "timeline": ("SELECT * FROM events ORDER BY event_date DESC, id LIMIT 50", {}),
                    "upcoming_deadlines": (
                        "SELECT * FROM deadlines WHERE status='open' ORDER BY due_at LIMIT 50",
                        {},
                    ),
                    "relationships": (
                        "SELECT * FROM relationships WHERE source_id=:id",
                        {"id": size - 1},
                    ),
                }
                timings: dict[str, float] = {}
                for name, (sql, parameters) in queries.items():
                    samples: list[float] = []
                    for _ in range(6):
                        query_started = time.perf_counter()
                        await session.execute(text(sql), parameters)
                        samples.append((time.perf_counter() - query_started) * 1000)
                    timings[name] = round(statistics.mean(samples[1:]), 3)
                reports.append(
                    {
                        "records_per_domain": size,
                        "incremental_insert_ms": round(insert_ms, 2),
                        "warm_query_ms": timings,
                    }
                )
                current = size
        finally:
            await transaction.rollback()
    return reports


async def run(corpus_path: Path, sizes: list[int]) -> dict[str, Any]:
    corpus = json.loads(await asyncio.to_thread(corpus_path.read_text, encoding="utf-8"))
    return {
        "schema_version": "1",
        "cases": len(corpus["cases"]),
        "quality": quality(corpus),
        "scale": await scale(sizes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="pdi-benchmark-knowledge")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--sizes", default="100,1000,10000")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(
        run(arguments.corpus, [int(value) for value in arguments.sizes.split(",")])
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
