# SEDB v0.3A Field Utility & Convergence Recommendation Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic explainable field-utility assessments, append-only protection guardrails, explicit convergence/reactivation application, and bounded registry assessment.

**Architecture:** `UtilityService` reads existing SEDB evidence and writes immutable assessment rows. It never changes lifecycle state while assessing; explicit apply delegates to `FieldService.transition` after checking the stored evidence basis is still current.

**Tech Stack:** Python 3.11+, SQLite, Python standard library only, existing dependency-free HTTP server/browser UI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-field-utility-convergence-kernel-design.md`

## Global Constraints

- Local-first; do not push or update GitHub.
- No external dependencies, network calls, embeddings, or LLM providers.
- Assessment never auto-mutates lifecycle state.
- Existing v0.2B governance and semantic candidate semantics remain authoritative.
- Assessments and guardrail history are append-only.
- Explicit apply must reject stale evidence bases.
- All production changes follow RED → GREEN TDD.

---

### Task 1: Migration-safe utility schema and immutable assessments

**Files:**
- Modify: `src/sedb/db.py`
- Modify: `tests/test_migration.py`

**Interfaces:**
- Produces `field_utility_assessments`, `field_guardrails`, and immutability triggers.

- [ ] Add a migration test that manually builds the existing SCHEMA + GOVERNANCE_SCHEMA + SEMANTIC_SCHEMA, inserts a field/entity/cell, then opens it through `Database` and asserts the two v0.3A tables exist while IDs/cell data remain unchanged.
- [ ] Add a test that inserts an assessment fixture and verifies direct SQL `UPDATE` and `DELETE` both raise `sqlite3.IntegrityError` with an immutable-assessment message.
- [ ] Run the targeted migration tests and verify RED because the v0.3A tables do not exist.
- [ ] Add idempotent utility DDL and two SQLite immutability triggers to `Database` initialization.
- [ ] Run targeted and full suites GREEN.
- [ ] Commit.

### Task 2: Append-only field guardrails

**Files:**
- Create: `src/sedb/utility.py`
- Create: `tests/test_utility.py`

**Interfaces:**
- Produces `UtilityService.set_guardrail`, `get_guardrail`, `list_guardrail_history`.

- [ ] Write failing tests proving protect/unprotect both require a reason, history remains append-only, and the latest event defines current protection state.
- [ ] Verify RED because `UtilityService` does not exist.
- [ ] Implement field resolution through existing `resolve_field_row` and append-only guardrail methods.
- [ ] Run targeted and full suites GREEN.
- [ ] Commit.

### Task 3: Deterministic utility assessment and recommendations

**Files:**
- Modify: `src/sedb/utility.py`
- Modify: `tests/test_utility.py`

**Interfaces:**
- Produces `assess_field`, `get_assessment`, `list_assessments` and `utility-v1` policy constants.

- [ ] Write failing tests for new-empty `insufficient_evidence`, old-unused `converge_candidate`, protected-old-unused `keep`, Task View-supported sparse `keep`, and score calculation fields.
- [ ] Verify RED.
- [ ] Implement aggregate evidence collection, policy v1 score, deterministic recommendation reasons, basis payload/hash, immutable assessment insert/decode methods.
- [ ] Run targeted and full suites GREEN.
- [ ] Commit.

### Task 4: Semantic redundancy and post-convergence reactivation evidence

**Files:**
- Modify: `src/sedb/utility.py`
- Modify: `tests/test_utility.py`

**Interfaces:**
- Extends metrics with pending semantic redundancy and convergence/post-convergence evidence.

- [ ] Write a failing test showing a pending high-similarity field-to-field candidate reduces the assessment score compared with the same field before the candidate exists.
- [ ] Write failing tests that a post-convergence cell and a post-convergence Task View each produce `reactivate_candidate`.
- [ ] Verify RED.
- [ ] Implement pending semantic-candidate aggregation and latest convergence/cell/view timestamp logic.
- [ ] Run targeted and full suites GREEN.
- [ ] Commit.

### Task 5: Explicit apply with traceability and stale-basis rejection

**Files:**
- Modify: `src/sedb/utility.py`
- Modify: `tests/test_utility.py`

**Interfaces:**
- Produces `apply_assessment(assessment_id, reason, evaluator='')`.

- [ ] Write failing tests that actionable recommendations require an explicit reason, `converge_candidate` applies through `FieldService.transition`, and the resulting `field_evaluations.evidence` contains `assessment_id` and `policy_version` while metrics match the assessment.
- [ ] Write a failing stale-assessment test: assess an old unused field, add a cell, then verify applying the old assessment is rejected.
- [ ] Write a failing test that `keep/review/insufficient_evidence` cannot be applied as lifecycle transitions.
- [ ] Verify RED.
- [ ] Implement basis recomputation, status checks, actionable-pair checks, and delegated transition with assessment evidence/metrics.
- [ ] Run targeted and full suites GREEN.
- [ ] Commit.

### Task 6: Bounded registry assessment

**Files:**
- Modify: `src/sedb/utility.py`
- Modify: `tests/test_utility.py`

**Interfaces:**
- Produces `assess_registry(statuses=('active','converged'), limit_fields=1000, offset=0, evaluator='system:utility', as_of=None)`.

- [ ] Write a failing test creating many fields and asserting `limit_fields` bounds output, selected statuses are respected, and one call produces one immutable assessment per selected field.
- [ ] Verify RED.
- [ ] Refactor evidence gathering so registry assessment uses fixed aggregate SQL passes for selected fields rather than invoking a separate full scan per field.
- [ ] Run targeted and full suites GREEN.
- [ ] Commit.

### Task 7: HTTP API and minimal Field Utility UI

**Files:**
- Modify: `src/sedb/server.py`
- Modify: `src/sedb/web/index.html`
- Modify: `src/sedb/web/app.js`
- Modify: `tests/test_server.py`

**Interfaces:**
- Exposes the six utility/guardrail routes from the design spec.

- [ ] Add failing API tests for field assessment/list, guardrail get/set, registry scan, explicit apply, and stale-apply error response.
- [ ] Add a failing static test for `Field Utility` panel controls and the absence of auto-apply behavior.
- [ ] Verify RED.
- [ ] Add `UtilityService` routing and minimal browser controls for assess/protect/apply/scan.
- [ ] Run pytest and `node --check src/sedb/web/app.js` GREEN.
- [ ] Commit.

### Task 8: v0.3A release checkpoint and 10K utility demo

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/sedb/__init__.py`
- Modify: `src/sedb/server.py`
- Modify: `README.md`
- Create: `docs/RELEASE_NOTES_v0.3A.md`
- Create: `examples/utility_demo.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Release version `0.3.0a1`; produces fresh utility demo/report and final local ZIP.

- [ ] Add a failing health/version assertion for `0.3.0a1`.
- [ ] Verify RED.
- [ ] Update package/server/UI identifiers and user-facing release documentation.
- [ ] Build a fresh governance/utility demo covering insufficient evidence, protected keep, Task View keep, convergence candidate, reactivation candidate, redundancy review, and explicit apply audit.
- [ ] Run a fresh 10,000-field bounded utility assessment and record local counts/runtime without claiming universal performance.
- [ ] Run full pytest, compileall, JS syntax, UTF-8 source validation, Markdown delimiter validation, SQLite integrity checks, manifest verification, and ZIP CRC.
- [ ] Re-extract the final ZIP and rerun the full test suite and integrity checks from the extracted artifact.
- [ ] Commit release checkpoint and keep `local-v0.3a` local.
