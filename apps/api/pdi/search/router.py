from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.router import require_auth
from pdi.auth.service import Principal
from pdi.core.database import get_session
from pdi.documents.models import DocumentStatus, LifeArea
from pdi.search.models import SavedSearch
from pdi.search.schemas import SavedSearchCreate, SavedSearchRead, SearchResponse
from pdi.search.service import normalize_query, search_documents, search_facets

router = APIRouter(prefix="/api/v1/search", tags=["search"])
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(require_auth)]


def owner_key(principal: Principal) -> str:
    return str(principal.user_id) if principal.user_id else "auth-disabled"


@router.get("", response_model=SearchResponse)
async def search(
    session: Session,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    document_status: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    life_area: LifeArea | None = None,
    document_type: Annotated[str | None, Query(max_length=100)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    organization_id: UUID | None = None,
    contract_id: UUID | None = None,
    has_event: bool = False,
    has_deadline: bool = False,
    amount_min: Annotated[Decimal | None, Query(ge=0)] = None,
    amount_max: Annotated[Decimal | None, Query(ge=0)] = None,
    source: Annotated[str | None, Query(max_length=100)] = None,
    tag: Annotated[str | None, Query(max_length=100)] = None,
) -> SearchResponse:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        raise HTTPException(status_code=422, detail="amount_min must not exceed amount_max")
    query = normalize_query(q)
    results, total = await search_documents(
        session,
        query=query,
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
    facets = await search_facets(
        session,
        query=query,
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
    return SearchResponse(
        query=query,
        total=total,
        limit=limit,
        offset=offset,
        results=results,
        facets=facets,
    )


@router.get("/saved", response_model=list[SavedSearchRead])
async def list_saved_searches(
    session: Session, principal: CurrentPrincipal
) -> list[SavedSearchRead]:
    rows = list(
        await session.scalars(
            select(SavedSearch)
            .where(SavedSearch.owner_key == owner_key(principal))
            .order_by(SavedSearch.name, SavedSearch.id)
        )
    )
    return [SavedSearchRead.model_validate(row, from_attributes=True) for row in rows]


@router.post("/saved", response_model=SavedSearchRead, status_code=status.HTTP_201_CREATED)
async def create_saved_search(
    values: SavedSearchCreate, session: Session, principal: CurrentPrincipal
) -> SavedSearchRead:
    row = SavedSearch(
        owner_key=owner_key(principal),
        name=values.name,
        filters=values.filters.model_dump(mode="json", exclude_none=True),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A saved search with this name exists") from exc
    await session.refresh(row)
    return SavedSearchRead.model_validate(row, from_attributes=True)


@router.post("/saved/{saved_search_id}/delete")
async def delete_saved_search(
    saved_search_id: UUID, session: Session, principal: CurrentPrincipal
) -> dict[str, bool]:
    row = await session.scalar(
        select(SavedSearch).where(
            SavedSearch.id == saved_search_id,
            SavedSearch.owner_key == owner_key(principal),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": True}
