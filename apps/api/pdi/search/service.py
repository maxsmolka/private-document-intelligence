import hashlib
import json
import logging
import re
import time
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction
from pdi.knowledge.models import (
    ContractDocument,
    Deadline,
    Organization,
    OrganizationDocument,
    TimelineEvent,
)
from pdi.search.models import SearchDocument
from pdi.search.schemas import (
    HighlightRange,
    SearchFacet,
    SearchFacets,
    SearchResult,
    SearchSnippet,
)

logger = logging.getLogger("pdi.search")
QUERY_TERM_PATTERN = re.compile(r"[\wÄÖÜäöüß]+(?:[-./][\wÄÖÜäöüß]+)*", re.UNICODE)
MAX_SNIPPET_LENGTH = 320
MAX_SNIPPETS = 2
MAINTENANCE_BATCH_SIZE = 200
SEARCHABLE_CANONICAL_FIELDS = {
    "organization",
    "identifier",
    "contract",
    "amount",
    "invoice_total",
    "monthly_rent",
    "service_charges",
    "parking_fee",
    "total_rent",
    "deposit",
    "contract_amount",
    "account_balance",
    "valuation",
    "premium",
    "refund",
    "other_amount",
    "monthly_contribution",
    "retirement_assets",
    "cancellation_value",
    "document_date",
    "due_date",
    "effective_date",
    "other_date",
    "tags",
}


@dataclass(frozen=True)
class SearchValues:
    title: str
    organizations: str
    identifiers: str
    metadata: str
    tags: str
    amount: Decimal | None
    body: str
    pages: list[str]
    extraction_id: uuid.UUID | None
    extraction_content_hash: str | None
    content_hash: str


@dataclass(frozen=True)
class SearchMaintenance:
    documents: int
    indexed: int
    created: int = 0
    updated: int = 0
    missing: int = 0
    stale: int = 0


def normalize_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for match in QUERY_TERM_PATTERN.finditer(query):
        term = match.group(0)
        folded = term.casefold()
        if folded not in seen:
            seen.add(folded)
            terms.append(term)
    return terms


def scalar_values(value: object) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [item for entry in value for item in scalar_values(entry)]
    if isinstance(value, dict):
        return [item for entry in value.values() for item in scalar_values(entry)]
    return []


def canonical_field_values(document: Document, field_name: str) -> list[str]:
    value = (document.canonical_metadata or {}).get(field_name)
    if isinstance(value, dict):
        if field_name == "contract":
            return [
                item
                for key in ("title", "reference_identifier")
                for item in scalar_values(value.get(key))
            ]
        preferred = (
            ("name", "value")
            if field_name == "organization"
            else ("normalized", "value", "source")
            if field_name == "identifier"
            else ()
        )
        for key in preferred:
            if key in value:
                return scalar_values(value[key])
    return scalar_values(value)


def canonical_amount(document: Document) -> Decimal | None:
    for field_name in (
        "invoice_total",
        "total_rent",
        "account_balance",
        "contract_amount",
        "valuation",
        "premium",
        "refund",
        "monthly_rent",
        "monthly_contribution",
        "retirement_assets",
        "cancellation_value",
        "amount",
        "other_amount",
    ):
        value = (document.canonical_metadata or {}).get(field_name)
        candidates = (
            scalar_values(value.get("amount")) if isinstance(value, dict) else scalar_values(value)
        )
        for candidate in candidates:
            rendered = candidate.replace("EUR", "").replace("€", "").replace(" ", "")
            rendered = rendered.replace(".", "").replace(",", ".") if "," in rendered else rendered
            matched = re.search(r"-?\d+(?:[.]\d+)?", rendered)
            if matched:
                try:
                    return Decimal(matched.group(0)).quantize(Decimal("0.01"))
                except InvalidOperation:
                    continue
    return None


def search_values(document: Document, extraction: DocumentExtraction | None = None) -> SearchValues:
    active_extraction = (
        extraction
        if extraction is not None
        else document.canonical_extraction
        if document.canonical_extraction_id is not None
        else None
    )
    organizations = canonical_field_values(document, "organization")
    identifiers = canonical_field_values(document, "identifier")
    tags = canonical_field_values(document, "tags")
    metadata = [
        document.document_type or "",
        document.life_area.value,
        document.document_date.isoformat() if document.document_date else "",
    ]
    for field_name in sorted(SEARCHABLE_CANONICAL_FIELDS - {"organization", "identifier"}):
        metadata.extend(canonical_field_values(document, field_name))
    title = document.title
    organization_text = "\n".join(dict.fromkeys(organizations))
    identifier_text = "\n".join(dict.fromkeys(identifiers))
    metadata_text = "\n".join(item for item in dict.fromkeys(metadata) if item)
    tags_text = "\n".join(item for item in dict.fromkeys(tags) if item)
    amount_value = canonical_amount(document)
    body = active_extraction.normalized_text or active_extraction.text if active_extraction else ""
    pages = active_extraction.pages if active_extraction else []
    extraction_content_hash = active_extraction.content_hash if active_extraction else None
    fields = {
        "title": title,
        "organizations": organization_text,
        "identifiers": identifier_text,
        "metadata": metadata_text,
        "tags": tags_text,
        "amount": str(amount_value) if amount_value is not None else None,
        "body": body,
        "pages": pages,
        "extraction_id": str(active_extraction.id) if active_extraction else None,
        "extraction_content_hash": extraction_content_hash,
    }
    digest = hashlib.sha256(
        json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return SearchValues(
        title=title,
        organizations=organization_text,
        identifiers=identifier_text,
        metadata=metadata_text,
        tags=tags_text,
        amount=amount_value,
        body=body,
        pages=pages,
        extraction_id=active_extraction.id if active_extraction else None,
        extraction_content_hash=extraction_content_hash,
        content_hash=digest,
    )


def weighted_vector(values: SearchValues) -> Any:
    config: Any = literal_column("'german'::regconfig")
    vectors = (
        func.setweight(func.to_tsvector(config, values.title), literal_column("'A'")),
        func.setweight(func.to_tsvector(config, values.organizations), literal_column("'A'")),
        func.setweight(func.to_tsvector(config, values.identifiers), literal_column("'A'")),
        func.setweight(func.to_tsvector(config, values.metadata), literal_column("'B'")),
        func.setweight(func.to_tsvector(config, values.body), literal_column("'D'")),
    )
    result: Any = vectors[0]
    for vector in vectors[1:]:
        result = result.op("||")(vector)
    return result


async def refresh_search_index(
    session: AsyncSession,
    document: Document,
    extraction: DocumentExtraction | None = None,
    *,
    flush: bool = True,
    assume_new: bool = False,
) -> tuple[SearchDocument, bool]:
    if flush:
        await session.flush()
    values = search_values(document, extraction)
    indexed = None if assume_new else await session.get(SearchDocument, document.id)
    created = indexed is None
    if indexed is None:
        indexed = SearchDocument(document_id=document.id, search_vector="")
        session.add(indexed)
    indexed.extraction_id = values.extraction_id
    indexed.extraction_content_hash = values.extraction_content_hash
    indexed.search_content_hash = values.content_hash
    indexed.title_text = values.title
    indexed.organization_text = values.organizations
    indexed.identifier_text = values.identifiers
    indexed.metadata_text = values.metadata
    indexed.tags_text = values.tags
    indexed.amount_value = values.amount
    indexed.body_text = values.body
    indexed.pages = values.pages
    if session.bind and session.bind.dialect.name == "postgresql":
        indexed.search_vector = cast(str, weighted_vector(values))
    else:
        indexed.search_vector = "\n".join(
            (values.title, values.organizations, values.identifiers, values.metadata, values.body)
        )
    if flush:
        await session.flush()
    return indexed, created


async def rebuild_search_index(session: AsyncSession) -> SearchMaintenance:
    total = int(await session.scalar(select(func.count()).select_from(Document)) or 0)
    created = updated = 0
    cursor: uuid.UUID | None = None
    while True:
        statement = (
            select(Document)
            .options(selectinload(Document.canonical_extraction))
            .order_by(Document.id)
            .limit(MAINTENANCE_BATCH_SIZE)
        )
        if cursor is not None:
            statement = statement.where(Document.id > cursor)
        documents = list((await session.scalars(statement)).all())
        if not documents:
            break
        document_ids = [document.id for document in documents]
        current = {
            item.document_id: item
            for item in await session.scalars(
                select(SearchDocument).where(SearchDocument.document_id.in_(document_ids))
            )
        }
        for document in documents:
            indexed = current.get(document.id)
            before = indexed.search_content_hash if indexed else None
            _, was_created = await refresh_search_index(
                session, document, document.canonical_extraction
            )
            created += was_created
            updated += (
                not was_created
                and before != search_values(document, document.canonical_extraction).content_hash
            )
        cursor = documents[-1].id
        await session.flush()
        session.expunge_all()
    await session.commit()
    return SearchMaintenance(documents=total, indexed=total, created=created, updated=updated)


async def verify_search_index(session: AsyncSession) -> SearchMaintenance:
    total = int(await session.scalar(select(func.count()).select_from(Document)) or 0)
    indexed_total = int(await session.scalar(select(func.count()).select_from(SearchDocument)) or 0)
    missing = stale = 0
    cursor: uuid.UUID | None = None
    while True:
        statement = (
            select(Document)
            .options(selectinload(Document.canonical_extraction))
            .order_by(Document.id)
            .limit(MAINTENANCE_BATCH_SIZE)
        )
        if cursor is not None:
            statement = statement.where(Document.id > cursor)
        documents = list((await session.scalars(statement)).all())
        if not documents:
            break
        document_ids = [document.id for document in documents]
        indexes = {
            item.document_id: item
            for item in await session.scalars(
                select(SearchDocument).where(SearchDocument.document_id.in_(document_ids))
            )
        }
        for document in documents:
            indexed = indexes.get(document.id)
            if indexed is None:
                missing += 1
            elif (
                indexed.search_content_hash
                != search_values(document, document.canonical_extraction).content_hash
            ):
                stale += 1
        cursor = documents[-1].id
        session.expunge_all()
    return SearchMaintenance(
        documents=total,
        indexed=indexed_total,
        missing=missing,
        stale=stale,
    )


def highlight_ranges(text_value: str, terms: list[str]) -> list[HighlightRange]:
    ranges: list[tuple[int, int]] = []
    for term in sorted(terms, key=len, reverse=True):
        ranges.extend(
            (match.start(), match.end())
            for match in re.finditer(re.escape(term), text_value, re.IGNORECASE)
        )
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return [HighlightRange(start=start, end=end) for start, end in merged]


def grounded_snippets(pages: list[str], terms: list[str]) -> list[SearchSnippet]:
    snippets: list[SearchSnippet] = []
    if not terms:
        return snippets
    pattern = re.compile(
        "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)), re.IGNORECASE
    )
    for page_number, page in enumerate(pages, 1):
        match = pattern.search(page)
        if match is None:
            continue
        start = max(0, match.start() - 120)
        end = min(len(page), start + MAX_SNIPPET_LENGTH)
        start = max(0, end - MAX_SNIPPET_LENGTH)
        snippet_text = page[start:end]
        snippets.append(
            SearchSnippet(
                page=page_number,
                text=snippet_text,
                highlight_ranges=highlight_ranges(snippet_text, terms),
            )
        )
        if len(snippets) == MAX_SNIPPETS:
            break
    return snippets


def matched_fields(row: Any, terms: list[str]) -> list[str]:
    fields = (
        ("title", row.title_text),
        ("organization", row.organization_text),
        ("identifier", row.identifier_text),
        ("canonical_metadata", row.metadata_text),
        ("text", row.body_text),
    )
    return [
        name for name, value in fields if any(term.casefold() in value.casefold() for term in terms)
    ]


def exact_line_match(value: str, query: str) -> bool:
    folded = query.casefold()
    return any(line.casefold() == folded for line in value.splitlines())


async def search_facets(
    session: AsyncSession,
    *,
    query: str,
    document_status: DocumentStatus | None,
    life_area: LifeArea | None,
    document_type: str | None,
    date_from: date | None,
    date_to: date | None,
    organization_id: uuid.UUID | None = None,
    contract_id: uuid.UUID | None = None,
    has_event: bool = False,
    has_deadline: bool = False,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    source: str | None = None,
    tag: str | None = None,
) -> SearchFacets:
    if session.bind and session.bind.dialect.name == "postgresql":
        filter_clause, parameters = filter_sql(
            document_status=document_status,
            life_area=life_area,
            document_type=document_type,
            date_from=date_from,
            date_to=date_to,
            organization_id=organization_id,
            contract_id=contract_id,
            has_event=has_event,
            has_deadline=has_deadline,
            amount_min=amount_min,
            amount_max=amount_max,
            source=source,
            tag=tag,
        )
        parameters.update({"query": normalize_query(query), "has_query": bool(query)})
        exact_identifier = "lower(s.identifier_text) = lower(:query)"
        match_clause = f"(:has_query = false OR s.search_vector @@ q.value OR {exact_identifier})"
        rows = (
            await session.execute(
                text(
                    "SELECT d.id FROM search_documents s JOIN documents d ON d.id = s.document_id "
                    "CROSS JOIN LATERAL "
                    "(SELECT websearch_to_tsquery('german', :query) AS value) q "
                    f"WHERE {match_clause}{filter_clause}"
                ),
                parameters,
            )
        ).all()
        document_ids = [uuid.UUID(str(row.id)) for row in rows]
    else:
        results, _ = await fallback_search(
            session,
            query=normalize_query(query),
            limit=1_000_000,
            offset=0,
            document_status=document_status,
            life_area=life_area,
            document_type=document_type,
            date_from=date_from,
            date_to=date_to,
            organization_id=organization_id,
            contract_id=contract_id,
            has_event=has_event,
            has_deadline=has_deadline,
            amount_min=amount_min,
            amount_max=amount_max,
            source=source,
            tag=tag,
        )
        document_ids = [item.document_id for item in results]
    if not document_ids:
        return SearchFacets()
    documents = (
        await session.execute(
            select(
                Document.id,
                Document.document_type,
                Document.document_date,
                Document.status,
                Document.source,
            ).where(Document.id.in_(document_ids))
        )
    ).all()

    def counted(values: list[str | None], *, limit: int = 20) -> list[SearchFacet]:
        counts = Counter(item for item in values if item)
        return [
            SearchFacet(value=value, label=value.replace("_", " ").title(), count=count)
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    organization_rows = (
        await session.execute(
            select(
                Organization.id,
                Organization.canonical_name,
                func.count(OrganizationDocument.document_id),
            )
            .join(OrganizationDocument, OrganizationDocument.organization_id == Organization.id)
            .where(OrganizationDocument.document_id.in_(document_ids))
            .group_by(Organization.id, Organization.canonical_name)
            .order_by(
                func.count(OrganizationDocument.document_id).desc(),
                Organization.canonical_name,
            )
            .limit(50)
        )
    ).all()
    return SearchFacets(
        document_types=counted([row.document_type for row in documents]),
        organizations=[
            SearchFacet(value=str(row.id), label=row.canonical_name, count=int(row[2]))
            for row in organization_rows
        ],
        years=counted(
            [
                str(row.document_date.year) if row.document_date is not None else None
                for row in documents
            ]
        ),
        review_states=counted([row.status.value for row in documents]),
        sources=counted([row.source for row in documents]),
    )


async def search_documents(
    session: AsyncSession,
    *,
    query: str,
    limit: int,
    offset: int,
    document_status: DocumentStatus | None,
    life_area: LifeArea | None,
    document_type: str | None,
    date_from: date | None,
    date_to: date | None,
    organization_id: uuid.UUID | None = None,
    contract_id: uuid.UUID | None = None,
    has_event: bool = False,
    has_deadline: bool = False,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    source: str | None = None,
    tag: str | None = None,
) -> tuple[list[SearchResult], int]:
    normalized = normalize_query(query)
    started = time.perf_counter()
    if session.bind and session.bind.dialect.name == "postgresql":
        results, total = await postgres_search(
            session,
            query=normalized,
            limit=limit,
            offset=offset,
            document_status=document_status,
            life_area=life_area,
            document_type=document_type,
            date_from=date_from,
            date_to=date_to,
            organization_id=organization_id,
            contract_id=contract_id,
            has_event=has_event,
            has_deadline=has_deadline,
            amount_min=amount_min,
            amount_max=amount_max,
            source=source,
            tag=tag,
        )
    else:
        results, total = await fallback_search(
            session,
            query=normalized,
            limit=limit,
            offset=offset,
            document_status=document_status,
            life_area=life_area,
            document_type=document_type,
            date_from=date_from,
            date_to=date_to,
            organization_id=organization_id,
            contract_id=contract_id,
            has_event=has_event,
            has_deadline=has_deadline,
            amount_min=amount_min,
            amount_max=amount_max,
            source=source,
            tag=tag,
        )
    logger.info(
        "search_completed",
        extra={
            "operation": "lexical_search",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "result_count": len(results),
            "has_query": bool(normalized),
        },
    )
    return results, total


def filter_sql(
    *,
    document_status: DocumentStatus | None,
    life_area: LifeArea | None,
    document_type: str | None,
    date_from: date | None,
    date_to: date | None,
    organization_id: uuid.UUID | None,
    contract_id: uuid.UUID | None,
    has_event: bool,
    has_deadline: bool,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
    source: str | None,
    tag: str | None,
) -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    parameters: dict[str, object] = {}
    for name, value, clause in (
        ("status", document_status.value if document_status else None, "d.status = :status"),
        ("life_area", life_area.value if life_area else None, "d.life_area = :life_area"),
        ("document_type", document_type, "d.document_type = :document_type"),
        ("date_from", date_from, "d.document_date >= :date_from"),
        ("date_to", date_to, "d.document_date <= :date_to"),
        ("source", source, "d.source = :source"),
        ("amount_min", amount_min, "s.amount_value >= :amount_min"),
        ("amount_max", amount_max, "s.amount_value <= :amount_max"),
        (
            "organization_id",
            organization_id,
            "EXISTS (SELECT 1 FROM organization_documents od "
            "WHERE od.document_id = d.id AND od.organization_id = :organization_id)",
        ),
        (
            "contract_id",
            contract_id,
            "EXISTS (SELECT 1 FROM contract_documents cd "
            "WHERE cd.document_id = d.id AND cd.contract_id = :contract_id)",
        ),
    ):
        if value is not None:
            clauses.append(clause)
            parameters[name] = value
    if tag:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(string_to_array(s.tags_text, E'\\n')) item "
            "WHERE lower(item) = lower(:tag))"
        )
        parameters["tag"] = tag
    if has_event:
        clauses.append("EXISTS (SELECT 1 FROM timeline_events e WHERE e.source_document_id = d.id)")
    if has_deadline:
        clauses.append("EXISTS (SELECT 1 FROM deadlines dl WHERE dl.source_document_id = d.id)")
    return (" AND " + " AND ".join(clauses) if clauses else ""), parameters


async def postgres_search(
    session: AsyncSession,
    *,
    query: str,
    limit: int,
    offset: int,
    document_status: DocumentStatus | None,
    life_area: LifeArea | None,
    document_type: str | None,
    date_from: date | None,
    date_to: date | None,
    organization_id: uuid.UUID | None,
    contract_id: uuid.UUID | None,
    has_event: bool,
    has_deadline: bool,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
    source: str | None,
    tag: str | None,
) -> tuple[list[SearchResult], int]:
    filters, parameters = filter_sql(
        document_status=document_status,
        life_area=life_area,
        document_type=document_type,
        date_from=date_from,
        date_to=date_to,
        organization_id=organization_id,
        contract_id=contract_id,
        has_event=has_event,
        has_deadline=has_deadline,
        amount_min=amount_min,
        amount_max=amount_max,
        source=source,
        tag=tag,
    )
    parameters.update({"query": query, "has_query": bool(query), "limit": limit, "offset": offset})
    exact_identifier = "lower(s.identifier_text) = lower(:query)"
    match_clause = f"(:has_query = false OR s.search_vector @@ q.value OR {exact_identifier})"
    from_clause = (
        " FROM search_documents s JOIN documents d ON d.id = s.document_id "
        "CROSS JOIN LATERAL (SELECT websearch_to_tsquery('german', :query) AS value) q "
        f"WHERE {match_clause}{filters}"
    )
    score = (
        "ts_rank_cd(s.search_vector, q.value, 32) "
        f"+ CASE WHEN {exact_identifier} THEN 2.0 ELSE 0 END "
        "+ CASE WHEN lower(s.organization_text) = lower(:query) THEN 0.8 ELSE 0 END "
        "+ CASE WHEN position(lower(:query) in lower(s.title_text)) > 0 THEN 0.6 ELSE 0 END "
        "+ CASE WHEN position(lower(:query) in lower(s.metadata_text)) > 0 THEN 0.3 ELSE 0 END"
    )
    total = await session.scalar(text("SELECT count(*)" + from_clause), parameters)
    statement = text(
        "SELECT d.id AS document_id, d.title, d.document_type, d.life_area, "
        "d.document_date, d.status, s.title_text, s.organization_text, "
        "s.identifier_text, s.metadata_text, s.body_text, s.pages, "
        f"({score}) AS score{from_clause} "
        "ORDER BY score DESC, d.document_date DESC NULLS LAST, d.id ASC "
        "LIMIT :limit OFFSET :offset"
    )
    rows = (await session.execute(statement, parameters)).mappings().all()
    terms = query_terms(query)
    return [row_to_result(row, terms) for row in rows], int(total or 0)


async def fallback_search(
    session: AsyncSession,
    *,
    query: str,
    limit: int,
    offset: int,
    document_status: DocumentStatus | None,
    life_area: LifeArea | None,
    document_type: str | None,
    date_from: date | None,
    date_to: date | None,
    organization_id: uuid.UUID | None,
    contract_id: uuid.UUID | None,
    has_event: bool,
    has_deadline: bool,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
    source: str | None,
    tag: str | None,
) -> tuple[list[SearchResult], int]:
    rows = (
        await session.execute(
            select(SearchDocument, Document).join(
                Document, Document.id == SearchDocument.document_id
            )
        )
    ).all()
    terms = query_terms(query)
    organization_documents = (
        set(
            await session.scalars(
                select(OrganizationDocument.document_id).where(
                    OrganizationDocument.organization_id == organization_id
                )
            )
        )
        if organization_id
        else set()
    )
    contract_documents = (
        set(
            await session.scalars(
                select(ContractDocument.document_id).where(
                    ContractDocument.contract_id == contract_id
                )
            )
        )
        if contract_id
        else set()
    )
    event_documents = (
        set(await session.scalars(select(TimelineEvent.source_document_id))) if has_event else set()
    )
    deadline_documents = (
        set(await session.scalars(select(Deadline.source_document_id))) if has_deadline else set()
    )
    ranked: list[tuple[float, Any]] = []
    for indexed, document in rows:
        if document_status and document.status != document_status:
            continue
        if life_area and document.life_area != life_area:
            continue
        if document_type and document.document_type != document_type:
            continue
        if date_from and (document.document_date is None or document.document_date < date_from):
            continue
        if date_to and (document.document_date is None or document.document_date > date_to):
            continue
        if source and document.source != source:
            continue
        if organization_id and document.id not in organization_documents:
            continue
        if contract_id and document.id not in contract_documents:
            continue
        if has_event and document.id not in event_documents:
            continue
        if has_deadline and document.id not in deadline_documents:
            continue
        if amount_min is not None and (
            indexed.amount_value is None or indexed.amount_value < amount_min
        ):
            continue
        if amount_max is not None and (
            indexed.amount_value is None or indexed.amount_value > amount_max
        ):
            continue
        if tag and not exact_line_match(indexed.tags_text, tag):
            continue
        combined = "\n".join(
            (
                indexed.title_text,
                indexed.organization_text,
                indexed.identifier_text,
                indexed.metadata_text,
                indexed.body_text,
            )
        ).casefold()
        if terms and not all(term.casefold() in combined for term in terms):
            continue
        score = sum(term.casefold() in combined for term in terms) * 0.05
        score += 2.0 if exact_line_match(indexed.identifier_text, query) else 0
        score += 0.8 if indexed.organization_text.casefold() == query.casefold() else 0
        score += 0.6 if query.casefold() in indexed.title_text.casefold() else 0
        score += 0.3 if query.casefold() in indexed.metadata_text.casefold() else 0
        ranked.append((score, (indexed, document)))
    ranked.sort(
        key=lambda item: (
            -item[0],
            -(item[1][1].document_date.toordinal() if item[1][1].document_date else -1),
            str(item[1][1].id),
        )
    )
    results = [
        orm_to_result(indexed, document, score, terms) for score, (indexed, document) in ranked
    ]
    return results[offset : offset + limit], len(results)


def row_to_result(row: Any, terms: list[str]) -> SearchResult:
    return SearchResult(
        document_id=row.document_id,
        title=row.title,
        document_type=row.document_type,
        life_area=row.life_area,
        document_date=row.document_date,
        status=row.status,
        score=round(float(row.score), 6),
        matched_fields=matched_fields(row, terms),
        snippets=grounded_snippets(row.pages, terms),
    )


def orm_to_result(
    indexed: SearchDocument,
    document: Document,
    score: float,
    terms: list[str],
) -> SearchResult:
    return SearchResult(
        document_id=document.id,
        title=document.title,
        document_type=document.document_type,
        life_area=document.life_area,
        document_date=document.document_date,
        status=document.status,
        score=round(score, 6),
        matched_fields=cast(Any, matched_fields(indexed, terms)),
        snippets=grounded_snippets(indexed.pages, terms),
    )
