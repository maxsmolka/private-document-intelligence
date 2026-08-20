# ADR 0005: Document-backed timeline and deadline semantics

- Status: Accepted
- Date: 2026-08-20

## Context

Dates in private documents may be exact, partial, relative, conditional, or OCR-damaged. Treating all date phrases as exact calendar facts can create unsafe deadlines and actions.

## Decision

Store timeline events and deadlines as typed canonical records with source document, extraction, proposal, exact evidence, and date precision. Preserve ambiguous relative rules verbatim and leave `due_at` empty. Create an action proposal only for an explicit obligation with a grounded exact date. Status transitions are explicit, audited mutations; this milestone performs no notification or calendar side effect.

## Consequences

The UI can distinguish trustworthy exact dates from unresolved rules, and re-analysis cannot silently replace accepted history. Some useful relative dates remain unresolved until a person supplies context; this is an intentional safety tradeoff.
