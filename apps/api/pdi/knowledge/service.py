import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document, LifeArea
from pdi.ingestion.models import DocumentExtraction, ProposalStatus
from pdi.knowledge.extraction import normalize_name
from pdi.knowledge.models import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    Contract,
    ContractDocument,
    ContractDocumentType,
    ContractStatus,
    ContractType,
    DatePrecision,
    Deadline,
    DeadlineStatus,
    DeadlineType,
    DocumentRelationship,
    DocumentRelationshipType,
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
from pdi.search.service import refresh_search_index


def parsed_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date must use YYYY-MM-DD") from exc


def enum_value[E: StrEnum](enum_type: type[E], value: Any, field: str) -> E:
    try:
        return enum_type(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown {field}") from exc


async def proposal_for_review(session: AsyncSession, proposal_id: uuid.UUID) -> KnowledgeProposal:
    proposal = await session.get(KnowledgeProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Knowledge proposal not found")
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=409, detail="Knowledge proposal is not pending")
    if not proposal.evidence_verified:
        raise HTTPException(status_code=409, detail="Knowledge proposal evidence is not verified")
    return proposal


def audit(
    session: AsyncSession,
    *,
    resource_type: str,
    resource_id: uuid.UUID,
    action: str,
    proposal: KnowledgeProposal | None,
    new_value: dict[str, Any] | None,
    previous_value: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        KnowledgeHistory(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            previous_value=previous_value,
            new_value=new_value,
            source_proposal_id=proposal.id if proposal else None,
            confirmation_source="user_review",
            reason=reason,
        )
    )


async def add_alias(
    session: AsyncSession,
    organization: Organization,
    alias: str,
    source: str,
    document_id: uuid.UUID | None,
) -> None:
    normalized = normalize_name(alias)
    exists = await session.scalar(
        select(OrganizationAlias).where(
            OrganizationAlias.organization_id == organization.id,
            OrganizationAlias.normalized_alias == normalized,
        )
    )
    if exists is None and normalized != organization.normalized_name:
        session.add(
            OrganizationAlias(
                organization_id=organization.id,
                alias=alias,
                normalized_alias=normalized,
                source=source,
                source_document_id=document_id,
            )
        )


async def link_organization_document(
    session: AsyncSession, organization_id: uuid.UUID, proposal: KnowledgeProposal
) -> None:
    link = await session.get(OrganizationDocument, (organization_id, proposal.document_id))
    if link is None:
        session.add(
            OrganizationDocument(
                organization_id=organization_id,
                document_id=proposal.document_id,
                source_proposal_id=proposal.id,
            )
        )


async def accept_organization(
    session: AsyncSession, proposal: KnowledgeProposal, decision: KnowledgeDecision
) -> Organization:
    payload = {**proposal.payload, **decision.values}
    name = str(payload.get("canonical_name", "")).strip()[:255]
    if not name:
        raise HTTPException(status_code=422, detail="Organization name required")
    if decision.action == "link_existing":
        target = decision.target_resource_id or proposal.possible_existing_organization_id
        organization = await session.get(Organization, target) if target else None
        if organization is None or organization.status != OrganizationStatus.ACTIVE:
            raise HTTPException(status_code=422, detail="Active target organization required")
        await add_alias(session, organization, name, "accepted_proposal", proposal.document_id)
    else:
        organization = Organization(
            canonical_name=name,
            normalized_name=normalize_name(name),
            organization_type=payload.get("organization_type"),
            source_document_id=proposal.document_id,
            source_extraction_id=proposal.extraction_id,
            intelligence_run_id=proposal.intelligence_run_id,
            source_proposal_id=proposal.id,
            evidence=proposal.evidence,
        )
        session.add(organization)
        await session.flush()
    await link_organization_document(session, organization.id, proposal)
    audit(
        session,
        resource_type="organization",
        resource_id=organization.id,
        action="linked" if decision.action == "link_existing" else "created",
        proposal=proposal,
        new_value={"canonical_name": organization.canonical_name},
    )
    document = await session.get(Document, proposal.document_id)
    if document:
        metadata = dict(document.canonical_metadata)
        metadata["organization"] = {
            "name": organization.canonical_name,
            "organization_id": str(organization.id),
        }
        document.canonical_metadata = metadata
        extraction = await session.get(DocumentExtraction, proposal.extraction_id)
        await refresh_search_index(session, document, extraction)
    return organization


async def organization_for_document(
    session: AsyncSession, document_id: uuid.UUID
) -> uuid.UUID | None:
    return cast(
        uuid.UUID | None,
        await session.scalar(
            select(OrganizationDocument.organization_id)
            .join(Organization, Organization.id == OrganizationDocument.organization_id)
            .where(
                OrganizationDocument.document_id == document_id,
                Organization.status == OrganizationStatus.ACTIVE,
            )
            .order_by(OrganizationDocument.created_at)
        ),
    )


async def accept_contract(
    session: AsyncSession, proposal: KnowledgeProposal, decision: KnowledgeDecision
) -> Contract:
    payload = {**proposal.payload, **decision.values}
    if decision.action == "link_existing":
        contract = await session.get(Contract, decision.target_resource_id)
        if contract is None:
            raise HTTPException(status_code=422, detail="Target contract required")
    else:
        organization_id = payload.get("organization_id") or await organization_for_document(
            session, proposal.document_id
        )
        contract = Contract(
            title=str(payload.get("title") or "Untitled contract")[:255],
            contract_type=enum_value(
                ContractType, payload.get("contract_type", "other"), "contract type"
            ),
            status=enum_value(ContractStatus, payload.get("status", "unknown"), "contract status"),
            organization_id=uuid.UUID(str(organization_id)) if organization_id else None,
            reference_identifier=payload.get("reference_identifier"),
            start_date=parsed_date(payload.get("start_date")),
            end_date=parsed_date(payload.get("end_date")),
            renewal_date=parsed_date(payload.get("renewal_date")),
            cancellation_deadline=parsed_date(payload.get("cancellation_deadline")),
            source_document_id=proposal.document_id,
            source_extraction_id=proposal.extraction_id,
            intelligence_run_id=proposal.intelligence_run_id,
            source_proposal_id=proposal.id,
            evidence=proposal.evidence,
        )
        session.add(contract)
        await session.flush()
    link = await session.get(ContractDocument, (contract.id, proposal.document_id))
    if link is None:
        session.add(
            ContractDocument(
                contract_id=contract.id,
                document_id=proposal.document_id,
                relationship_type=enum_value(
                    ContractDocumentType,
                    payload.get("document_relationship_type", "contract_document"),
                    "contract document relationship",
                ),
                source_proposal_id=proposal.id,
            )
        )
    audit(
        session,
        resource_type="contract",
        resource_id=contract.id,
        action="linked" if decision.action == "link_existing" else "created",
        proposal=proposal,
        new_value={"title": contract.title, "reference_identifier": contract.reference_identifier},
    )
    document = await session.get(Document, proposal.document_id)
    if document:
        metadata = dict(document.canonical_metadata)
        metadata["contract"] = {
            "title": contract.title,
            "reference_identifier": contract.reference_identifier,
            "contract_id": str(contract.id),
        }
        document.canonical_metadata = metadata
        extraction = await session.get(DocumentExtraction, proposal.extraction_id)
        await refresh_search_index(session, document, extraction)
    return contract


async def accept_event(
    session: AsyncSession, proposal: KnowledgeProposal, decision: KnowledgeDecision
) -> TimelineEvent:
    payload = {**proposal.payload, **decision.values}
    event = TimelineEvent(
        event_type=enum_value(EventType, payload["event_type"], "event type"),
        title=str(payload["title"])[:255],
        description=payload.get("description"),
        event_date=parsed_date(payload.get("event_date")),
        event_date_precision=enum_value(
            DatePrecision, payload.get("event_date_precision", "unknown"), "date precision"
        ),
        life_area=enum_value(LifeArea, payload.get("life_area", "other"), "life area"),
        organization_id=uuid.UUID(payload["organization_id"])
        if payload.get("organization_id")
        else await organization_for_document(session, proposal.document_id),
        contract_id=uuid.UUID(payload["contract_id"]) if payload.get("contract_id") else None,
        source_document_id=proposal.document_id,
        source_extraction_id=proposal.extraction_id,
        intelligence_run_id=proposal.intelligence_run_id,
        source_proposal_id=proposal.id,
        evidence=proposal.evidence,
    )
    session.add(event)
    await session.flush()
    audit(
        session,
        resource_type="event",
        resource_id=event.id,
        action="created",
        proposal=proposal,
        new_value=payload,
    )
    return event


async def accept_deadline(
    session: AsyncSession, proposal: KnowledgeProposal, decision: KnowledgeDecision
) -> Deadline:
    payload = {**proposal.payload, **decision.values}
    deadline = Deadline(
        title=str(payload["title"])[:255],
        due_at=parsed_date(payload.get("due_at")),
        original_rule=payload.get("original_rule"),
        deadline_type=enum_value(
            DeadlineType, payload.get("deadline_type", "other"), "deadline type"
        ),
        organization_id=await organization_for_document(session, proposal.document_id),
        contract_id=uuid.UUID(payload["contract_id"]) if payload.get("contract_id") else None,
        source_document_id=proposal.document_id,
        source_extraction_id=proposal.extraction_id,
        source_proposal_id=proposal.id,
        evidence=proposal.evidence,
    )
    session.add(deadline)
    await session.flush()
    audit(
        session,
        resource_type="deadline",
        resource_id=deadline.id,
        action="created",
        proposal=proposal,
        new_value=payload,
    )
    return deadline


async def accept_action(
    session: AsyncSession, proposal: KnowledgeProposal, decision: KnowledgeDecision
) -> ActionItem:
    payload = {**proposal.payload, **decision.values}
    item = ActionItem(
        title=str(payload["title"])[:255],
        description=payload.get("description"),
        due_at=parsed_date(payload.get("due_at")),
        priority=enum_value(ActionPriority, payload.get("priority", "normal"), "priority"),
        life_area=enum_value(LifeArea, payload.get("life_area", "other"), "life area"),
        organization_id=await organization_for_document(session, proposal.document_id),
        contract_id=uuid.UUID(payload["contract_id"]) if payload.get("contract_id") else None,
        deadline_id=uuid.UUID(payload["deadline_id"]) if payload.get("deadline_id") else None,
        source_document_id=proposal.document_id,
        source_extraction_id=proposal.extraction_id,
        source_proposal_id=proposal.id,
        evidence=proposal.evidence,
    )
    session.add(item)
    await session.flush()
    audit(
        session,
        resource_type="action_item",
        resource_id=item.id,
        action="created",
        proposal=proposal,
        new_value=payload,
    )
    return item


async def accept_relationship(
    session: AsyncSession, proposal: KnowledgeProposal, decision: KnowledgeDecision
) -> DocumentRelationship:
    payload = {**proposal.payload, **decision.values}
    target_id = uuid.UUID(str(payload["target_document_id"]))
    if target_id == proposal.document_id or await session.get(Document, target_id) is None:
        raise HTTPException(status_code=422, detail="Valid distinct target document required")
    relationship_type = enum_value(
        DocumentRelationshipType, payload["relationship_type"], "relationship type"
    )
    existing = await session.scalar(
        select(DocumentRelationship).where(
            DocumentRelationship.source_document_id == proposal.document_id,
            DocumentRelationship.target_document_id == target_id,
            DocumentRelationship.relationship_type == relationship_type,
        )
    )
    if existing:
        return existing
    relationship = DocumentRelationship(
        source_document_id=proposal.document_id,
        target_document_id=target_id,
        relationship_type=relationship_type,
        confidence=proposal.confidence,
        provider=proposal.provider,
        intelligence_run_id=proposal.intelligence_run_id,
        source_proposal_id=proposal.id,
        evidence=proposal.evidence,
    )
    session.add(relationship)
    await session.flush()
    audit(
        session,
        resource_type="relationship",
        resource_id=relationship.id,
        action="created",
        proposal=proposal,
        new_value=payload,
    )
    return relationship


async def accept_knowledge_proposal(
    session: AsyncSession, proposal_id: uuid.UUID, decision: KnowledgeDecision
) -> KnowledgeProposal:
    proposal = await proposal_for_review(session, proposal_id)
    handlers = {
        KnowledgeProposalType.ORGANIZATION: accept_organization,
        KnowledgeProposalType.CONTRACT: accept_contract,
        KnowledgeProposalType.EVENT: accept_event,
        KnowledgeProposalType.DEADLINE: accept_deadline,
        KnowledgeProposalType.ACTION_ITEM: accept_action,
        KnowledgeProposalType.DOCUMENT_RELATIONSHIP: accept_relationship,
    }
    handler = handlers.get(proposal.proposal_type)
    if handler is None:
        raise HTTPException(status_code=422, detail="Unsupported proposal type")
    resource: Any = await handler(session, proposal, decision)
    proposal.status = ProposalStatus.ACCEPTED
    proposal.resolved_resource_id = resource.id
    proposal.resolved_at = datetime.now(UTC)
    if decision.values:
        proposal.validation_notes = [*proposal.validation_notes, "user_edited"]
    await session.commit()
    return proposal


async def reject_knowledge_proposal(
    session: AsyncSession, proposal_id: uuid.UUID
) -> KnowledgeProposal:
    proposal = await proposal_for_review(session, proposal_id)
    proposal.status = ProposalStatus.REJECTED
    proposal.resolved_at = datetime.now(UTC)
    await session.commit()
    return proposal


async def merge_organizations(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    reason: str,
) -> Organization:
    if source_id == target_id:
        raise HTTPException(status_code=422, detail="Organizations must be distinct")
    source = await session.get(Organization, source_id)
    target = await session.get(Organization, target_id)
    if (
        not source
        or not target
        or source.status != OrganizationStatus.ACTIVE
        or target.status != OrganizationStatus.ACTIVE
    ):
        raise HTTPException(status_code=409, detail="Both organizations must be active")
    aliases = list(
        (
            await session.scalars(
                select(OrganizationAlias).where(OrganizationAlias.organization_id == source_id)
            )
        ).all()
    )
    await add_alias(session, target, source.canonical_name, "merge", source.source_document_id)
    for alias in aliases:
        await add_alias(session, target, alias.alias, "merge", alias.source_document_id)
    source_docs = list(
        (
            await session.scalars(
                select(OrganizationDocument).where(
                    OrganizationDocument.organization_id == source_id
                )
            )
        ).all()
    )
    for link in source_docs:
        target_link = await session.get(OrganizationDocument, (target_id, link.document_id))
        if target_link is None:
            session.add(
                OrganizationDocument(
                    organization_id=target_id,
                    document_id=link.document_id,
                    source_proposal_id=link.source_proposal_id,
                )
            )
        document = await session.get(Document, link.document_id)
        if document is not None:
            metadata = dict(document.canonical_metadata)
            metadata["organization"] = {
                "name": target.canonical_name,
                "organization_id": str(target.id),
            }
            document.canonical_metadata = metadata
            extraction = await session.scalar(
                select(DocumentExtraction).where(DocumentExtraction.document_id == document.id)
            )
            await refresh_search_index(session, document, extraction)
    await session.execute(
        delete(OrganizationDocument).where(OrganizationDocument.organization_id == source_id)
    )
    await session.execute(
        update(Contract)
        .where(Contract.organization_id == source_id)
        .values(organization_id=target_id)
    )
    await session.execute(
        update(TimelineEvent)
        .where(TimelineEvent.organization_id == source_id)
        .values(organization_id=target_id)
    )
    await session.execute(
        update(Deadline)
        .where(Deadline.organization_id == source_id)
        .values(organization_id=target_id)
    )
    await session.execute(
        update(ActionItem)
        .where(ActionItem.organization_id == source_id)
        .values(organization_id=target_id)
    )
    source.status = OrganizationStatus.MERGED
    source.merged_into_id = target_id
    session.add(
        OrganizationMergeHistory(
            source_organization_id=source_id,
            target_organization_id=target_id,
            reason=reason,
            confirmation_source="user_merge",
        )
    )
    audit(
        session,
        resource_type="organization",
        resource_id=source_id,
        action="merged",
        proposal=None,
        new_value={"merged_into_id": str(target_id)},
        reason=reason,
    )
    await session.commit()
    return target


async def update_action_status(
    session: AsyncSession, item_id: uuid.UUID, new_status: ActionStatus
) -> ActionItem:
    item = await session.get(ActionItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Action item not found")
    previous = item.status
    item.status = new_status
    item.completed_at = datetime.now(UTC) if new_status == ActionStatus.COMPLETED else None
    audit(
        session,
        resource_type="action_item",
        resource_id=item.id,
        action="status_changed",
        proposal=None,
        previous_value={"status": previous.value},
        new_value={"status": new_status.value},
    )
    await session.commit()
    await session.refresh(item)
    return item


async def update_deadline_status(
    session: AsyncSession, deadline_id: uuid.UUID, new_status: DeadlineStatus
) -> Deadline:
    deadline = await session.get(Deadline, deadline_id)
    if deadline is None:
        raise HTTPException(status_code=404, detail="Deadline not found")
    previous = deadline.status
    deadline.status = new_status
    audit(
        session,
        resource_type="deadline",
        resource_id=deadline.id,
        action="status_changed",
        proposal=None,
        previous_value={"status": previous.value},
        new_value={"status": new_status.value},
    )
    await session.commit()
    await session.refresh(deadline)
    return deadline
