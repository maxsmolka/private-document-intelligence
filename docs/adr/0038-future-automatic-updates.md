# ADR 0038: Future automatic update policy

Status: Accepted

Automatic installation is disabled and unimplemented. Discovery may later run weekly without sending private data. Any future experiment starts with manifest-authorized patch releases, exact digests, a fresh verified backup, no active jobs, a maintenance window, and all checks passing. Minor/major releases remain manual; semver never overrides manifest safety metadata.
