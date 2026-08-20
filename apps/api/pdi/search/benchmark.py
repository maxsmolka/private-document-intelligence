import argparse
import asyncio
import json
import math
import statistics
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text

from pdi.core.database import session_factory
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction
from pdi.search.service import refresh_search_index, search_documents

BENCHMARK_NAMESPACE = uuid.UUID("2cb2e9b0-364c-48b8-86df-9b9cce781f20")


def retrieval_metrics(rankings: list[list[str]], relevant: list[set[str]]) -> dict[str, float]:
    recall_at_1 = recall_at_5 = reciprocal_rank = ndcg = zero_results = wrong_top = 0.0
    for ranking, expected in zip(rankings, relevant, strict=True):
        recall_at_1 += len(set(ranking[:1]) & expected) / len(expected)
        recall_at_5 += len(set(ranking[:5]) & expected) / len(expected)
        first = next((index + 1 for index, item in enumerate(ranking) if item in expected), None)
        reciprocal_rank += 1 / first if first else 0
        gains = [1.0 if item in expected else 0.0 for item in ranking[:10]]
        dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
        ideal = sum(1 / math.log2(index + 2) for index in range(min(len(expected), 10)))
        ndcg += dcg / ideal if ideal else 1
        zero_results += not ranking
        wrong_top += bool(ranking) and ranking[0] not in expected
    count = len(rankings) or 1
    return {
        "recall_at_1": recall_at_1 / count,
        "recall_at_5": recall_at_5 / count,
        "mrr": reciprocal_rank / count,
        "ndcg_at_10": ndcg / count,
        "zero_result_rate": zero_results / count,
        "wrong_top_result_rate": wrong_top / count,
    }


async def seed_document(session: Any, sample: dict[str, Any]) -> Document:
    document_id = uuid.uuid5(BENCHMARK_NAMESPACE, sample["id"])
    pages = sample["pages"]
    canonical: dict[str, object] = {
        "organization": {"name": sample["organization"]},
        "identifier": {"kind": "reference", "value": sample["identifier"]},
    }
    if amount := sample.get("amount"):
        canonical["amount"] = amount
    document = Document(
        id=document_id,
        title=sample["title"],
        original_filename=f"{sample['id']}.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256=uuid.uuid5(BENCHMARK_NAMESPACE, sample["id"] + "hash").hex * 2,
        storage_key=f"retrieval-benchmark-{document_id}.pdf",
        status=DocumentStatus.READY,
        life_area=LifeArea(sample["life_area"]),
        document_type=sample["document_type"],
        document_date=date.fromisoformat(sample["document_date"]),
        canonical_metadata=canonical,
        source="retrieval_benchmark",
    )
    body = "\n\n".join(pages)
    document.extraction = DocumentExtraction(
        id=uuid.uuid5(BENCHMARK_NAMESPACE, sample["id"] + "extraction"),
        provider="synthetic",
        provider_version="1",
        method="benchmark",
        text=body,
        page_count=len(pages),
        pages=pages,
        content_hash=uuid.uuid5(BENCHMARK_NAMESPACE, sample["id"] + "text").hex * 2,
        warnings=[],
        extraction_metadata={},
    )
    session.add(document)
    await refresh_search_index(session, document, document.extraction, flush=False, assume_new=True)
    return document


async def quality_benchmark(session: Any, corpus: dict[str, Any]) -> dict[str, Any]:
    ids = {
        sample["id"]: str(uuid.uuid5(BENCHMARK_NAMESPACE, sample["id"]))
        for sample in corpus["documents"]
    }
    for sample in corpus["documents"]:
        await seed_document(session, sample)
    await session.flush()
    rankings: list[list[str]] = []
    expected_sets: list[set[str]] = []
    latencies: list[float] = []
    exact_success = exact_total = 0
    outcomes: list[dict[str, Any]] = []
    for case in corpus["queries"]:
        filters = case.get("filters", {})
        started = time.perf_counter()
        results, _ = await search_documents(
            session,
            query=case["query"],
            limit=10,
            offset=0,
            document_status=None,
            life_area=LifeArea(filters["life_area"]) if filters.get("life_area") else None,
            document_type=filters.get("document_type"),
            date_from=date.fromisoformat(filters["date_from"])
            if filters.get("date_from")
            else None,
            date_to=date.fromisoformat(filters["date_to"]) if filters.get("date_to") else None,
        )
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        ranking = [str(result.document_id) for result in results]
        expected = {ids[item] for item in case["relevant"]}
        rankings.append(ranking)
        expected_sets.append(expected)
        if case.get("exact_identifier"):
            exact_total += 1
            exact_success += bool(ranking and ranking[0] in expected)
        snippet_expected = case.get("snippet")
        snippet_grounded = (
            any(
                snippet_expected in snippet.text
                for result in results
                for snippet in result.snippets
            )
            if snippet_expected
            else None
        )
        outcomes.append(
            {
                "query": case["query"],
                "top": ranking[0] if ranking else None,
                "expected": sorted(expected),
                "latency_ms": round(latency, 3),
                "snippet_grounded": snippet_grounded,
            }
        )
    metrics = retrieval_metrics(rankings, expected_sets)
    metrics.update(
        {
            "exact_identifier_success": exact_success / exact_total if exact_total else 1.0,
            "latency_ms_mean": statistics.mean(latencies),
            "latency_ms_p95": sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)],
        }
    )
    return {"metrics": metrics, "queries": outcomes}


async def add_scale_documents(session: Any, start: int, end: int) -> None:
    for number in range(start, end):
        sample = {
            "id": f"scale-{number}",
            "title": f"Synthetisches Archivdokument {number}",
            "document_type": "generic_letter",
            "life_area": "other",
            "document_date": "2026-01-01",
            "organization": f"Skalierung Organisation {number % 100}",
            "identifier": f"SCALE-{number:05d}",
            "pages": [f"Reproduzierbarer Skalierungstext für Dokument {number}."],
        }
        await seed_document(session, sample)
        if number and number % 500 == 0:
            await session.flush()


async def scale_benchmark(session: Any, sizes: list[int]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    current = 0
    for size in sizes:
        index_started = time.perf_counter()
        await add_scale_documents(session, current, size)
        await session.flush()
        await session.execute(text("SELECT gin_clean_pending_list('benchmark_search_vector_idx')"))
        await session.execute(text("ANALYZE search_documents"))
        index_ms = (time.perf_counter() - index_started) * 1000
        current = size
        query = f"Skalierungstext {size - 1}"
        latencies: list[float] = []
        for _ in range(6):
            started = time.perf_counter()
            await search_documents(
                session,
                query=query,
                limit=10,
                offset=0,
                document_status=DocumentStatus.READY,
                life_area=None,
                document_type=None,
                date_from=None,
                date_to=None,
            )
            latencies.append((time.perf_counter() - started) * 1000)
        index_size = await session.scalar(text("SELECT pg_total_relation_size('search_documents')"))
        plan = await session.scalar(
            text(
                "EXPLAIN (FORMAT JSON) SELECT document_id FROM search_documents "
                "WHERE search_vector @@ websearch_to_tsquery('german', :query)"
            ),
            {"query": query},
        )
        reports.append(
            {
                "documents": size,
                "incremental_index_ms": round(index_ms, 2),
                "cold_query_ms": round(latencies[0], 3),
                "warm_query_ms_mean": round(statistics.mean(latencies[1:]), 3),
                "index_size_bytes": int(index_size or 0),
                "plan": plan,
            }
        )
    return reports


async def prepare_temporary_tables(session: Any) -> None:
    await session.execute(
        text("CREATE TEMP TABLE documents (LIKE public.documents INCLUDING DEFAULTS)")
    )
    await session.execute(
        text(
            "CREATE TEMP TABLE document_extractions "
            "(LIKE public.document_extractions INCLUDING DEFAULTS)"
        )
    )
    await session.execute(
        text("CREATE TEMP TABLE search_documents (LIKE public.search_documents INCLUDING DEFAULTS)")
    )
    await session.execute(
        text(
            "CREATE INDEX benchmark_search_vector_idx ON search_documents USING gin(search_vector)"
        )
    )
    await session.execute(
        text("CREATE INDEX benchmark_identifier_idx ON search_documents (lower(identifier_text))")
    )


async def run(corpus_path: Path, sizes: list[int]) -> dict[str, Any]:
    corpus = json.loads(await asyncio.to_thread(corpus_path.read_text, encoding="utf-8"))
    async with session_factory() as session:
        if not session.bind or session.bind.dialect.name != "postgresql":
            raise RuntimeError("Retrieval benchmark requires PostgreSQL")
        transaction = await session.begin()
        try:
            await prepare_temporary_tables(session)
            quality = await quality_benchmark(session, corpus)
            scale = await scale_benchmark(session, sizes)
        finally:
            await transaction.rollback()
    return {
        "engine": "postgresql_fts",
        "configuration": "german",
        "corpus_documents": len(corpus["documents"]),
        "quality": quality,
        "scale": scale,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="pdi-benchmark-retrieval")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--sizes", default="100,1000,10000")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    sizes = [int(value) for value in arguments.sizes.split(",")]
    report = asyncio.run(run(arguments.corpus, sizes))
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
