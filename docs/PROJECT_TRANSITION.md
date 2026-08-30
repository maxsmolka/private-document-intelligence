# Project transition

PDI remains available as a standalone technical reference and learning baseline after v1.4.1. Feature development is paused and no active milestone is scheduled.

Productive document management will not be actively extended in PDI during this pause. PDI does not migrate, disable, reconfigure, or shut down any other document-management system automatically. Existing deployment, migration, export, backup, restore, and update operations remain explicit operator actions.

PDI remains independent: it owns its own PostgreSQL state and document storage and does not require Paperless, Atlas, Compute Core, or a cloud intelligence provider. Any future use of its APIs or release artifacts should preserve the documented security, provenance, backup, and operator-control boundaries.

This repository contains no productive credentials, private infrastructure details, or automatic transition action.
