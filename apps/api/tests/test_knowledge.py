from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
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
    Contract,
    DeadlineStatus,
    KnowledgeProposalType,
    Organization,
    OrganizationAlias,
    OrganizationDocument,
    OrganizationMergeHistory,
    OrganizationStatus,
)
from pdi.knowledge.service import merge_organizations
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


async def test_organization_merge_preserves_aliases_and_reassigns_references(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document, _, _ = await seed_run(session, "merge")
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
        session.add(contract)
        await session.commit()
        await merge_organizations(
            session, source_id=source.id, target_id=target.id, reason="Reviewed duplicate"
        )
        await session.refresh(source)
        await session.refresh(contract)
        assert source.status == OrganizationStatus.MERGED
        assert source.merged_into_id == target.id
        assert contract.organization_id == target.id
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
