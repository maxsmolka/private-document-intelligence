# ADR 0022: Resource classification and admission

## Status

Accepted.

## Decision

Use coarse PDI resource classes (`cpu_light`, `cpu_heavy`, `io_heavy`, `ocr`, `local_ai`, `maintenance`) and static typed limits. Serialize the short admission decision in PostgreSQL and count durable active jobs. Use durable leases for OCR and local-AI stages.

## Consequences

Backlog does not create uncontrolled consumption, multiple worker processes share limits, and no unreliable host telemetry or generic allocator is introduced.
