# ADR 0034: Backup before update

Status: Accepted

Every managed release currently requires a new coordinated backup. Its existing manifest, dump, assets, and checksums are verified and its database identity is linked to the update run before execution is enabled. Update backups are operator-protected and excluded from automatic deletion because automatic retention is not implemented.
