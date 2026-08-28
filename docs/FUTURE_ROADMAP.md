# Future roadmap after v1.4.0

These items are explicitly deferred. They are not implemented by the roadmap-completion program and are not prerequisites for PDI to remain a standalone document system.

## TODO A — Atlas Extension Foundation

Assess extension registration, shared PDI identity and authorization, Ask, reasoning, briefings, agents, and cross-source synthesis. Atlas must reuse versioned scoped PDI APIs, retain PDI UUID/page provenance, and never duplicate PDI ownership of documents or document-derived canonical knowledge.

## TODO B — Compute Core Integration Assessment

Evaluate a narrow optional `Execution Service → ComputeCoreExecutor → Compute Core` adapter only when measured OCR, local-LLM, embedding, Atlas, batch, or GPU workloads require it. PDI's PostgreSQL task state remains authoritative. Do not add a second scheduler or integration merely because the seam exists.

## TODO C — Optional unattended patch updates

Reassess unattended patch-only installation only after sufficient real-world experience with the Controlled Update Manager, reliable restore drills, explicit maintenance policy, notification/escalation, and a narrowly documented security-update trust model. Automatic merging or major-version installation remains out of scope.
