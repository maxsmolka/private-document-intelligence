# ADR 0014: Extension boundary

## Status

Accepted at A1.

## Decision

Optional trusted extensions integrate first through authenticated, scoped, versioned HTTP APIs. PDI may later add a small deployment-time manifest for capabilities, navigation, settings and job registration when the first extension exists. Dynamic third-party code loading, a marketplace and database/volume access are prohibited.

## Consequences

PDI remains standalone. Atlas can be added without a premature plugin framework; the first real extension will define the minimum UI composition contract.
