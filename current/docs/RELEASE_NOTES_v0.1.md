# SEDB Local v0.1 — Release Notes

Date: 2026-08-20

## Checkpoint purpose

This checkpoint establishes the first executable implementation of the SEDB Unbounded Dynamic Field Layer. It is intentionally local-first and is not automatically synchronized to GitHub.

## Implemented

- SQLite dynamic field registry.
- Sparse JSON cell store.
- True blank-by-absence semantics.
- 10,000-field bulk registration.
- Field lifecycle and audit events.
- Mandatory convergence reason.
- Converged-field reactivation with reason.
- Structured field evaluations.
- Field proposal queue.
- Entity service.
- Task-view projections and bounded field windows.
- Search and sparsity statistics.
- CSV and JSONL exchange.
- Local HTTP API.
- Browser UI.
- CLI for init, demo, stats, and serve.
- Automated pytest suite.

## Deliberately deferred

- remote synchronization;
- PostgreSQL / DuckDB backends;
- authentication;
- production multi-user concurrency;
- vector search;
- direct LLM provider integration;
- semantic proposal deduplication;
- public software license selection.

## Compatibility

Validated target: Python 3.13 with SQLite 3.46. Runtime code uses only the Python standard library.
