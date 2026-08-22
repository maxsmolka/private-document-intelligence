from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.database import get_session
from pdi.documents.models import LifeArea
from pdi.ingestion.models import ProposalStatus
from pdi.knowledge.models import (
    ActionItem,
    ActionStatus,
    Contract,
    ContractDocument,
    ContractStatus,
    ContractType,
    Deadline,
    DeadlineStatus,
    DocumentRelationship,
    EventType,
    KnowledgeProposal,
    KnowledgeProposalType,
    Organization,
    OrganizationAlias,
    OrganizationDocument,
    OrganizationStatus,
    TimelineEvent,
)
from pdi.knowledge.schemas import (
    ActionItemList,
    ActionItemRead,
    ContractDetail,
    ContractDocumentRead,
    ContractList,
    ContractRead,
    DeadlineList,
    DeadlineRead,
    EventList,
    EventRead,
    KnowledgeDecision,
    KnowledgeProposalList,
    KnowledgeProposalRead,
    OrganizationDetail,
    OrganizationList,
    OrganizationMergeRequest,
    OrganizationRead,
    RelationshipList,
    RelationshipRead,
    StateDecision,
)
from pdi.knowledge.service import (
    accept_knowledge_proposal,
    merge_organizations,
    reject_knowledge_proposal,
    resolve_exact_organization,
    update_action_status,
    update_deadline_status,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
Session = Annotated[AsyncSession, Depends(get_session)]


async def page[T](
    session: AsyncSession, statement: Select[tuple[T]], limit: int, offset: int
) -> tuple[list[T], int]:
    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    items = list((await session.scalars(statement.limit(limit).offset(offset))).all())
    return items, int(total or 0)


@router.get("/organizations", response_model=OrganizationList)
async def organizations(
    session: Session,
    q: Annotated[str, Query(max_length=200)] = "",
    organization_status: Annotated[
        OrganizationStatus, Query(alias="status")
    ] = OrganizationStatus.ACTIVE,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrganizationList:
    statement = select(Organization).where(Organization.status == organization_status)
    if q.strip():
        pattern = f"%{q.strip()}%"
        alias_matches = select(OrganizationAlias.organization_id).where(
            OrganizationAlias.alias.ilike(pattern)
        )
        statement = statement.where(
            or_(Organization.canonical_name.ilike(pattern), Organization.id.in_(alias_matches))
        )
    statement = statement.order_by(Organization.canonical_name, Organization.id)
    items, total = await page(session, statement, limit, offset)
    return OrganizationList(
        items=[OrganizationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/organizations/{organization_id}", response_model=OrganizationDetail)
async def organization_detail(organization_id: UUID, session: Session) -> OrganizationDetail:
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    aliases = list(
        await session.scalars(
            select(OrganizationAlias.alias)
            .where(OrganizationAlias.organization_id == organization_id)
            .order_by(OrganizationAlias.alias)
        )
    )
    documents = list(
        await session.scalars(
            select(OrganizationDocument.document_id)
            .where(OrganizationDocument.organization_id == organization_id)
            .order_by(OrganizationDocument.created_at)
        )
    )
    contracts = list(
        await session.scalars(
            select(Contract.id)
            .where(Contract.organization_id == organization_id)
            .order_by(Contract.title, Contract.id)
        )
    )
    events = list(
        await session.scalars(
            select(TimelineEvent.id)
            .where(TimelineEvent.organization_id == organization_id)
            .order_by(TimelineEvent.event_date.desc(), TimelineEvent.id)
        )
    )
    deadlines = list(
        await session.scalars(
            select(Deadline.id)
            .where(Deadline.organization_id == organization_id)
            .order_by(Deadline.due_at, Deadline.id)
        )
    )
    actions = list(
        await session.scalars(
            select(ActionItem.id)
            .where(ActionItem.organization_id == organization_id)
            .order_by(ActionItem.due_at, ActionItem.id)
        )
    )
    return OrganizationDetail(
        **OrganizationRead.model_validate(organization).model_dump(),
        aliases=aliases,
        document_ids=documents,
        contract_ids=contracts,
        event_ids=events,
        deadline_ids=deadlines,
        action_item_ids=actions,
    )


@router.post("/organizations/{target_id}/merge", response_model=OrganizationRead)
async def merge_organization(
    target_id: UUID, values: OrganizationMergeRequest, session: Session
) -> OrganizationRead:
    target = await merge_organizations(
        session, source_id=values.source_organization_id, target_id=target_id, reason=values.reason
    )
    return OrganizationRead.model_validate(target)


@router.get("/contracts", response_model=ContractList)
async def contracts(
    session: Session,
    organization_id: UUID | None = None,
    contract_status: Annotated[ContractStatus | None, Query(alias="status")] = None,
    contract_type: ContractType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ContractList:
    statement = select(Contract)
    if organization_id:
        statement = statement.where(Contract.organization_id == organization_id)
    if contract_status:
        statement = statement.where(Contract.status == contract_status)
    if contract_type:
        statement = statement.where(Contract.contract_type == contract_type)
    statement = statement.order_by(Contract.title, Contract.id)
    items, total = await page(session, statement, limit, offset)
    return ContractList(
        items=[ContractRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/contracts/{contract_id}", response_model=ContractDetail)
async def contract_detail(contract_id: UUID, session: Session) -> ContractDetail:
    contract = await session.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    organization = (
        await session.get(Organization, contract.organization_id)
        if contract.organization_id
        else None
    )
    documents = list(
        (
            await session.scalars(
                select(ContractDocument)
                .where(ContractDocument.contract_id == contract_id)
                .order_by(ContractDocument.created_at)
            )
        ).all()
    )
    events = list(
        await session.scalars(
            select(TimelineEvent.id)
            .where(TimelineEvent.contract_id == contract_id)
            .order_by(TimelineEvent.event_date.desc(), TimelineEvent.id)
        )
    )
    deadlines = list(
        await session.scalars(
            select(Deadline.id)
            .where(Deadline.contract_id == contract_id)
            .order_by(Deadline.due_at, Deadline.id)
        )
    )
    actions = list(
        await session.scalars(
            select(ActionItem.id)
            .where(ActionItem.contract_id == contract_id)
            .order_by(ActionItem.due_at, ActionItem.id)
        )
    )
    return ContractDetail(
        **ContractRead.model_validate(contract).model_dump(),
        organization=OrganizationRead.model_validate(organization) if organization else None,
        documents=[
            ContractDocumentRead(
                document_id=item.document_id, relationship_type=item.relationship_type
            )
            for item in documents
        ],
        event_ids=events,
        deadline_ids=deadlines,
        action_item_ids=actions,
    )


async def event_listing(
    session: AsyncSession,
    *,
    life_area: LifeArea | None,
    organization_id: UUID | None,
    contract_id: UUID | None,
    event_type: EventType | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> EventList:
    statement = select(TimelineEvent)
    for value, clause in (
        (life_area, TimelineEvent.life_area == life_area),
        (organization_id, TimelineEvent.organization_id == organization_id),
        (contract_id, TimelineEvent.contract_id == contract_id),
        (event_type, TimelineEvent.event_type == event_type),
        (date_from, TimelineEvent.event_date >= date_from if date_from else None),
        (date_to, TimelineEvent.event_date <= date_to if date_to else None),
    ):
        if value is not None and clause is not None:
            statement = statement.where(clause)
    statement = statement.order_by(TimelineEvent.event_date.desc().nullslast(), TimelineEvent.id)
    items, total = await page(session, statement, limit, offset)
    return EventList(
        items=[EventRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/events", response_model=EventList)
@router.get("/timeline", response_model=EventList)
async def events(
    session: Session,
    life_area: LifeArea | None = None,
    organization_id: UUID | None = None,
    contract_id: UUID | None = None,
    event_type: EventType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EventList:
    return await event_listing(
        session,
        life_area=life_area,
        organization_id=organization_id,
        contract_id=contract_id,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/events/{event_id}", response_model=EventRead)
async def event_detail(event_id: UUID, session: Session) -> EventRead:
    event = await session.get(TimelineEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventRead.model_validate(event)


@router.get("/deadlines", response_model=DeadlineList)
async def deadlines(
    session: Session,
    deadline_status: Annotated[DeadlineStatus | None, Query(alias="status")] = None,
    organization_id: UUID | None = None,
    contract_id: UUID | None = None,
    due_before: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DeadlineList:
    statement = select(Deadline)
    if deadline_status:
        statement = statement.where(Deadline.status == deadline_status)
    if organization_id:
        statement = statement.where(Deadline.organization_id == organization_id)
    if contract_id:
        statement = statement.where(Deadline.contract_id == contract_id)
    if due_before:
        statement = statement.where(Deadline.due_at <= due_before)
    statement = statement.order_by(Deadline.due_at.asc().nullslast(), Deadline.id)
    items, total = await page(session, statement, limit, offset)
    return DeadlineList(
        items=[DeadlineRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/action-items", response_model=ActionItemList)
async def action_items(
    session: Session,
    action_status: Annotated[ActionStatus | None, Query(alias="status")] = None,
    life_area: LifeArea | None = None,
    organization_id: UUID | None = None,
    contract_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ActionItemList:
    statement = select(ActionItem)
    if action_status:
        statement = statement.where(ActionItem.status == action_status)
    if life_area:
        statement = statement.where(ActionItem.life_area == life_area)
    if organization_id:
        statement = statement.where(ActionItem.organization_id == organization_id)
    if contract_id:
        statement = statement.where(ActionItem.contract_id == contract_id)
    statement = statement.order_by(ActionItem.due_at.asc().nullslast(), ActionItem.id)
    items, total = await page(session, statement, limit, offset)
    return ActionItemList(
        items=[ActionItemRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/deadlines/{deadline_id}/status", response_model=DeadlineRead)
async def deadline_state(
    deadline_id: UUID, values: StateDecision, session: Session
) -> DeadlineRead:
    try:
        state = DeadlineStatus(values.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown deadline status") from exc
    return DeadlineRead.model_validate(await update_deadline_status(session, deadline_id, state))


@router.post("/action-items/{item_id}/status", response_model=ActionItemRead)
async def action_state(item_id: UUID, values: StateDecision, session: Session) -> ActionItemRead:
    try:
        state = ActionStatus(values.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown action status") from exc
    return ActionItemRead.model_validate(await update_action_status(session, item_id, state))


@router.get("/relationships", response_model=RelationshipList)
async def relationships(
    session: Session,
    document_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RelationshipList:
    statement = select(DocumentRelationship)
    if document_id:
        statement = statement.where(
            or_(
                DocumentRelationship.source_document_id == document_id,
                DocumentRelationship.target_document_id == document_id,
            )
        )
    statement = statement.order_by(DocumentRelationship.created_at.desc(), DocumentRelationship.id)
    items, total = await page(session, statement, limit, offset)
    return RelationshipList(
        items=[RelationshipRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/knowledge/review", response_model=KnowledgeProposalList)
async def knowledge_review(
    session: Session,
    proposal_type: KnowledgeProposalType | None = None,
    document_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeProposalList:
    statement = select(KnowledgeProposal).where(KnowledgeProposal.status == ProposalStatus.PENDING)
    if proposal_type:
        statement = statement.where(KnowledgeProposal.proposal_type == proposal_type)
    if document_id:
        statement = statement.where(KnowledgeProposal.document_id == document_id)
    statement = statement.order_by(KnowledgeProposal.created_at, KnowledgeProposal.id)
    items, total = await page(session, statement, limit, offset)
    reads = []
    for item in items:
        read = KnowledgeProposalRead.model_validate(item)
        if item.proposal_type == KnowledgeProposalType.ORGANIZATION:
            name = str(item.payload.get("canonical_name", "")).strip()
            existing, reason = await resolve_exact_organization(session, name, item.payload)
            if existing is not None:
                read = read.model_copy(
                    update={
                        "possible_existing_organization_id": existing.id,
                        "match_reason": reason,
                    }
                )
        reads.append(read)
    return KnowledgeProposalList(
        items=reads,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/knowledge/review/{proposal_id}/accept", response_model=KnowledgeProposalRead)
async def accept(
    proposal_id: UUID, values: KnowledgeDecision, session: Session
) -> KnowledgeProposalRead:
    return KnowledgeProposalRead.model_validate(
        await accept_knowledge_proposal(session, proposal_id, values)
    )


@router.post("/knowledge/review/{proposal_id}/reject", response_model=KnowledgeProposalRead)
async def reject(proposal_id: UUID, session: Session) -> KnowledgeProposalRead:
    return KnowledgeProposalRead.model_validate(
        await reject_knowledge_proposal(session, proposal_id)
    )
