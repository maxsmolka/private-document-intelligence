import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import (
    DocumentExtraction,
    IntelligenceRun,
    IntelligenceRunStatus,
    MetadataProposal,
    ProposalStatus,
)
from pdi.knowledge.extraction import generate_knowledge_proposals, normalize_name
from pdi.knowledge.models import (
    ActionItem,
    Contract,
    DatePrecision,
    Deadline,
    DeadlineStatus,
    DeadlineType,
    EventType,
    KnowledgeHistory,
    KnowledgeProposal,
    KnowledgeProposalType,
    Organization,
    OrganizationAlias,
    OrganizationDocument,
    OrganizationMergeHistory,
    OrganizationStatus,
    TimelineEvent,
)
from pdi.knowledge.schemas import KnowledgeDecision
from pdi.knowledge.service import accept_knowledge_proposal, merge_organizations
from pdi.search.models import SearchDocument

TEXT = """Generali Deutschland AG
Versicherungsschein: VS-12345678
Vertragsbeginn: 01.08.2026
Der Beitrag ist zahlbar bis 31.08.2026.
"""


async def seed_run(
    session: AsyncSession, suffix: str = "knowledge"
) -> tuple[Document, DocumentExtraction, IntelligenceRun]:
    document = Document(
        title="Generali Versicherung",
        original_filename=f"{suffix}.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256=suffix.ljust(64, "a")[:64],
        storage_key=f"{suffix}.pdf",
        status=DocumentStatus.NEEDS_REVIEW,
        life_area=LifeArea.INSURANCE,
        document_type="insurance_policy",
        source="test",
    )
    extraction = DocumentExtraction(
        document=document,
        provider="test",
        provider_version="1",
        method="native_pdf",
        text=TEXT,
        page_count=1,
        pages=[TEXT],
        content_hash=suffix.rjust(64, "b")[:64],
        warnings=[],
        extraction_metadata={},
    )
    session.add(document)
    await session.flush()
    now = datetime.now(UTC)
    run = IntelligenceRun(
        document=document,
        input_extraction_id=extraction.id,
        input_content_hash=extraction.content_hash,
        request_key=f"test:{suffix}",
        provider="deterministic",
        provider_version="1",
        schema_version="1",
        status=IntelligenceRunStatus.COMPLETED,
        is_current=True,
        started_at=now,
        finished_at=now,
    )
    session.add(run)
    await session.flush()
    for field, value in (
        ("organization", "Generali Deutschland AG"),
        ("identifier", "VS-12345678"),
    ):
        start = TEXT.index(value)
        session.add(
            MetadataProposal(
                document=document,
                intelligence_run=run,
                field_name=field,
                proposed_value=value,
                normalized_value=value,
                source="document_intelligence",
                provider="deterministic",
                confidence=0.95,
                evidence=[
                    {
                        "page": 1,
                        "start": start,
                        "end": start + len(value),
                        "text": value,
                        "verified": True,
                    }
                ],
                evidence_verified=True,
                status=ProposalStatus.PENDING,
            )
        )
    await session.commit()
    return document, extraction, run


async def test_knowledge_flow_is_review_first_grounded_and_idempotent(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        document, extraction, run = await seed_run(session)
        created = await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=run
        )
        await session.commit()
        assert {item.proposal_type for item in created} >= {
            KnowledgeProposalType.ORGANIZATION,
            KnowledgeProposalType.CONTRACT,
            KnowledgeProposalType.EVENT,
            KnowledgeProposalType.DEADLINE,
            KnowledgeProposalType.ACTION_ITEM,
        }
        assert await session.scalar(select(func.count()).select_from(Organization)) == 0
        assert (
            await generate_knowledge_proposals(
                session, document=document, extraction=extraction, run=run
            )
            == []
        )
        proposal_ids = {item.proposal_type: item.id for item in created}

    organization_response = await client.post(
        f"/api/v1/knowledge/review/{proposal_ids[KnowledgeProposalType.ORGANIZATION]}/accept",
        json={"action": "create", "values": {}},
    )
    assert organization_response.status_code == 200
    organization_id = organization_response.json()["resolved_resource_id"]
    resolved_ids: dict[KnowledgeProposalType, str] = {}
    for proposal_type in (
        KnowledgeProposalType.CONTRACT,
        KnowledgeProposalType.EVENT,
        KnowledgeProposalType.DEADLINE,
        KnowledgeProposalType.ACTION_ITEM,
    ):
        response = await client.post(
            f"/api/v1/knowledge/review/{proposal_ids[proposal_type]}/accept",
            json={
                "action": "create",
                "values": {"title": "Reviewed policy"}
                if proposal_type == KnowledgeProposalType.CONTRACT
                else {},
            },
        )
        assert response.status_code == 200, response.text
        resolved_ids[proposal_type] = response.json()["resolved_resource_id"]

    detail = await client.get(f"/api/v1/organizations/{organization_id}")
    assert detail.status_code == 200
    assert detail.json()["contract_ids"]
    assert detail.json()["document_ids"] == [str(document.id)]
    contract_detail = await client.get(
        f"/api/v1/contracts/{resolved_ids[KnowledgeProposalType.CONTRACT]}"
    )
    assert contract_detail.json()["title"] == "Reviewed policy"
    assert (await client.get("/api/v1/timeline")).json()["total"] == 1
    assert (await client.get("/api/v1/deadlines")).json()["total"] == 1
    deadline_response = await client.post(
        f"/api/v1/deadlines/{resolved_ids[KnowledgeProposalType.DEADLINE]}/status",
        json={"status": "completed"},
    )
    assert deadline_response.status_code == 200
    assert deadline_response.json()["status"] == DeadlineStatus.COMPLETED
    assert (await client.get("/api/v1/action-items", params={"status": "open"})).json()[
        "total"
    ] == 1
    async with session_factory() as session:
        indexed = await session.get(SearchDocument, document.id)
        assert indexed is not None
        assert "Generali Deutschland AG" in indexed.organization_text
        assert "VS-12345678" in indexed.metadata_text


async def test_exact_alias_match_suggests_link_without_auto_merge(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        organization = Organization(
            canonical_name="Generali Deutschland AG",
            normalized_name=normalize_name("Generali Deutschland AG"),
        )
        session.add(organization)
        await session.flush()
        session.add(
            OrganizationAlias(
                organization_id=organization.id,
                alias="Generali",
                normalized_alias=normalize_name("Generali"),
                source="user",
            )
        )
        document, extraction, run = await seed_run(session, "alias")
        organization_proposal = await session.scalar(
            select(MetadataProposal).where(
                MetadataProposal.intelligence_run_id == run.id,
                MetadataProposal.field_name == "organization",
            )
        )
        assert organization_proposal is not None
        organization_proposal.proposed_value = "Generali"
        organization_proposal.normalized_value = "Generali"
        start = TEXT.index("Generali")
        organization_proposal.evidence = [
            {
                "page": 1,
                "start": start,
                "end": start + 8,
                "text": "Generali",
                "verified": True,
            }
        ]
        await session.commit()
        created = await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=run
        )
        candidate = next(
            item for item in created if item.proposal_type == KnowledgeProposalType.ORGANIZATION
        )
        assert candidate.possible_existing_organization_id == organization.id
        assert candidate.match_reason == "exact normalized name or alias"
        assert organization.status == OrganizationStatus.ACTIVE


async def pending_organization_proposal(
    session: AsyncSession, suffix: str, name: str = "Generali Deutschland AG"
) -> KnowledgeProposal:
    document, extraction, run = await seed_run(session, suffix)
    created = await generate_knowledge_proposals(
        session, document=document, extraction=extraction, run=run
    )
    proposal = next(
        item for item in created if item.proposal_type == KnowledgeProposalType.ORGANIZATION
    )
    proposal.payload = {**proposal.payload, "canonical_name": name}
    proposal.possible_existing_organization_id = None
    proposal.match_reason = None
    await session.commit()
    return proposal


async def test_accepting_create_rechecks_exact_canonical_name(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        existing = Organization(
            canonical_name="Generali Deutschland AG",
            normalized_name=normalize_name("Generali Deutschland AG"),
        )
        session.add(existing)
        await session.commit()
        proposal = await pending_organization_proposal(session, "exact-recheck")
        existing_id = existing.id
        proposal_id = proposal.id
        document_id = proposal.document_id
    review = await client.get("/api/v1/knowledge/review", params={"proposal_type": "organization"})
    review_item = next(item for item in review.json()["items"] if item["id"] == str(proposal_id))
    assert review_item["possible_existing_organization_id"] == str(existing_id)
    assert review_item["match_reason"] == "exact normalized canonical name"
    response = await client.post(
        f"/api/v1/knowledge/review/{proposal_id}/accept",
        json={"action": "create", "values": {}},
    )
    assert response.status_code == 200
    assert response.json()["resolved_resource_id"] == str(existing_id)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Organization)) == 1
        assert await session.get(OrganizationDocument, (existing_id, document_id)) is not None
        history = await session.scalar(
            select(KnowledgeHistory).where(KnowledgeHistory.source_proposal_id == proposal_id)
        )
        assert history is not None and history.action == "linked"


async def test_accepting_create_rechecks_exact_alias(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        existing = Organization(
            canonical_name="Generali Deutschland AG",
            normalized_name=normalize_name("Generali Deutschland AG"),
        )
        session.add(existing)
        await session.flush()
        session.add(
            OrganizationAlias(
                organization_id=existing.id,
                alias="Generali",
                normalized_alias=normalize_name("Generali"),
                source="user",
            )
        )
        await session.commit()
        proposal = await pending_organization_proposal(session, "alias-recheck", "Generali")
        existing_id = existing.id
        proposal_id = proposal.id
    response = await client.post(
        f"/api/v1/knowledge/review/{proposal_id}/accept",
        json={"action": "create", "values": {}},
    )
    assert response.status_code == 200
    assert response.json()["resolved_resource_id"] == str(existing_id)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Organization)) == 1


async def test_fuzzy_similar_organization_name_remains_separate(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        session.add(
            Organization(
                canonical_name="Generali Deutschland AG",
                normalized_name=normalize_name("Generali Deutschland AG"),
            )
        )
        await session.commit()
        proposal = await pending_organization_proposal(
            session, "fuzzy-separate", "Generali Deutschland GmbH"
        )
        proposal_id = proposal.id
    response = await client.post(
        f"/api/v1/knowledge/review/{proposal_id}/accept",
        json={"action": "create", "values": {}},
    )
    assert response.status_code == 200
    async with session_factory() as session:
        organizations = list(await session.scalars(select(Organization)))
        assert {item.canonical_name for item in organizations} == {
            "Generali Deutschland AG",
            "Generali Deutschland GmbH",
        }


async def test_accepting_create_rechecks_exact_strong_identifier(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        first = await pending_organization_proposal(session, "identifier-one", "Acme Holdings AG")
        first.payload = {**first.payload, "vat_id": "ATU-12345678"}
        await session.commit()
        first_id = first.id
    response = await client.post(
        f"/api/v1/knowledge/review/{first_id}/accept",
        json={"action": "create", "values": {}},
    )
    assert response.status_code == 200
    organization_id = response.json()["resolved_resource_id"]
    async with session_factory() as session:
        second = await pending_organization_proposal(session, "identifier-two", "Acme Austria")
        second.payload = {**second.payload, "vat_id": "ATU 12345678"}
        await session.commit()
        second_id = second.id
    response = await client.post(
        f"/api/v1/knowledge/review/{second_id}/accept",
        json={"action": "create", "values": {}},
    )
    assert response.status_code == 200
    assert response.json()["resolved_resource_id"] == organization_id
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Organization)) == 1


async def test_near_simultaneous_exact_proposals_create_one_organization(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_factory() as session:
        first = await pending_organization_proposal(session, "concurrent-one")
        second = await pending_organization_proposal(session, "concurrent-two")
        proposal_ids = (first.id, second.id)

    async def accept(proposal_id: uuid.UUID) -> None:
        async with postgres_factory() as session:
            await accept_knowledge_proposal(
                session,
                proposal_id,
                KnowledgeDecision(action="create"),
            )

    await asyncio.gather(*(accept(proposal_id) for proposal_id in proposal_ids))
    async with postgres_factory() as session:
        organizations = list(await session.scalars(select(Organization)))
        proposals = list(
            await session.scalars(
                select(KnowledgeProposal).where(KnowledgeProposal.id.in_(proposal_ids))
            )
        )
        assert len(organizations) == 1
        assert {item.resolved_resource_id for item in proposals} == {organizations[0].id}


async def test_knowledge_review_batches_organization_resolution_queries(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        for number in range(50):
            await pending_organization_proposal(
                session, f"batch-{number}", f"Synthetic Organization {number}"
            )

    engine = session_factory.kw["bind"]
    statements: list[str] = []

    def count_selects(*args: object) -> None:
        statement = str(args[2])
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
    try:
        response = await client.get("/api/v1/knowledge/review", params={"limit": 50})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_selects)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 50
    assert len(statements) <= 4


async def test_rejected_knowledge_proposal_is_audited(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        document, extraction, run = await seed_run(session, "reject")
        proposals = await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=run
        )
        await session.commit()
        proposal = proposals[0]

    response = await client.post(f"/api/v1/knowledge/review/{proposal.id}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    async with session_factory() as session:
        history = await session.scalar(
            select(KnowledgeHistory).where(KnowledgeHistory.source_proposal_id == proposal.id)
        )
        assert history is not None
        assert history.action == "rejected"


async def test_organization_merge_preserves_aliases_and_reassigns_references(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document, extraction, _ = await seed_run(session, "merge")
        source = Organization(
            canonical_name="Generali Deutschland", normalized_name="generali deutschland"
        )
        target = Organization(
            canonical_name="Generali Deutschland AG", normalized_name="generali deutschland ag"
        )
        session.add_all([source, target])
        await session.flush()
        session.add(OrganizationDocument(organization_id=source.id, document_id=document.id))
        contract = Contract(title="Policy", organization_id=source.id)
        event = TimelineEvent(
            event_type=EventType.OTHER,
            title="Source event",
            event_date_precision=DatePrecision.UNKNOWN,
            organization_id=source.id,
            source_document_id=document.id,
            source_extraction_id=extraction.id,
        )
        deadline = Deadline(
            title="Source deadline",
            deadline_type=DeadlineType.OTHER,
            organization_id=source.id,
            source_document_id=document.id,
            source_extraction_id=extraction.id,
        )
        action = ActionItem(
            title="Source action",
            organization_id=source.id,
            source_document_id=document.id,
            source_extraction_id=extraction.id,
        )
        history = KnowledgeHistory(
            resource_type="organization",
            resource_id=source.id,
            action="created",
            new_value={"canonical_name": source.canonical_name},
            confirmation_source="user_review",
        )
        session.add_all((contract, event, deadline, action, history))
        await session.commit()
        await merge_organizations(
            session, source_id=source.id, target_id=target.id, reason="Reviewed duplicate"
        )
        await session.refresh(source)
        await session.refresh(contract)
        await session.refresh(event)
        await session.refresh(deadline)
        await session.refresh(action)
        await session.refresh(history)
        assert source.status == OrganizationStatus.MERGED
        assert source.merged_into_id == target.id
        assert contract.organization_id == target.id
        assert event.organization_id == target.id
        assert deadline.organization_id == target.id
        assert action.organization_id == target.id
        assert history.resource_id == source.id
        assert await session.get(OrganizationDocument, (target.id, document.id)) is not None
        assert await session.scalar(select(OrganizationMergeHistory)) is not None
        aliases = list(
            await session.scalars(
                select(OrganizationAlias.alias).where(
                    OrganizationAlias.organization_id == target.id
                )
            )
        )
        assert "Generali Deutschland" in aliases
        await session.refresh(document)
        assert document.canonical_metadata["organization"] == {
            "name": target.canonical_name,
            "organization_id": str(target.id),
        }
        indexed = await session.get(SearchDocument, document.id)
        assert indexed is not None and target.canonical_name in indexed.organization_text
    organizations = await client.get("/api/v1/organizations")
    assert organizations.status_code == 200
    assert organizations.json()["total"] == 1
    assert organizations.json()["items"][0]["id"] == str(target.id)


async def test_relative_deadline_keeps_rule_without_invented_date(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document, extraction, run = await seed_run(session, "relative")
        extraction.text = "Widerspruch ist innerhalb eines Monats möglich."
        extraction.pages = [extraction.text]
        extraction.content_hash = "c" * 64
        created = await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=run
        )
        relative = next(
            item for item in created if item.proposal_type == KnowledgeProposalType.DEADLINE
        )
        assert relative.payload["due_at"] is None
        assert "ambiguous_relative_deadline" in relative.validation_notes
        assert not any(item.proposal_type == KnowledgeProposalType.ACTION_ITEM for item in created)


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("zahlbar bis zum 27.08.2026", "2026-08-27"),
        ("begleichen Sie den Rechnungsbetrag bis zum 28.08.2026", "2026-08-28"),
        ("fällig am 29.08.2026", "2026-08-29"),
    ],
)
async def test_invoice_deadline_does_not_create_contract_from_identifier_alone(
    session_factory: async_sessionmaker[AsyncSession], wording: str, expected: str
) -> None:
    async with session_factory() as session:
        document, extraction, run = await seed_run(session, f"invoice-{expected}")
        document.document_type = "invoice"
        document.life_area = LifeArea.FINANCE
        extraction.text = f"Rechnung\nRechnungsnummer: R-2026-10\n{wording}\nBetrag: 49,90 EUR"
        extraction.pages = [extraction.text]
        extraction.content_hash = expected.replace("-", "").ljust(64, "e")
        created = await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=run
        )
        assert not any(item.proposal_type == KnowledgeProposalType.CONTRACT for item in created)
        deadline = next(
            item for item in created if item.proposal_type == KnowledgeProposalType.DEADLINE
        )
        assert deadline.payload["due_at"] == expected
        payment_due = next(
            item
            for item in created
            if item.proposal_type == KnowledgeProposalType.EVENT
            and item.payload["event_type"] == EventType.PAYMENT_DUE.value
        )
        assert payment_due.payload["event_date"] == expected


async def test_invoice_without_deadline_creates_neither_deadline_nor_contract(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document, extraction, run = await seed_run(session, "invoice-no-due")
        document.document_type = "invoice"
        document.life_area = LifeArea.FINANCE
        extraction.text = "Rechnung\nRechnungsnummer: R-2026-11\nBetrag: 49,90 EUR"
        extraction.pages = [extraction.text]
        created = await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=run
        )
        assert not any(
            item.proposal_type in {KnowledgeProposalType.CONTRACT, KnowledgeProposalType.DEADLINE}
            for item in created
        )


@pytest.mark.parametrize("proposal_type", list(KnowledgeProposalType))
async def test_every_pending_knowledge_proposal_can_be_rejected_without_verified_evidence(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    proposal_type: KnowledgeProposalType,
) -> None:
    async with session_factory() as session:
        document, extraction, run = await seed_run(session, f"reject-{proposal_type.value}")
        proposal = KnowledgeProposal(
            identity_key=f"reject-{proposal_type.value}".ljust(64, "0")[:64],
            proposal_type=proposal_type,
            document_id=document.id,
            extraction_id=extraction.id,
            intelligence_run_id=run.id,
            knowledge_schema_version="1",
            provider="deterministic",
            provider_version="1",
            payload={"title": "Synthetic candidate"},
            confidence=0.4,
            evidence=[],
            evidence_verified=False,
            status=ProposalStatus.PENDING,
        )
        session.add(proposal)
        await session.commit()
        proposal_id = proposal.id
    response = await client.post(f"/api/v1/knowledge/review/{proposal_id}/reject")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == ProposalStatus.REJECTED
    async with session_factory() as session:
        stored = await session.get(KnowledgeProposal, proposal_id)
        assert stored is not None and stored.status == ProposalStatus.REJECTED
        history = await session.scalar(
            select(KnowledgeHistory).where(KnowledgeHistory.source_proposal_id == proposal_id)
        )
        assert history is not None and history.action == "rejected"
        assert await session.scalar(select(func.count()).select_from(Contract)) == 0
        assert await session.scalar(select(func.count()).select_from(Organization)) == 0


async def test_new_analysis_supersedes_only_stale_pending_proposals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document, extraction, first_run = await seed_run(session, "supersede")
        first = await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=first_run
        )
        first[0].status = ProposalStatus.ACCEPTED
        now = datetime.now(UTC)
        second_run = IntelligenceRun(
            document=document,
            input_extraction_id=extraction.id,
            input_content_hash="d" * 64,
            request_key="test:supersede:2",
            provider="deterministic",
            provider_version="1",
            schema_version="1",
            status=IntelligenceRunStatus.COMPLETED,
            is_current=True,
            started_at=now,
            finished_at=now,
        )
        session.add(second_run)
        await session.flush()
        await generate_knowledge_proposals(
            session, document=document, extraction=extraction, run=second_run
        )
        await session.flush()
        assert first[0].status == ProposalStatus.ACCEPTED
        assert all(item.status == ProposalStatus.SUPERSEDED for item in first[1:])
