# SEDB v0.2B Semantic Candidate & Dedup Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic explainable semantic-candidate discovery, review, and bounded field-registry scanning without automatic canonical mutation.

**Architecture:** Introduce `SemanticDedupService` as an advisory layer over v0.2A governance. Candidate scores and reviews are persisted in new migration-safe tables; aliases and relations are written only after explicit review.

**Tech Stack:** Python 3.11+, SQLite, stdlib `difflib`, existing dependency-free HTTP server and vanilla browser UI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-semantic-candidate-dedup-kernel-design.md`

## Global Constraints

- Local-first; do not push or update GitHub.
- No external dependencies, embeddings, network calls, or LLM providers.
- Similarity never auto-merges or auto-aliases.
- Aliases resolve directly to canonical fields only.
- Existing v0.2A databases migrate forward in place.
- All production changes follow RED → GREEN TDD.

---

### Task 1: Migration-safe semantic governance schema

**Files:**
- Modify: `src/sedb/db.py`
- Test: `tests/test_migration.py`

**Interfaces:**
- Produces tables `semantic_candidates`, `semantic_candidate_reviews`, `field_relations`.

- [ ] Add a migration test that opens a v0.2A-shaped database and asserts the three v0.2B tables exist while previous IDs/cells remain unchanged.
- [ ] Run the targeted test and verify it fails because the tables are absent.
- [ ] Add idempotent v0.2B DDL to `Database` initialization.
- [ ] Rerun migration and full regression tests.
- [ ] Commit the green task.

### Task 2: Explainable deterministic scoring

**Files:**
- Create: `src/sedb/semantic.py`
- Create: `tests/test_semantic.py`

**Interfaces:**
- Produces `score_field_pair(left, right) -> dict` with `score` and component signals.

- [ ] Write failing tests for reordered equivalent wording, unrelated wording, and type-conflict penalty.
- [ ] Verify RED because `sedb.semantic` does not exist.
- [ ] Implement tokenizer/Jaccard/character similarity and the weighted score from the spec.
- [ ] Verify targeted and full suites GREEN.
- [ ] Commit.

### Task 3: Proposal candidate scoring and persistence

**Files:**
- Modify: `src/sedb/semantic.py`
- Test: `tests/test_semantic.py`

**Interfaces:**
- Produces `SemanticDedupService.score_proposal(...)`, `list_candidates(...)`.

- [ ] Write failing tests that rank `country_of_author` against `author_country`, enforce default namespace isolation, bound candidate count, and persist signal breakdown.
- [ ] Verify RED.
- [ ] Implement proposal candidate generation, score persistence, and list APIs.
- [ ] Verify GREEN and commit.

### Task 4: Auditable candidate review

**Files:**
- Modify: `src/sedb/semantic.py`
- Test: `tests/test_semantic.py`

**Interfaces:**
- Produces `review_candidate(...)`, `get_review(...)`, `list_relations(...)`.

- [ ] Write failing tests for proposal→alias, canonical alias rejection, related field relation, distinct/ignore audit, and one-review-only behavior.
- [ ] Verify RED.
- [ ] Implement transactional review semantics and canonical relation storage.
- [ ] Verify GREEN and commit.

### Task 5: Bounded canonical registry scan

**Files:**
- Modify: `src/sedb/semantic.py`
- Test: `tests/test_semantic.py`

**Interfaces:**
- Produces `scan_field_similarity(namespace='global', threshold=0.72, max_neighbors=12, limit_fields=None)`.

- [ ] Write failing tests asserting reverse-pair deduplication, bounded pair count, and discovery of nearby lexical duplicates.
- [ ] Verify RED.
- [ ] Implement sorted-neighborhood plus rare-token blocking with per-field candidate caps.
- [ ] Verify GREEN and commit.

### Task 6: HTTP API and minimal governance UI

**Files:**
- Modify: `src/sedb/server.py`
- Modify: `src/sedb/web/index.html`
- Modify: `src/sedb/web/app.js`
- Test: `tests/test_server.py`

**Interfaces:**
- Exposes the seven API routes defined in the spec and proposal-scoring/review UI.

- [ ] Add failing HTTP/static UI tests.
- [ ] Verify RED.
- [ ] Add server routes and minimal UI controls.
- [ ] Verify pytest and `node --check src/sedb/web/app.js` GREEN.
- [ ] Commit.

### Task 7: Release checkpoint and 10K bounded-scan demo

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/sedb/server.py`
- Modify: `README.md`
- Create: `docs/RELEASE_NOTES_v0.2B.md`
- Create: `examples/semantic_scan_demo.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Release version `0.2.0b1`; generates a fresh 10K field demo and scan report.

- [ ] Add a failing health-version assertion for `0.2.0b1`.
- [ ] Verify RED.
- [ ] Update package/server/UI release identifiers and docs.
- [ ] Build fresh demo databases and run bounded 10K scan, recording counts/runtime without claiming universal performance.
- [ ] Run full pytest, compileall, JS syntax, UTF-8 source validation, manifest verification, and ZIP CRC.
- [ ] Re-extract the final ZIP and rerun the full suite from the extracted artifact.
- [ ] Commit release checkpoint and keep branch local.
