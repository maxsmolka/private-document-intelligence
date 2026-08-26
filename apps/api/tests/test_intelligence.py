import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import (
    DocumentExtraction,
    IntelligenceRun,
    IntelligenceRunStatus,
    MetadataProposal,
    ProposalStatus,
)
from pdi.intelligence.providers import DeterministicIntelligenceProvider, DocumentContext
from pdi.intelligence.schemas import IntelligenceResult
from pdi.intelligence.service import run_intelligence
from pdi.search.models import SearchDocument

SAMPLE = """Nordstern Versicherung AG
Versicherungsschein: POL-2026-991
Beitragsrechnung
Rechnungsdatum: 20.08.2026
Fällig bis zum 01.09.2026
Gesamtbetrag: 1.234,56 EUR
"""

PENSION_STATEMENT = """Muster Leben Versicherung AG
Jährliche Wertmitteilung RiesterRente STRATEGIE PLUS
Ausstellungsdatum: 28.02.2022
Wertmitteilung zum 31.12.2021
Vertragsnummer: RR-123456
Versicherungsbeginn: 01.12.2020
Geplanter Rentenbeginn: 01.05.2055
Monatlicher Beitrag: 160,42 EUR
Aktuelles Altersvorsorgevermögen: 8.789,80 EUR
Rückkaufswert: 8.689,80 EUR
Modellrechnung bei 1 %: 12.000,00 EUR
Modellrechnung bei 4 %: 24.000,00 EUR
Modellrechnung bei 6 %: 36.000,00 EUR
"""


async def test_deterministic_provider_returns_normalized_grounded_candidates() -> None:
    result = await DeterministicIntelligenceProvider().analyze(
        DocumentContext(
            text=SAMPLE,
            pages=[SAMPLE],
            original_filename="policy.pdf",
            extraction_method="ocr_pdf",
        )
    )
    assert result.document_type is not None
    assert result.document_type.normalized_value == "insurance_policy"
    assert result.life_area is not None
    assert result.life_area.normalized_value == "insurance"
    assert [item.normalized_value for item in result.amounts] == ["1234.56 EUR"]
    assert {item.field_name for item in result.dates} == {"document_date", "due_date"}
    assert result.identifiers[0].normalized_value == "POL-2026-991"
    for candidate in result.candidates():
        for evidence in candidate.evidence:
            assert SAMPLE[evidence.start : evidence.end] == evidence.text


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("zahlbar bis zum 27.08.2026", "2026-08-27"),
        ("begleichen Sie den Rechnungsbetrag bis zum 28.08.2026", "2026-08-28"),
        ("fällig am 29.08.2026", "2026-08-29"),
    ],
)
async def test_invoice_due_date_uses_explicit_german_payment_anchor(
    wording: str, expected: str
) -> None:
    text = f"Rechnung\nRechnungsdatum: 20.08.2026\n{wording}\nBetrag: 49,90 EUR"
    result = await DeterministicIntelligenceProvider().analyze(
        DocumentContext(
            text=text,
            pages=[text],
            original_filename="invoice.pdf",
            extraction_method="native_pdf",
        )
    )
    due_dates = [item.normalized_value for item in result.dates if item.field_name == "due_date"]
    assert due_dates == [expected]


async def test_invoice_without_due_date_does_not_fabricate_one() -> None:
    text = "Rechnung\nRechnungsdatum: 20.08.2026\nBetrag: 49,90 EUR"
    result = await DeterministicIntelligenceProvider().analyze(
        DocumentContext(
            text=text,
            pages=[text],
            original_filename="invoice.pdf",
            extraction_method="native_pdf",
        )
    )
    assert not any(item.field_name == "due_date" for item in result.dates)


async def test_pension_statement_emits_typed_facts_and_suppresses_scenarios() -> None:
    result = await DeterministicIntelligenceProvider().analyze(
        DocumentContext(
            text=PENSION_STATEMENT,
            pages=[PENSION_STATEMENT],
            original_filename="annual-statement.pdf",
            extraction_method="ocr_pdf",
        )
    )
    assert result.document_type is not None
    assert result.document_type.normalized_value == "pension_statement"
    assert result.life_area is not None and result.life_area.normalized_value == "insurance"
    typed_dates = {item.field_name: item.normalized_value for item in result.dates}
    assert typed_dates == {
        "document_date": "2022-02-28",
        "valuation_date": "2021-12-31",
        "contract_start": "2020-12-01",
        "planned_retirement_start": "2055-05-01",
    }
    typed_amounts = {item.field_name: item.normalized_value for item in result.amounts}
    assert typed_amounts == {
        "monthly_contribution": "160.42 EUR",
        "retirement_assets": "8789.80 EUR",
        "cancellation_value": "8689.80 EUR",
    }
    assert result.semantic_facts[0].field_name == "product_name"
    assert result.semantic_facts[0].normalized_value == "RiesterRente STRATEGIE PLUS"
    assert all(
        "Modellrechnung" not in span.text for item in result.amounts for span in item.evidence
    )


async def seed_document(session: AsyncSession) -> tuple[Document, DocumentExtraction]:
    document = Document(
        title="policy",
        original_filename="policy.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256="f" * 64,
        storage_key="policy.pdf",
        status=DocumentStatus.NEEDS_REVIEW,
        life_area=LifeArea.OTHER,
        source="test",
    )
    document.extraction = DocumentExtraction(
        provider="pypdf",
        provider_version="6",
        method="native_pdf",
        text=SAMPLE,
        page_count=1,
        pages=[SAMPLE],
        content_hash="e" * 64,
        warnings=[],
        extraction_metadata={},
    )
    session.add(document)
    await session.commit()
    return document, document.extraction


async def test_intelligence_runs_are_idempotent_and_supersede_only_after_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(env="test", intelligence_provider="deterministic")
    async with session_factory() as session:
        document, extraction = await seed_document(session)
        first = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key="test:first",
        )
        repeated = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key="test:first",
        )
        second = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key="test:second",
        )
        resumed_ingestion = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key="test:later-worker-attempt",
            reuse_completed=True,
        )
        assert first.id == repeated.id
        assert first.status == IntelligenceRunStatus.COMPLETED
        assert second.is_current is True
        assert resumed_ingestion.id == second.id
        runs = list((await session.scalars(select(IntelligenceRun))).all())
        assert len(runs) == 2
        assert sum(run.is_current for run in runs) == 1
        first_proposals = list(
            (
                await session.scalars(
                    select(MetadataProposal).where(MetadataProposal.intelligence_run_id == first.id)
                )
            ).all()
        )
        assert all(item.status == ProposalStatus.SUPERSEDED for item in first_proposals)
        assert all(item.evidence_verified for item in second.proposals)


async def test_accepting_field_proposal_updates_canonical_value_and_history(
    client: object,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from httpx import AsyncClient

    assert isinstance(client, AsyncClient)
    settings = Settings(env="test", intelligence_provider="deterministic")
    async with session_factory() as session:
        document, extraction = await seed_document(session)
        run = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key="test:accept",
        )
        proposal = next(item for item in run.proposals if item.field_name == "life_area")
        document_id, proposal_id = document.id, proposal.id
    response = await client.post(
        f"/api/v1/review/{document_id}/proposals/{proposal_id}/accept", json={}
    )
    assert response.status_code == 200
    assert response.json()["life_area"] == "insurance"
    detail = await client.get(f"/api/v1/review/{document_id}")
    assert detail.json()["metadata_history"][0]["field_name"] == "life_area"
    assert detail.json()["metadata_history"][0]["source_proposal_id"] == str(proposal_id)
    async with session_factory() as session:
        indexed = await session.scalar(
            select(SearchDocument).where(SearchDocument.document_id == document_id)
        )
        assert indexed is not None
        assert "insurance" in indexed.metadata_text


async def test_failed_reanalysis_preserves_last_successful_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(env="test", intelligence_provider="deterministic")
    async with session_factory() as session:
        document, extraction = await seed_document(session)
        successful = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key="test:successful",
        )

        class FailingProvider:
            name = "failing-test"
            provider_version = "1"
            schema_version = "1"
            prompt_version = None

            async def analyze(self, document: DocumentContext) -> IntelligenceResult:
                raise TimeoutError

        from pdi.intelligence import service

        monkeypatch.setattr(service, "configured_provider", lambda _: FailingProvider())
        failed = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key="test:failed",
        )
        await session.refresh(successful)
        assert failed.status == IntelligenceRunStatus.FAILED
        assert successful.is_current is True
        pending = list(
            (
                await session.scalars(
                    select(MetadataProposal).where(
                        MetadataProposal.intelligence_run_id == successful.id
                    )
                )
            ).all()
        )
        assert all(item.status == ProposalStatus.PENDING for item in pending)


def test_structured_result_rejects_unknown_taxonomy() -> None:
    with pytest.raises(ValidationError, match="Unknown document type"):
        IntelligenceResult.model_validate(
            {
                "document_type": {
                    "field_name": "document_type",
                    "value": "invented",
                    "normalized_value": "invented",
                    "confidence": 0.9,
                    "evidence": [{"page": 1, "start": 0, "end": 8, "text": "invented"}],
                }
            }
        )
