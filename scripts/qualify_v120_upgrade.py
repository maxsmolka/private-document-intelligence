"""Seed and verify a realistic synthetic PDI v1.2.0 direct-upgrade fixture.

Run ``seed`` inside the immutable v1.2.0 backend image after its schema reaches
20260826_0013. Run ``verify`` inside the candidate backend after it upgrades the
same PostgreSQL database to head. The fixture contains no production data or
reusable credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select, text

from pdi.core.config import get_settings
from pdi.core.database import session_factory

USER_ID = uuid.UUID("12000000-0000-4000-8000-000000000001")
DOCUMENT_ID = uuid.UUID("12000000-0000-4000-8000-000000000002")
EXTRACTION_ID = uuid.UUID("12000000-0000-4000-8000-000000000003")
ASSET_ID = uuid.UUID("12000000-0000-4000-8000-000000000004")
JOB_ID = uuid.UUID("12000000-0000-4000-8000-000000000005")
RUN_ID = uuid.UUID("12000000-0000-4000-8000-000000000006")
ACCEPTED_METADATA_ID = uuid.UUID("12000000-0000-4000-8000-000000000007")
REJECTED_METADATA_ID = uuid.UUID("12000000-0000-4000-8000-000000000008")
ORGANIZATION_ID = uuid.UUID("12000000-0000-4000-8000-000000000009")
CONTRACT_ID = uuid.UUID("12000000-0000-4000-8000-000000000010")
EVENT_ID = uuid.UUID("12000000-0000-4000-8000-000000000011")
DEADLINE_ID = uuid.UUID("12000000-0000-4000-8000-000000000012")
ACTION_ID = uuid.UUID("12000000-0000-4000-8000-000000000013")
ACCEPTED_KNOWLEDGE_ID = uuid.UUID("12000000-0000-4000-8000-000000000014")
REJECTED_KNOWLEDGE_ID = uuid.UUID("12000000-0000-4000-8000-000000000015")
INGESTION_SOURCE_ID = uuid.UUID("12000000-0000-4000-8000-000000000016")
SAVED_SEARCH_ID = uuid.UUID("12000000-0000-4000-8000-000000000017")
REMINDER_ID = uuid.UUID("12000000-0000-4000-8000-000000000018")
UPDATE_RUN_ID = uuid.UUID("12000000-0000-4000-8000-000000000019")
UPDATE_EVENT_ID = uuid.UUID("12000000-0000-4000-8000-000000000020")

STORAGE_KEY = "v120-direct-upgrade.pdf"
DOCUMENT_BYTES = b"%PDF-1.4\n% synthetic PDI v1.2 direct-upgrade fixture\n%%EOF\n"
DOCUMENT_HASH = hashlib.sha256(DOCUMENT_BYTES).hexdigest()
EXTRACTION_TEXT = (
    "Nordstern Versicherung AG\n"
    "Versicherungsschein: POL-V120-001\n"
    "Gesamtbetrag: 1.234,56 EUR\n"
    "Faellig am 30.09.2026\n"
)
EXTRACTION_HASH = hashlib.sha256(EXTRACTION_TEXT.encode()).hexdigest()
EVIDENCE = [
    {"page": 1, "start": 0, "end": 27, "text": "Nordstern Versicherung AG", "verified": True}
]


async def seed() -> dict[str, object]:
    from pdi.auth.service import (
        create_api_token,
        create_user,
        encrypt_totp_secret,
        hash_password,
        issue_session,
    )
    from pdi.documents.models import Document, DocumentStatus, LifeArea
    from pdi.execution.specification import ResourceClass, TaskPriority, TaskType
    from pdi.ingestion.models import (
        CanonicalMetadataHistory,
        DocumentAsset,
        DocumentAssetKind,
        DocumentExtraction,
        IngestionJob,
        IngestionJobEvent,
        IngestionJobState,
        IntelligenceRun,
        IntelligenceRunStatus,
        MetadataProposal,
        ProposalStatus,
    )
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
        EventType,
        KnowledgeHistory,
        KnowledgeProposal,
        KnowledgeProposalType,
        Organization,
        OrganizationDocument,
        TimelineEvent,
    )
    from pdi.operations.models import ExternalIngestion, ExternalIngestionStatus, RecoveryCode
    from pdi.search.models import SearchDocument

    settings = get_settings()
    storage_path = Path(settings.storage_path)
    await asyncio.to_thread(storage_path.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((storage_path / STORAGE_KEY).write_bytes, DOCUMENT_BYTES)

    async with session_factory() as session:
        existing = await session.get(Document, DOCUMENT_ID)
        if existing is not None:
            raise RuntimeError("The v1.2 direct-upgrade fixture is already present")

        user = await create_user(
            session,
            "v120-upgrade-admin",
            "Synthetic-v120-upgrade-only!",
            commit=False,
        )
        user.id = USER_ID
        user.totp_secret_encrypted = encrypt_totp_secret(settings, "JBSWY3DPEHPK3PXP")
        user.totp_enabled_at = datetime.now(UTC)
        await issue_session(session, user, settings)
        session.add(
            RecoveryCode(
                user_id=USER_ID,
                code_hash=hash_password("synthetic-recovery-code"),
            )
        )
        await session.commit()
        await create_api_token(
            session,
            username=user.username,
            name="Synthetic direct-upgrade token",
            scopes=["documents:read", "search:read", "knowledge:read"],
        )

        document = Document(
            id=DOCUMENT_ID,
            title="Nordstern Versicherung v1.2",
            original_filename="nordstern-v120.pdf",
            mime_type="application/pdf",
            file_size=len(DOCUMENT_BYTES),
            sha256=DOCUMENT_HASH,
            storage_key=STORAGE_KEY,
            document_date=date(2026, 8, 20),
            status=DocumentStatus.NEEDS_REVIEW,
            life_area=LifeArea.INSURANCE,
            document_type="insurance_policy",
            source="upload",
            canonical_metadata={
                "identifier": "POL-V120-001",
                "organization": "Nordstern Versicherung AG",
                "invoice_total": {"amount": "1234.56", "currency": "EUR"},
                "tags": ["insurance", "important"],
            },
        )
        extraction = DocumentExtraction(
            id=EXTRACTION_ID,
            document=document,
            source="pdi",
            provider="synthetic",
            provider_version="1",
            method="native_pdf",
            text=EXTRACTION_TEXT,
            normalized_text=EXTRACTION_TEXT,
            page_count=1,
            pages=[EXTRACTION_TEXT],
            language="de",
            content_hash=EXTRACTION_HASH,
            identity_key=hashlib.sha256(b"v120-extraction").hexdigest(),
            warnings=[],
            extraction_metadata={"fixture": "v1.2.0-direct-upgrade"},
            source_provenance={"release": "v1.2.0"},
        )
        document.canonical_extraction = extraction
        document.assets.append(
            DocumentAsset(
                id=ASSET_ID,
                kind=DocumentAssetKind.ORIGINAL,
                storage_key=STORAGE_KEY,
                mime_type="application/pdf",
                file_size=len(DOCUMENT_BYTES),
                sha256=DOCUMENT_HASH,
                provider="upload",
                provider_version="1",
            )
        )
        job = IngestionJob(
            id=JOB_ID,
            document=document,
            state=IngestionJobState.COMPLETED,
            stage="completed",
            task_type=TaskType.DOCUMENT_INGESTION,
            priority=TaskPriority.HIGH,
            resource_class=ResourceClass.CPU_HEAVY,
            attempt_count=1,
            max_attempts=3,
            timeout_seconds=300,
            idempotency_key="v120-upgrade-job",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        job.events.append(
            IngestionJobEvent(
                from_state="extracting",
                to_state="completed",
                stage="completed",
                worker_id="synthetic-v120-worker",
                detail="synthetic direct-upgrade fixture",
                event_type="transition",
                attempt=1,
                duration_ms=12.5,
                event_metadata={"resource_class": "cpu_heavy"},
            )
        )
        session.add(document)
        await session.flush()

        run = IntelligenceRun(
            id=RUN_ID,
            document_id=DOCUMENT_ID,
            input_extraction_id=EXTRACTION_ID,
            input_content_hash=EXTRACTION_HASH,
            request_key="v120-direct-upgrade-intelligence",
            provider="deterministic",
            provider_version="1",
            schema_version="2",
            status=IntelligenceRunStatus.COMPLETED,
            is_current=True,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            result={"fixture": True},
        )
        accepted_metadata = MetadataProposal(
            id=ACCEPTED_METADATA_ID,
            document_id=DOCUMENT_ID,
            intelligence_run_id=RUN_ID,
            field_name="organization",
            proposed_value="Nordstern Versicherung AG",
            normalized_value="Nordstern Versicherung AG",
            source="document_intelligence",
            provider="deterministic",
            confidence=0.99,
            evidence=EVIDENCE,
            evidence_verified=True,
            validation_notes=[],
            is_critical=True,
            status=ProposalStatus.ACCEPTED,
            confirmed_at=datetime.now(UTC),
        )
        rejected_metadata = MetadataProposal(
            id=REJECTED_METADATA_ID,
            document_id=DOCUMENT_ID,
            intelligence_run_id=RUN_ID,
            field_name="other_amount",
            proposed_value="9999.99 EUR",
            normalized_value="9999.99 EUR",
            source="document_intelligence",
            provider="deterministic",
            confidence=0.51,
            evidence=EVIDENCE,
            evidence_verified=True,
            validation_notes=["synthetic rejected proposal"],
            status=ProposalStatus.REJECTED,
            confirmed_at=datetime.now(UTC),
        )
        session.add_all([run, accepted_metadata, rejected_metadata])
        await session.flush()
        session.add(
            CanonicalMetadataHistory(
                document_id=DOCUMENT_ID,
                field_name="organization",
                previous_value=None,
                new_value="Nordstern Versicherung AG",
                source_proposal_id=ACCEPTED_METADATA_ID,
                confirmation_source="user",
                confirmed_at=datetime.now(UTC),
            )
        )
        await session.flush()

        accepted_knowledge = KnowledgeProposal(
            id=ACCEPTED_KNOWLEDGE_ID,
            identity_key=hashlib.sha256(b"v120-accepted-knowledge").hexdigest(),
            proposal_type=KnowledgeProposalType.ORGANIZATION,
            document_id=DOCUMENT_ID,
            extraction_id=EXTRACTION_ID,
            intelligence_run_id=RUN_ID,
            knowledge_schema_version="1",
            provider="deterministic",
            provider_version="1",
            payload={"canonical_name": "Nordstern Versicherung AG"},
            confidence=0.99,
            evidence=EVIDENCE,
            evidence_verified=True,
            validation_notes=[],
            status=ProposalStatus.ACCEPTED,
            resolved_resource_id=ORGANIZATION_ID,
            resolved_at=datetime.now(UTC),
        )
        rejected_knowledge = KnowledgeProposal(
            id=REJECTED_KNOWLEDGE_ID,
            identity_key=hashlib.sha256(b"v120-rejected-knowledge").hexdigest(),
            proposal_type=KnowledgeProposalType.CONTRACT,
            document_id=DOCUMENT_ID,
            extraction_id=EXTRACTION_ID,
            intelligence_run_id=RUN_ID,
            knowledge_schema_version="1",
            provider="deterministic",
            provider_version="1",
            payload={"title": "Rejected synthetic contract"},
            confidence=0.55,
            evidence=EVIDENCE,
            evidence_verified=True,
            validation_notes=["synthetic rejection"],
            status=ProposalStatus.REJECTED,
            resolved_at=datetime.now(UTC),
        )
        session.add_all([accepted_knowledge, rejected_knowledge])
        await session.flush()

        organization = Organization(
            id=ORGANIZATION_ID,
            canonical_name="Nordstern Versicherung AG",
            normalized_name="nordstern versicherung ag",
            organization_type="insurer",
            source_document_id=DOCUMENT_ID,
            source_extraction_id=EXTRACTION_ID,
            intelligence_run_id=RUN_ID,
            source_proposal_id=ACCEPTED_KNOWLEDGE_ID,
            evidence=EVIDENCE,
        )
        contract = Contract(
            id=CONTRACT_ID,
            title="Nordstern Policy",
            contract_type=ContractType.INSURANCE,
            status=ContractStatus.ACTIVE,
            organization_id=ORGANIZATION_ID,
            reference_identifier="POL-V120-001",
            start_date=date(2026, 8, 1),
            source_document_id=DOCUMENT_ID,
            source_extraction_id=EXTRACTION_ID,
            intelligence_run_id=RUN_ID,
            evidence=EVIDENCE,
        )
        event = TimelineEvent(
            id=EVENT_ID,
            event_type=EventType.CONTRACT_STARTED,
            title="Nordstern policy started",
            event_date=date(2026, 8, 1),
            event_date_precision=DatePrecision.EXACT,
            life_area=LifeArea.INSURANCE,
            organization_id=ORGANIZATION_ID,
            contract_id=CONTRACT_ID,
            source_document_id=DOCUMENT_ID,
            source_extraction_id=EXTRACTION_ID,
            intelligence_run_id=RUN_ID,
            evidence=EVIDENCE,
        )
        deadline = Deadline(
            id=DEADLINE_ID,
            title="Pay Nordstern invoice",
            due_at=date(2026, 9, 30),
            deadline_type=DeadlineType.PAYMENT,
            status=DeadlineStatus.OPEN,
            organization_id=ORGANIZATION_ID,
            contract_id=CONTRACT_ID,
            source_document_id=DOCUMENT_ID,
            source_extraction_id=EXTRACTION_ID,
            evidence=EVIDENCE,
        )
        action = ActionItem(
            id=ACTION_ID,
            title="Review Nordstern renewal",
            status=ActionStatus.OPEN,
            due_at=date(2026, 9, 30),
            priority=ActionPriority.HIGH,
            life_area=LifeArea.INSURANCE,
            organization_id=ORGANIZATION_ID,
            contract_id=CONTRACT_ID,
            deadline_id=DEADLINE_ID,
            source_document_id=DOCUMENT_ID,
            source_extraction_id=EXTRACTION_ID,
            evidence=EVIDENCE,
        )
        session.add(organization)
        await session.flush()
        session.add(contract)
        await session.flush()
        session.add_all([event, deadline])
        await session.flush()
        session.add(action)
        await session.flush()
        session.add_all(
            [
                OrganizationDocument(
                    organization_id=ORGANIZATION_ID,
                    document_id=DOCUMENT_ID,
                    source_proposal_id=ACCEPTED_KNOWLEDGE_ID,
                ),
                ContractDocument(
                    contract_id=CONTRACT_ID,
                    document_id=DOCUMENT_ID,
                    relationship_type=ContractDocumentType.POLICY,
                ),
                KnowledgeHistory(
                    resource_type="organization",
                    resource_id=ORGANIZATION_ID,
                    action="created",
                    new_value={"canonical_name": "Nordstern Versicherung AG"},
                    source_proposal_id=ACCEPTED_KNOWLEDGE_ID,
                    confirmation_source="user",
                ),
                ExternalIngestion(
                    source_type="consume",
                    source_key="v120-direct-upgrade/source.pdf",
                    content_hash=DOCUMENT_HASH,
                    observed_size=len(DOCUMENT_BYTES),
                    # Schema 0013 stored this as int32; migration 0017 widens it.
                    observed_mtime_ns=1_777_777_777,
                    status=ExternalIngestionStatus.INGESTED,
                    document_id=DOCUMENT_ID,
                    provenance={"fixture": "v1.2.0-direct-upgrade"},
                ),
                SearchDocument(
                    document_id=DOCUMENT_ID,
                    extraction_id=EXTRACTION_ID,
                    extraction_content_hash=EXTRACTION_HASH,
                    search_content_hash=hashlib.sha256(b"v120-search").hexdigest(),
                    title_text=document.title,
                    organization_text="Nordstern Versicherung AG",
                    identifier_text="POL-V120-001",
                    metadata_text="insurance_policy POL-V120-001 1234.56 EUR",
                    body_text=EXTRACTION_TEXT,
                    pages=[EXTRACTION_TEXT],
                    search_vector="nordstern versicherung pol v120",
                ),
            ]
        )
        await session.commit()

        counts = {
            "users": await session.scalar(select(func.count()).select_from(type(user))),
            "documents": await session.scalar(select(func.count()).select_from(Document)),
            "assets": await session.scalar(select(func.count()).select_from(DocumentAsset)),
            "extractions": await session.scalar(
                select(func.count()).select_from(DocumentExtraction)
            ),
            "intelligence_runs": await session.scalar(
                select(func.count()).select_from(IntelligenceRun)
            ),
            "metadata_proposals": await session.scalar(
                select(func.count()).select_from(MetadataProposal)
            ),
            "knowledge_proposals": await session.scalar(
                select(func.count()).select_from(KnowledgeProposal)
            ),
            "jobs": await session.scalar(select(func.count()).select_from(IngestionJob)),
            "job_events": await session.scalar(select(func.count()).select_from(IngestionJobEvent)),
        }
    return {"result": "SEEDED", "schema": "20260826_0013", "counts": counts}


async def scalar(session: object, sql: str) -> object:
    return await session.scalar(text(sql))  # type: ignore[attr-defined,no-any-return]


async def enrich() -> dict[str, object]:
    """Add representative post-v1.2 state before backup/restore qualification."""
    from pdi.administration.models import OperationalSetting
    from pdi.knowledge.models import ReminderKind, ReminderNotification
    from pdi.operations.models import IngestionSource, IngestionSourceHealth
    from pdi.search.models import SavedSearch
    from pdi.updates.models import UpdateEvent, UpdateRun, UpdateState

    async with session_factory() as session:
        if await session.get(IngestionSource, INGESTION_SOURCE_ID) is not None:
            raise RuntimeError("The post-upgrade qualification fixture is already present")
        session.add_all(
            [
                OperationalSetting(
                    key="reminder_horizon_days",
                    value=45,
                    updated_by_user_id=USER_ID,
                ),
                IngestionSource(
                    id=INGESTION_SOURCE_ID,
                    source_key="synthetic-final-qualification",
                    source_type="consume",
                    display_name="Synthetic final qualification",
                    enabled=True,
                    health=IngestionSourceHealth.HEALTHY,
                    safe_configuration={"path": "/consume", "recursive": False},
                    last_report={"result": "healthy", "synthetic": True},
                ),
                SavedSearch(
                    id=SAVED_SEARCH_ID,
                    owner_key=str(USER_ID),
                    name="Synthetic insurance review",
                    filters={"life_area": ["insurance"], "status": ["needs_review"]},
                ),
                ReminderNotification(
                    id=REMINDER_ID,
                    deadline_id=DEADLINE_ID,
                    kind=ReminderKind.UPCOMING,
                    scheduled_for=date(2026, 8, 28),
                    due_at=date(2026, 9, 30),
                ),
                UpdateRun(
                    id=UPDATE_RUN_ID,
                    state=UpdateState.COMPLETED,
                    active_guard=None,
                    from_version="1.3.0",
                    to_version="1.4.0",
                    release_commit="0" * 40,
                    schema_before="20260828_0019",
                    schema_target="20260828_0020",
                    schema_after="20260828_0020",
                    previous_backend_digest="sha256:" + "1" * 64,
                    previous_web_digest="sha256:" + "2" * 64,
                    target_backend_digest="sha256:" + "3" * 64,
                    target_web_digest="sha256:" + "4" * 64,
                    migration_required=True,
                    reindex_required=False,
                    backup_required=True,
                    rollback_mode="backup_restore",
                    expected_downtime="brief",
                    architecture="amd64",
                    compatibility="compatible",
                    warnings=[],
                    preflight={"synthetic": True, "result": "pass"},
                    started_by_user_id=USER_ID,
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        session.add(
            UpdateEvent(
                id=UPDATE_EVENT_ID,
                update_run_id=UPDATE_RUN_ID,
                event_type="state_transition",
                from_state="verifying",
                to_state="completed",
                safe_detail="Synthetic final qualification event",
                duration_ms=42.0,
            )
        )
        await session.commit()
    return {
        "result": "ENRICHED",
        "settings": 1,
        "ingestion_sources": 1,
        "saved_searches": 1,
        "reminders": 1,
        "update_runs": 1,
        "update_events": 1,
    }


async def verify() -> dict[str, object]:
    from pdi.auth.service import decrypt_totp_secret
    from pdi.operations.models import LocalUser

    settings = get_settings()
    asset_path = Path(settings.storage_path) / STORAGE_KEY
    if not asset_path.is_file() or asset_path.read_bytes() != DOCUMENT_BYTES:
        raise RuntimeError("The preserved v1.2 original asset does not match")

    async with session_factory() as session:
        user = await session.get(LocalUser, USER_ID)
        if user is None or user.totp_secret_encrypted is None:
            raise RuntimeError("The preserved v1.2 TOTP state is missing")
        totp_secret = decrypt_totp_secret(settings, user.totp_secret_encrypted)
        checks = {
            "alembic_head": await scalar(session, "SELECT version_num FROM alembic_version"),
            "document_id": await scalar(
                session, f"SELECT id::text FROM documents WHERE id = '{DOCUMENT_ID}'"
            ),
            "document_hash": await scalar(
                session, f"SELECT sha256 FROM documents WHERE id = '{DOCUMENT_ID}'"
            ),
            "asset_hash": await scalar(
                session, f"SELECT sha256 FROM document_assets WHERE id = '{ASSET_ID}'"
            ),
            "canonical_extraction": await scalar(
                session,
                f"SELECT canonical_extraction_id::text FROM documents WHERE id = '{DOCUMENT_ID}'",
            ),
            "extraction_hash": await scalar(
                session,
                f"SELECT content_hash FROM document_extractions WHERE id = '{EXTRACTION_ID}'",
            ),
            "intelligence_runs": await scalar(session, "SELECT count(*) FROM intelligence_runs"),
            "accepted_metadata": await scalar(
                session, "SELECT count(*) FROM metadata_proposals WHERE status = 'accepted'"
            ),
            "rejected_metadata": await scalar(
                session, "SELECT count(*) FROM metadata_proposals WHERE status = 'rejected'"
            ),
            "accepted_knowledge": await scalar(
                session, "SELECT count(*) FROM knowledge_proposals WHERE status = 'accepted'"
            ),
            "rejected_knowledge": await scalar(
                session, "SELECT count(*) FROM knowledge_proposals WHERE status = 'rejected'"
            ),
            "organizations": await scalar(session, "SELECT count(*) FROM organizations"),
            "contracts": await scalar(session, "SELECT count(*) FROM contracts"),
            "events": await scalar(session, "SELECT count(*) FROM timeline_events"),
            "deadlines": await scalar(session, "SELECT count(*) FROM deadlines"),
            "actions": await scalar(session, "SELECT count(*) FROM action_items"),
            "search_projections": await scalar(session, "SELECT count(*) FROM search_documents"),
            "search_tags": await scalar(
                session,
                "SELECT string_agg(tag, E'\\n' ORDER BY tag) "
                "FROM search_documents, "
                "unnest(string_to_array(tags_text, E'\\n')) AS tag "
                f"WHERE document_id = '{DOCUMENT_ID}'",
            ),
            "search_amount": str(
                await scalar(
                    session,
                    "SELECT amount_value FROM search_documents "
                    f"WHERE document_id = '{DOCUMENT_ID}'",
                )
            ),
            "users": await scalar(session, "SELECT count(*) FROM local_users"),
            "totp_users": await scalar(
                session,
                "SELECT count(*) FROM local_users "
                "WHERE totp_secret_encrypted IS NOT NULL AND totp_enabled_at IS NOT NULL",
            ),
            "totp_secret_decrypts": totp_secret == "JBSWY3DPEHPK3PXP",
            "sessions": await scalar(session, "SELECT count(*) FROM user_sessions"),
            "api_tokens": await scalar(session, "SELECT count(*) FROM api_tokens"),
            "recovery_codes": await scalar(session, "SELECT count(*) FROM recovery_codes"),
            "jobs": await scalar(session, "SELECT count(*) FROM ingestion_jobs"),
            "job_events": await scalar(session, "SELECT count(*) FROM ingestion_job_events"),
            "external_ingestions": await scalar(
                session, "SELECT count(*) FROM external_ingestions"
            ),
            "external_attempt_default": await scalar(
                session,
                "SELECT attempt_count FROM external_ingestions "
                "WHERE source_key = 'v120-direct-upgrade/source.pdf'",
            ),
            "ingestion_sources_table": await scalar(
                session, "SELECT to_regclass('public.ingestion_sources') IS NOT NULL"
            ),
            "settings_table": await scalar(
                session, "SELECT to_regclass('public.operational_settings') IS NOT NULL"
            ),
            "saved_searches_table": await scalar(
                session, "SELECT to_regclass('public.saved_searches') IS NOT NULL"
            ),
            "reminders_table": await scalar(
                session, "SELECT to_regclass('public.reminder_notifications') IS NOT NULL"
            ),
            "operational_settings": await scalar(
                session,
                "SELECT count(*) FROM operational_settings "
                "WHERE key = 'reminder_horizon_days' AND value::text = '45'",
            ),
            "ingestion_sources": await scalar(
                session,
                f"SELECT count(*) FROM ingestion_sources WHERE id = '{INGESTION_SOURCE_ID}' "
                "AND enabled IS TRUE AND health = 'healthy'",
            ),
            "saved_searches": await scalar(
                session, f"SELECT count(*) FROM saved_searches WHERE id = '{SAVED_SEARCH_ID}'"
            ),
            "reminders": await scalar(
                session,
                f"SELECT count(*) FROM reminder_notifications WHERE id = '{REMINDER_ID}'",
            ),
            "update_runs": await scalar(
                session,
                f"SELECT count(*) FROM update_runs WHERE id = '{UPDATE_RUN_ID}' "
                "AND state = 'completed'",
            ),
            "update_events": await scalar(
                session,
                f"SELECT count(*) FROM update_events WHERE id = '{UPDATE_EVENT_ID}'",
            ),
            "deadline_snoozed_default": await scalar(
                session, f"SELECT snoozed_until FROM deadlines WHERE id = '{DEADLINE_ID}'"
            ),
        }

    expected = {
        "alembic_head": "20260828_0020",
        "document_id": str(DOCUMENT_ID),
        "document_hash": DOCUMENT_HASH,
        "asset_hash": DOCUMENT_HASH,
        "canonical_extraction": str(EXTRACTION_ID),
        "extraction_hash": EXTRACTION_HASH,
        "intelligence_runs": 1,
        "accepted_metadata": 1,
        "rejected_metadata": 1,
        "accepted_knowledge": 1,
        "rejected_knowledge": 1,
        "organizations": 1,
        "contracts": 1,
        "events": 1,
        "deadlines": 1,
        "actions": 1,
        "search_projections": 1,
        "search_tags": "important\ninsurance",
        "search_amount": "1234.56",
        "users": 1,
        "totp_users": 1,
        "totp_secret_decrypts": True,
        "sessions": 1,
        "api_tokens": 1,
        "recovery_codes": 1,
        "jobs": 1,
        "job_events": 1,
        "external_ingestions": 1,
        "external_attempt_default": 0,
        "ingestion_sources_table": True,
        "settings_table": True,
        "saved_searches_table": True,
        "reminders_table": True,
        "operational_settings": 1,
        "ingestion_sources": 1,
        "saved_searches": 1,
        "reminders": 1,
        "update_runs": 1,
        "update_events": 1,
        "deadline_snoozed_default": None,
    }
    failures = {
        key: {"expected": expected[key], "actual": value}
        for key, value in checks.items()
        if value != expected[key]
    }
    if failures:
        raise RuntimeError(json.dumps(failures, default=str, sort_keys=True))
    return {"result": "PASS", "checks": checks, "asset_bytes": len(DOCUMENT_BYTES)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "enrich", "verify"))
    arguments = parser.parse_args()
    operations = {"seed": seed, "enrich": enrich, "verify": verify}
    result = asyncio.run(operations[arguments.mode]())
    print(json.dumps(result, indent=2, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
