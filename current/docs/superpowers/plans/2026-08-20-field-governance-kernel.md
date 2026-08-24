# SEDB v0.2A Field Governance Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build deterministic field governance on top of SEDB v0.1 without breaking sparse storage or existing databases.

**Architecture:** Preserve `fields` and sparse `cells` as canonical runtime state, add migration-safe governance metadata/tables, centralize deterministic field resolution, and expose proposal decisions plus alias/version/lineage operations through services and HTTP API. Browser UI adds only the minimum proposal governance surface in this checkpoint.

**Tech Stack:** Python 3.11+, SQLite, standard-library HTTP server, vanilla HTML/JavaScript, pytest; no runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-field-governance-kernel-design.md`

## Global Constraints

- Local-first only; do not push this checkpoint to GitHub.
- Preserve v0.1 blank-by-absence and sparse-cell semantics.
- Existing v0.1 SQLite files must forward-migrate automatically and retain IDs/data.
- Normalization is deterministic and model-free; no embeddings or external AI providers.
- Merge/split records lineage only; it does not silently migrate cell values.
- New production behavior must follow TDD: failing test first, then minimal implementation.

---

### Task 1: Migration-safe governance schema and naming

**Files:**
- Create: `src/sedb/naming.py`
- Modify: `src/sedb/db.py`
- Create: `tests/test_migration.py`

**Interfaces:**
- Produces: `normalize_field_key(value: str) -> str`
- Produces: `Database` auto-migration for v0.1 database files.

- [x] **Step 1:** Write a failing migration test that constructs a literal v0.1 SQLite schema/data fixture, opens it with current `Database`, and expects governance columns/tables plus one version snapshot while preserving field/entity/cell IDs.
- [x] **Step 2:** Run `pytest tests/test_migration.py -v` and confirm failure because governance schema is absent.
- [x] **Step 3:** Write normalization tests covering NFKC/case/separator normalization and empty normalization rejection.
- [x] **Step 4:** Run the new normalization tests and confirm failure because `sedb.naming` is absent.
- [x] **Step 5:** Implement `normalize_field_key` and idempotent forward migration in `Database.__init__` using `ALTER TABLE ... ADD COLUMN` only when missing, governance table creation, normalized-key backfill, and initial field-version backfill.
- [x] **Step 6:** Run `pytest tests/test_migration.py -v` until green, then run all existing tests.
- [x] **Step 7:** Commit migration/naming changes.

### Task 2: Canonical identity and alias resolution

**Files:**
- Create: `src/sedb/governance.py`
- Modify: `src/sedb/fields.py`
- Modify: `src/sedb/entities.py`
- Modify: `src/sedb/views.py`
- Create: `tests/test_governance.py`

**Interfaces:**
- Produces: `FieldGovernanceService.resolve_field(ref: str, namespace: str = "global") -> dict`
- Produces: `FieldGovernanceService.add_alias(field_ref: str, alias: str, namespace: str = "global", reason: str = "") -> dict`
- Produces: `FieldGovernanceService.list_aliases(field_ref: str) -> list[dict]`

- [x] **Step 1:** Write failing tests proving `Author-Country` and `author country` normalize to one canonical identity and direct duplicate creation is rejected.
- [x] **Step 2:** Write failing tests proving an alias resolves to the same field ID and can be used by `EntityService.set_cell` and `ViewService.create_view` without creating a field.
- [x] **Step 3:** Run targeted tests and verify the missing behavior failures.
- [x] **Step 4:** Implement governance-aware resolution and alias collision rules; update field create/bulk create to store namespace/normalized key and reject new normalized duplicates.
- [x] **Step 5:** Route entity/view field lookup through governance-aware resolution.
- [x] **Step 6:** Run targeted tests and full suite.
- [x] **Step 7:** Commit canonical identity/alias behavior.

### Task 3: Proposal accept/reject kernel

**Files:**
- Modify: `src/sedb/governance.py`
- Modify: `src/sedb/fields.py`
- Modify: `tests/test_governance.py`

**Interfaces:**
- Produces: `create_proposal(...)` compatibility through `FieldService`
- Produces: `FieldGovernanceService.decide_proposal(proposal_id: str, decision: str, reason: str, evaluator: str = "", evidence: dict | None = None) -> dict`
- Produces: `FieldGovernanceService.get_proposal_decision(proposal_id: str) -> dict`

- [x] **Step 1:** Write failing test: accepting a unique pending proposal creates exactly one canonical field and records a decision target.
- [x] **Step 2:** Write failing test: accepting a normalized duplicate records/uses an alias and targets the existing field without increasing field count.
- [x] **Step 3:** Write failing test: reject requires reason, creates no field, and proposals cannot be decided twice.
- [x] **Step 4:** Run tests and verify expected failures.
- [x] **Step 5:** Implement transactional proposal decisions and compatibility wrappers.
- [x] **Step 6:** Run targeted tests and full suite.
- [x] **Step 7:** Commit proposal governance.

### Task 4: Immutable field definition versions

**Files:**
- Modify: `src/sedb/governance.py`
- Modify: `src/sedb/fields.py`
- Modify: `tests/test_governance.py`

**Interfaces:**
- Produces: `FieldGovernanceService.list_versions(field_ref: str) -> list[dict]`
- Produces: `FieldGovernanceService.update_definition(field_ref: str, *, label: str | None = None, value_type: str | None = None, description: str | None = None, reason: str, evaluator: str = "") -> dict`

- [x] **Step 1:** Write failing test that every new field starts with immutable version 1.
- [x] **Step 2:** Write failing test that updating label/description requires reason, appends version 2, and preserves version 1 unchanged.
- [x] **Step 3:** Run targeted tests and confirm failures.
- [x] **Step 4:** Implement version append logic and definition update transaction.
- [x] **Step 5:** Run targeted tests and full suite.
- [x] **Step 6:** Commit field versioning.

### Task 5: Merge/split lineage kernel

**Files:**
- Modify: `src/sedb/governance.py`
- Modify: `src/sedb/fields.py`
- Modify: `tests/test_governance.py`

**Interfaces:**
- Produces: `FieldGovernanceService.merge_fields(source_refs: list[str], target_ref: str, *, reason: str, evaluator: str = "", evidence: dict | None = None) -> list[dict]`
- Produces: `FieldGovernanceService.split_field(source_ref: str, child_refs: list[str], *, reason: str, evaluator: str = "", evidence: dict | None = None) -> list[dict]`
- Produces: `FieldGovernanceService.list_lineage(field_ref: str) -> list[dict]`

- [x] **Step 1:** Write failing merge test proving source status becomes `merged`, lineage points to target, and existing cells remain on the source field.
- [x] **Step 2:** Write failing split test proving source status becomes `split`, at least two child edges exist, and no cells are copied.
- [x] **Step 3:** Write failing test preventing direct `transition(..., "merged"/"split")` without governance lineage.
- [x] **Step 4:** Run targeted tests and confirm failures.
- [x] **Step 5:** Implement merge/split transactional lineage and guard direct transitions.
- [x] **Step 6:** Run targeted tests and full suite.
- [x] **Step 7:** Commit lineage kernel.

### Task 6: HTTP API and minimal governance UI

**Files:**
- Modify: `src/sedb/server.py`
- Modify: `src/sedb/web/index.html`
- Modify: `src/sedb/web/app.js`
- Modify: `src/sedb/web/style.css`
- Modify: `tests/test_server.py`

**Interfaces:**
- Produces the API routes listed in the approved design spec.

- [x] **Step 1:** Write failing HTTP tests for proposal accept/reject, alias create/list, version update/list, merge/split, and lineage read.
- [x] **Step 2:** Run server tests and confirm route failures.
- [x] **Step 3:** Implement API routing with existing 400/404 error conventions.
- [x] **Step 4:** Extend UI with namespace input and a pending-proposals governance panel with accept/reject actions.
- [x] **Step 5:** Run server tests, full tests, and JavaScript syntax validation.
- [x] **Step 6:** Commit API/UI changes.

### Task 7: v0.2A release checkpoint and artifact validation

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/sedb/__init__.py`
- Modify: `README.md`
- Create: `docs/RELEASE_NOTES_v0.2A.md`
- Create/refresh: `demo/sedb-demo-10k-v0.2a.sqlite`
- Create/refresh: `demo/stats-v0.2a.json`
- Create/refresh: `MANIFEST.sha256`

**Interfaces:**
- Produces: installable local SEDB `0.2.0a1` checkpoint and distributable ZIP.

- [x] **Step 1:** Add release documentation that separates implemented behavior from deferred semantic-AI dedup and scale experiments.
- [x] **Step 2:** Bump package/runtime version to `0.2.0a1` and server banner to v0.2A.
- [x] **Step 3:** Build a fresh 10,000-field demo and exercise governance by creating one accepted proposal alias, one definition version update, and lineage records in a separate governance demo fixture if needed.
- [x] **Step 4:** Run `pytest -q`, `python -m compileall -q src examples`, and JS syntax validation.
- [x] **Step 5:** Generate source SHA-256 manifest, ensure UTF-8 source round-trip, remove caches, and create ZIP.
- [x] **Step 6:** Extract the final ZIP into a clean directory and rerun the complete test/compile/integrity checks against the extracted artifact.
- [x] **Step 7:** Commit release checkpoint locally and preserve branch `local-v0.2a` without push/merge.
