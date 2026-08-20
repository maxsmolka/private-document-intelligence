from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.database import get_session
from pdi.documents.models import DocumentStatus, LifeArea
from pdi.search.schemas import SearchResponse
from pdi.search.service import normalize_query, search_documents

router = APIRouter(prefix="/api/v1/search", tags=["search"])
Session = Annotated[AsyncSession, Depends(get_session)]


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
) -> SearchResponse:
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
    )
    return SearchResponse(
        query=query,
        total=total,
        limit=limit,
        offset=offset,
        results=results,
    )
