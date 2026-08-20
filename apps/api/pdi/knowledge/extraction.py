import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document
from pdi.ingestion.models import (
    DocumentExtraction,
    IntelligenceRun,
    MetadataProposal,
    ProposalStatus,
)
from pdi.knowledge.models import (
    KNOWLEDGE_SCHEMA_VERSION,
    Contract,
    ContractDocument,
    ContractDocumentType,
    ContractType,
    DocumentRelationshipType,
    EventType,
    KnowledgeProposal,
    KnowledgeProposalType,
    Organization,
    OrganizationAlias,
)

DATE_PATTERN = r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4})"
EVENT_PATTERNS: tuple[tuple[re.Pattern[str], EventType, str], ...] = (
    (
        re.compile(rf"(?:Vertragsbeginn|beginnt am)\s*:?\s*{DATE_PATTERN}", re.I),
        EventType.CONTRACT_STARTED,
        "Contract started",
    ),
    (
        re.compile(rf"(?:gültig|wirksam)\s+ab\s+{DATE_PATTERN}", re.I),
        EventType.CONTRACT_CHANGED,
        "Change effective",
    ),
    (
        re.compile(rf"gekündigt\s+(?:zum|am)\s+{DATE_PATTERN}", re.I),
        EventType.CONTRACT_CANCELLED,
        "Contract cancelled",
    ),
    (
        re.compile(rf"Rechnungsdatum\s*:?\s*{DATE_PATTERN}", re.I),
        EventType.INVOICE_ISSUED,
        "Invoice issued",
    ),
)
DEADLINE_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(rf"(?:zahlbar|fällig)\s+(?:bis|zum)\s+{DATE_PATTERN}", re.I),
        "payment",
        "Payment due",
    ),
    (
        re.compile(rf"Kündigung\s+(?:bis|spätestens)\s*{DATE_PATTERN}", re.I),
        "cancellation",
        "Cancellation deadline",
    ),
    (
        re.compile(
            rf"(?:Antwort|Rückmeldung|Widerspruch)\s+(?:bis|spätestens)\s*{DATE_PATTERN}", re.I
        ),
        "response",
        "Response deadline",
    ),
    (
        re.compile(rf"(?:einreichen|vorlegen)\s+(?:bis|spätestens)\s*{DATE_PATTERN}", re.I),
        "submission",
        "Submission deadline",
    ),
)
RELATIVE_DEADLINE = re.compile(
    r"(?P<rule>(?:Widerspruch|Antwort|Kündigung)[^.\n]{0,80}"
    r"innerhalb\s+(?:eines|von einem)\s+Monats)",
    re.I,
)


@dataclass(frozen=True)
class Candidate:
    proposal_type: KnowledgeProposalType
    payload: dict[str, Any]
    confidence: float
    evidence: list[dict[str, Any]]
    notes: list[str]
    possible_existing_organization_id: uuid.UUID | None = None
    match_reason: str | None = None


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\wäöüß]+", " ", normalized).split())


def parse_german_date(value: str) -> date:
    day, month, year = (int(part) for part in value.split("."))
    return date(year, month, day)


def evidence_for(extraction: DocumentExtraction, start: int, end: int) -> dict[str, Any]:
    page = 1
    cursor = 0
    for number, page_text in enumerate(extraction.pages, 1):
        page_end = cursor + len(page_text)
        if start <= page_end:
            page = number
            break
        cursor = page_end + 2
    return {
        "page": page,
        "start": start,
        "end": end,
        "text": extraction.text[start:end],
        "verified": True,
    }


def proposal_identity(extraction: DocumentExtraction, candidate: Candidate) -> str:
    data = {
        "extraction_hash": extraction.content_hash,
        "schema": KNOWLEDGE_SCHEMA_VERSION,
        "type": candidate.proposal_type.value,
        "payload": candidate.payload,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def metadata_candidates(run: IntelligenceRun) -> list[MetadataProposal]:
    return [proposal for proposal in run.proposals if proposal.evidence_verified]


async def organization_candidates(session: AsyncSession, run: IntelligenceRun) -> list[Candidate]:
    candidates: list[Candidate] = []
    for proposal in metadata_candidates(run):
        if proposal.field_name != "organization" or not proposal.proposed_value:
            continue
        name = proposal.proposed_value.strip()
        normalized = normalize_name(name)
        existing = await session.scalar(
            select(Organization)
            .outerjoin(OrganizationAlias, OrganizationAlias.organization_id == Organization.id)
            .where(
                Organization.status == "active",
                or_(
                    Organization.normalized_name == normalized,
                    OrganizationAlias.normalized_alias == normalized,
                ),
            )
            .order_by(Organization.id)
        )
        candidates.append(
            Candidate(
                proposal_type=KnowledgeProposalType.ORGANIZATION,
                payload={"canonical_name": name, "normalized_name": normalized},
                confidence=proposal.confidence or 0.7,
                evidence=proposal.evidence,
                notes=["exact_existing_name_or_alias"] if existing else [],
                possible_existing_organization_id=existing.id if existing else None,
                match_reason="exact normalized name or alias" if existing else None,
            )
        )
    return candidates


def inferred_contract_type(document: Document) -> ContractType:
    document_type = document.document_type or ""
    if document.life_area.value == "insurance" or "insurance" in document_type:
        return ContractType.INSURANCE
    if document.life_area.value == "work" or "employment" in document_type:
        return ContractType.EMPLOYMENT
    if document.life_area.value == "finance" or "bank" in document_type:
        return ContractType.BANKING
    return ContractType.OTHER


def contract_candidate(document: Document, run: IntelligenceRun) -> Candidate | None:
    proposals = metadata_candidates(run)
    identifiers = [item for item in proposals if item.field_name == "identifier"]
    contract_document = (document.document_type or "") in {
        "contract",
        "insurance_policy",
        "employment_document",
    } or bool(
        re.search(
            r"Vertrag|Versicherungsschein|Police",
            document.extraction.text if document.extraction else "",
            re.I,
        )
    )
    if not identifiers and not contract_document:
        return None
    identifier = identifiers[0] if identifiers else None
    evidence = (
        identifier.evidence
        if identifier
        else next((item.evidence for item in proposals if item.field_name == "document_type"), [])
    )
    payload = {
        "title": document.title,
        "contract_type": inferred_contract_type(document).value,
        "status": "unknown",
        "reference_identifier": (
            identifier.normalized_value or identifier.proposed_value if identifier else None
        ),
        "document_relationship_type": (
            ContractDocumentType.POLICY.value
            if document.document_type == "insurance_policy"
            else ContractDocumentType.CONTRACT_DOCUMENT.value
        ),
    }
    return Candidate(
        proposal_type=KnowledgeProposalType.CONTRACT,
        payload=payload,
        confidence=identifier.confidence if identifier and identifier.confidence else 0.7,
        evidence=evidence,
        notes=["partial_contract_candidate"] if identifier is None else ["exact_identifier"],
    )


def temporal_candidates(document: Document, extraction: DocumentExtraction) -> list[Candidate]:
    candidates: list[Candidate] = []
    for pattern, event_type, title in EVENT_PATTERNS:
        for match in pattern.finditer(extraction.text):
            candidates.append(
                Candidate(
                    proposal_type=KnowledgeProposalType.EVENT,
                    payload={
                        "event_type": event_type.value,
                        "title": title,
                        "event_date": parse_german_date(match.group("date")).isoformat(),
                        "event_date_precision": "exact",
                        "life_area": document.life_area.value,
                    },
                    confidence=0.9,
                    evidence=[evidence_for(extraction, match.start(), match.end())],
                    notes=["explicit_date_pattern"],
                )
            )
    for pattern, deadline_type, title in DEADLINE_PATTERNS:
        for match in pattern.finditer(extraction.text):
            due = parse_german_date(match.group("date"))
            evidence = [evidence_for(extraction, match.start(), match.end())]
            candidates.append(
                Candidate(
                    proposal_type=KnowledgeProposalType.DEADLINE,
                    payload={
                        "title": title,
                        "due_at": due.isoformat(),
                        "deadline_type": deadline_type,
                        "original_rule": match.group(0),
                    },
                    confidence=0.95,
                    evidence=evidence,
                    notes=["explicit_absolute_deadline"],
                )
            )
            action_title = {
                "payment": "Pay document amount",
                "cancellation": "Review cancellation deadline",
                "response": "Respond to document",
                "submission": "Submit requested documents",
            }.get(deadline_type)
            if action_title:
                candidates.append(
                    Candidate(
                        proposal_type=KnowledgeProposalType.ACTION_ITEM,
                        payload={
                            "title": action_title,
                            "due_at": due.isoformat(),
                            "priority": "normal",
                            "life_area": document.life_area.value,
                        },
                        confidence=0.9,
                        evidence=evidence,
                        notes=["explicit_document_obligation"],
                    )
                )
    for match in RELATIVE_DEADLINE.finditer(extraction.text):
        candidates.append(
            Candidate(
                proposal_type=KnowledgeProposalType.DEADLINE,
                payload={
                    "title": "Relative deadline requires review",
                    "due_at": None,
                    "deadline_type": "response",
                    "original_rule": match.group("rule"),
                },
                confidence=0.45,
                evidence=[evidence_for(extraction, match.start(), match.end())],
                notes=["ambiguous_relative_deadline", "no_exact_date_inferred"],
            )
        )
    return candidates


async def relationship_candidates(
    session: AsyncSession, document: Document, run: IntelligenceRun
) -> list[Candidate]:
    identifiers = [
        item.normalized_value or item.proposed_value
        for item in metadata_candidates(run)
        if item.field_name == "identifier"
    ]
    candidates: list[Candidate] = []
    for identifier in filter(None, identifiers):
        rows = (
            await session.execute(
                select(Contract, ContractDocument)
                .join(ContractDocument, ContractDocument.contract_id == Contract.id)
                .where(
                    Contract.reference_identifier == identifier,
                    ContractDocument.document_id != document.id,
                )
                .order_by(ContractDocument.document_id)
            )
        ).all()
        for contract, linked in rows:
            relationship_type = (
                DocumentRelationshipType.AMENDS
                if re.search(
                    r"Änderung|Anpassung|Nachtrag",
                    document.extraction.text if document.extraction else "",
                    re.I,
                )
                else DocumentRelationshipType.SAME_CASE
            )
            candidates.append(
                Candidate(
                    proposal_type=KnowledgeProposalType.DOCUMENT_RELATIONSHIP,
                    payload={
                        "target_document_id": str(linked.document_id),
                        "relationship_type": relationship_type.value,
                        "contract_id": str(contract.id),
                        "reference_identifier": identifier,
                    },
                    confidence=0.95,
                    evidence=next(
                        (
                            item.evidence
                            for item in metadata_candidates(run)
                            if (item.normalized_value or item.proposed_value) == identifier
                        ),
                        [],
                    ),
                    notes=["exact_contract_identifier"],
                    match_reason="same exact contract identifier",
                )
            )
    return candidates


async def generate_knowledge_proposals(
    session: AsyncSession,
    *,
    document: Document,
    extraction: DocumentExtraction,
    run: IntelligenceRun,
) -> list[KnowledgeProposal]:
    if run.status.value != "completed":
        return []
    # A changed extraction invalidates unresolved candidates from the previous
    # source text. Accepted knowledge remains historical and is never rewritten.
    await session.execute(
        update(KnowledgeProposal)
        .where(
            KnowledgeProposal.document_id == document.id,
            KnowledgeProposal.intelligence_run_id != run.id,
            KnowledgeProposal.status == ProposalStatus.PENDING,
        )
        .values(status=ProposalStatus.SUPERSEDED, resolved_at=datetime.now(UTC))
    )
    await session.refresh(run, attribute_names=["proposals"])
    document.extraction = extraction
    candidates = await organization_candidates(session, run)
    if contract := contract_candidate(document, run):
        candidates.append(contract)
    candidates.extend(temporal_candidates(document, extraction))
    candidates.extend(await relationship_candidates(session, document, run))
    created: list[KnowledgeProposal] = []
    for candidate in candidates:
        identity = proposal_identity(extraction, candidate)
        existing = await session.scalar(
            select(KnowledgeProposal).where(KnowledgeProposal.identity_key == identity)
        )
        if existing is not None:
            continue
        proposal = KnowledgeProposal(
            identity_key=identity,
            proposal_type=candidate.proposal_type,
            document_id=document.id,
            extraction_id=extraction.id,
            intelligence_run_id=run.id,
            knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
            provider=run.provider,
            provider_version=run.provider_version,
            payload=candidate.payload,
            confidence=candidate.confidence,
            evidence=candidate.evidence,
            evidence_verified=bool(candidate.evidence)
            and all(item.get("verified") for item in candidate.evidence),
            validation_notes=candidate.notes,
            possible_existing_organization_id=candidate.possible_existing_organization_id,
            match_reason=candidate.match_reason,
        )
        session.add(proposal)
        created.append(proposal)
    await session.flush()
    return created
