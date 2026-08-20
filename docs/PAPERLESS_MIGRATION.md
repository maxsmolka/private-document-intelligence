# Paperless-ngx migration compatibility

The eventual importer will preserve originals, metadata, dates, useful source identifiers, and provenance. Unsupported values will be retained in an import record or reported—never silently discarded. PDI targets migration compatibility, not Paperless schema compatibility.

| Paperless concept | Planned PDI mapping | Current gap |
| --- | --- | --- |
| Document | `Document` plus extraction/proposals | Core mapping exists |
| Correspondent | Future `Organization`/correspondent relation | Not representable yet |
| Document Type | `document_type`, later normalized type entity | Canonical string exists |
| Tags | Future labels/relationships | Not representable yet |
| Custom Fields | Future typed namespaced metadata with source provenance | Not representable yet |
| Storage Paths | Import provenance only; PDI generates its own storage key | Source path not yet modeled |
| Created Date | `document_date` when semantically equivalent | Exists |
| Added Date | `created_at`, preserving source timestamp during import | Import override not implemented |
| Archive Serial Number | Namespaced legacy identifier | Not representable yet |
| Notes | Future document notes | Not representable yet |
| Owner | Future ownership identity | No users/auth yet |
| Permissions | Future access policy after tenancy design | No RBAC yet |
| Original File | Immutable PDI stored original | Exists |
| Archived File | Derived rendition linked to original | Not representable yet |

Import should be staged and resumable: inventory export, verify checksums, copy originals, persist source IDs/raw unsupported metadata, import canonical mappings, schedule extraction only when needed, and produce a reconciliation report. PDI will not overwrite a preserved Paperless original with an archived/OCR rendition.

