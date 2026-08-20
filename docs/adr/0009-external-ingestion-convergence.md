# ADR 0009: External ingestion convergence

Status: accepted

Upload, consume-folder, mail, and migration entrypoints converge on shared validation/storage/document services. Durable source identities provide restart safety and deduplication; the existing worker remains the sole extraction/OCR path. Separate pipelines were rejected because they would diverge on file safety, hashes, queue semantics, and provenance.
