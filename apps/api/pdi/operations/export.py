import asyncio
import enum
import json
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document
from pdi.ingestion.models import (
    CanonicalMetadataHistory,
    DocumentAsset,
    DocumentAssetKind,
    DocumentExtraction,
    ExtractionComparison,
    ExtractionPromotion,
    IntelligenceRun,
    MetadataProposal,
)
from pdi.knowledge.models import (
    ActionItem,
    Contract,
    ContractDocument,
    Deadline,
    DocumentRelationship,
    KnowledgeHistory,
    KnowledgeProposal,
    Organization,
    OrganizationAlias,
    OrganizationDocument,
    OrganizationMergeHistory,
    TimelineEvent,
)
from pdi.operations.backup import write_checksums
from pdi.operations.models import DocumentNote, DocumentTag, MigrationItem, MigrationRun, Tag
from pdi.storage.base import StorageBackend
from pdi.version import PDI_VERSION

EXPORT_FORMAT_VERSION = "1"
EXPORT_MODELS = (
    Document,
    DocumentAsset,
    DocumentExtraction,
    ExtractionComparison,
    ExtractionPromotion,
    CanonicalMetadataHistory,
    IntelligenceRun,
    MetadataProposal,
    Organization,
    OrganizationAlias,
    OrganizationDocument,
    OrganizationMergeHistory,
    Contract,
    ContractDocument,
    DocumentRelationship,
    TimelineEvent,
    Deadline,
    ActionItem,
    KnowledgeProposal,
    KnowledgeHistory,
    Tag,
    DocumentTag,
    DocumentNote,
    MigrationRun,
    MigrationItem,
)


def resolved(path: Path) -> Path:
    return path.resolve()


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, enum.Enum)):
        return str(value.value if isinstance(value, enum.Enum) else value)
    return value


def model_dict(value: Any) -> dict[str, Any]:
    return {
        column.name: json_value(getattr(value, column.name)) for column in value.__table__.columns
    }


async def create_export(
    destination: Path, *, session: AsyncSession, storage: StorageBackend
) -> dict[str, Any]:
    target = resolved(destination)
    if target.exists():
        raise ValueError("Export destination must not already exist")
    data = target / "data"
    originals = target / "originals"
    data.mkdir(parents=True)
    originals.mkdir()
    counts: dict[str, int] = {}
    for model in EXPORT_MODELS:
        rows = list(await session.scalars(select(model)))
        name = model.__tablename__
        counts[name] = len(rows)
        (data / f"{name}.json").write_text(
            json.dumps([model_dict(row) for row in rows], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    original_assets = list(
        await session.scalars(
            select(DocumentAsset).where(DocumentAsset.kind == DocumentAssetKind.ORIGINAL)
        )
    )
    for asset in original_assets:
        await asyncio.to_thread(
            shutil.copy2, storage.path_for(asset.storage_key), originals / asset.storage_key
        )
    manifest = {
        "format": "pdi-export",
        "format_version": EXPORT_FORMAT_VERSION,
        "pdi_version": PDI_VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "counts": counts,
        "original_count": len(original_assets),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums = write_checksums(target)
    return {**manifest, "path": str(target), "checked_files": len(checksums)}
