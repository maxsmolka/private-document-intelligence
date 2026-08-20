"""Add proposal-first relational document knowledge model."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0007"
down_revision: str | None = "20260820_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name)


def existing_enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    op.create_table(
        "knowledge_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column(
            "proposal_type",
            enum(
                "knowledge_proposal_type",
                "organization",
                "contract",
                "document_relationship",
                "event",
                "deadline",
                "action_item",
                "merge",
            ),
            nullable=False,
        ),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("intelligence_run_id", sa.Uuid(), nullable=True),
        sa.Column("knowledge_schema_version", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_verified", sa.Boolean(), nullable=False),
        sa.Column("validation_notes", sa.JSON(), nullable=False),
        sa.Column("possible_existing_organization_id", sa.Uuid(), nullable=True),
        sa.Column("match_reason", sa.String(255), nullable=True),
        sa.Column(
            "status",
            existing_enum(
                "metadata_proposal_status", "pending", "accepted", "rejected", "superseded"
            ),
            nullable=False,
        ),
        sa.Column("resolved_resource_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_id"], ["document_extractions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["intelligence_run_id"], ["intelligence_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("identity_key", name="uq_knowledge_proposals_identity"),
    )
    op.create_index(
        "ix_knowledge_proposals_review",
        "knowledge_proposals",
        ["status", "proposal_type", "created_at"],
    )
    op.create_index(
        "ix_knowledge_proposals_document",
        "knowledge_proposals",
        ["document_id", "created_at"],
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("organization_type", sa.String(100), nullable=True),
        sa.Column(
            "status", enum("organization_status", "active", "inactive", "merged"), nullable=False
        ),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=True),
        sa.Column("intelligence_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["merged_into_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_extraction_id"], ["document_extractions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["intelligence_run_id"], ["intelligence_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_organizations_normalized_name", "organizations", ["normalized_name"])
    op.create_index("ix_organizations_status_name", "organizations", ["status", "canonical_name"])
    op.create_table(
        "organization_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("normalized_alias", sa.String(255), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "normalized_alias", name="uq_org_alias_normalized"),
    )
    op.create_index(
        "ix_organization_aliases_normalized", "organization_aliases", ["normalized_alias"]
    )
    op.create_table(
        "organization_documents",
        sa.Column("organization_id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), primary_key=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_table(
        "organization_merge_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_organization_id", sa.Uuid(), nullable=False),
        sa.Column("target_organization_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("confirmation_source", sa.String(50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("source_organization_id", name="uq_organization_merge_source"),
    )
    op.create_table(
        "contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "contract_type",
            enum(
                "contract_type",
                "insurance",
                "subscription",
                "utility",
                "banking",
                "loan",
                "lease",
                "employment",
                "telecommunications",
                "service",
                "other",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            enum("contract_status", "active", "pending", "ended", "cancelled", "unknown"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("reference_identifier", sa.String(255), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("renewal_date", sa.Date(), nullable=True),
        sa.Column("cancellation_deadline", sa.Date(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=True),
        sa.Column("intelligence_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_extraction_id"], ["document_extractions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["intelligence_run_id"], ["intelligence_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_contracts_reference", "contracts", ["reference_identifier"])
    op.create_index("ix_contracts_organization_status", "contracts", ["organization_id", "status"])
    op.create_index("ix_contracts_dates", "contracts", ["start_date", "end_date"])
    op.create_table(
        "contract_documents",
        sa.Column("contract_id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "relationship_type",
            enum(
                "contract_document_type",
                "contract_document",
                "invoice_for_contract",
                "renewal_notice",
                "cancellation_notice",
                "confirmation",
                "amendment",
                "terms",
                "policy",
                "statement",
            ),
            nullable=False,
        ),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_contract_documents_document", "contract_documents", ["document_id"])
    op.create_table(
        "document_relationships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("target_document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relationship_type",
            enum(
                "document_relationship_type",
                "supersedes",
                "amends",
                "responds_to",
                "confirms",
                "cancels",
                "renews",
                "belongs_to_same_case",
                "duplicate_of",
                "derived_from",
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("intelligence_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["intelligence_run_id"], ["intelligence_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "source_document_id",
            "target_document_id",
            "relationship_type",
            name="uq_document_relationship",
        ),
    )
    op.create_index(
        "ix_document_relationships_target", "document_relationships", ["target_document_id"]
    )
    op.create_table(
        "deadlines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("due_at", sa.Date(), nullable=True),
        sa.Column("original_rule", sa.String(500), nullable=True),
        sa.Column(
            "deadline_type",
            enum(
                "deadline_type",
                "payment",
                "cancellation",
                "renewal",
                "response",
                "submission",
                "appointment",
                "other",
            ),
            nullable=False,
        ),
        sa.Column(
            "status", enum("deadline_status", "open", "completed", "dismissed"), nullable=False
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("contract_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_deadlines_upcoming", "deadlines", ["status", "due_at"])
    op.create_table(
        "timeline_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_type",
            enum(
                "timeline_event_type",
                "document_received",
                "contract_started",
                "contract_changed",
                "contract_renewed",
                "contract_cancelled",
                "contract_ended",
                "payment_due",
                "invoice_issued",
                "policy_changed",
                "tariff_changed",
                "deadline_set",
                "official_decision",
                "other",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column(
            "event_date_precision",
            enum("date_precision", "exact", "month", "year", "unknown"),
            nullable=False,
        ),
        sa.Column(
            "life_area",
            existing_enum(
                "life_area",
                "finance",
                "insurance",
                "vehicle",
                "home",
                "health",
                "tax",
                "work",
                "travel",
                "personal",
                "other",
            ),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("contract_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("intelligence_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["intelligence_run_id"], ["intelligence_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_timeline_events_date", "timeline_events", ["event_date", "id"])
    op.create_index("ix_timeline_events_filters", "timeline_events", ["life_area", "event_type"])
    op.create_index("ix_timeline_events_organization", "timeline_events", ["organization_id"])
    op.create_index("ix_timeline_events_contract", "timeline_events", ["contract_id"])
    op.create_table(
        "action_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", enum("action_status", "open", "completed", "dismissed"), nullable=False
        ),
        sa.Column("due_at", sa.Date(), nullable=True),
        sa.Column("priority", enum("action_priority", "low", "normal", "high"), nullable=False),
        sa.Column(
            "life_area",
            existing_enum(
                "life_area",
                "finance",
                "insurance",
                "vehicle",
                "home",
                "health",
                "tax",
                "work",
                "travel",
                "personal",
                "other",
            ),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("contract_id", sa.Uuid(), nullable=True),
        sa.Column("deadline_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deadline_id"], ["deadlines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_action_items_open", "action_items", ["status", "due_at"])
    op.create_table(
        "knowledge_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("previous_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("confirmation_source", sa.String(50), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["knowledge_proposals.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_knowledge_history_resource",
        "knowledge_history",
        ["resource_type", "resource_id", "created_at"],
    )


def downgrade() -> None:
    for table in (
        "knowledge_history",
        "action_items",
        "timeline_events",
        "deadlines",
        "document_relationships",
        "contract_documents",
        "contracts",
        "organization_merge_history",
        "organization_documents",
        "organization_aliases",
        "organizations",
        "knowledge_proposals",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name in (
            "action_priority",
            "action_status",
            "date_precision",
            "timeline_event_type",
            "deadline_status",
            "deadline_type",
            "document_relationship_type",
            "contract_document_type",
            "contract_status",
            "contract_type",
            "organization_status",
            "knowledge_proposal_type",
        ):
            postgresql.ENUM(name=name).drop(bind, checkfirst=True)
