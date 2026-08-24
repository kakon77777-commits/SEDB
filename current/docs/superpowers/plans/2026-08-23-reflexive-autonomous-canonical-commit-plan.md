# SEDB v0.4B Reflexive Autonomous Canonical Commit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral autonomous canonical commit kernel that can execute bounded, authority-valid canonical mutations while preserving open-world classification, Decision/Commit separation, stale-state safety, and append-only receipts.

**Architecture:** Add an immutable autonomy persistence layer in `db.py` and a focused `AutonomyService` in `autonomy.py`. The service classifies action effects, evaluates immutable authority envelopes and public-state constraints, persists Decision Receipts, then separately executes known adapters inside one SQLite transaction that also persists the Commit Receipt. Unknown actions remain open-world: authority can be granted even when commit capability is absent.

**Tech Stack:** Python 3.11+, SQLite, standard library only, pytest, vanilla browser UI.

**Spec:** `docs/superpowers/specs/2026-08-23-reflexive-autonomous-canonical-commit-design.md`

## Global Constraints

- Preserve all 160 v0.4A tests.
- No external model/API dependency.
- No autonomous envelope installation or authority self-grant.
- Consensus is evidence, never authority.
- Decision Receipt must exist before canonical mutation.
- Commit Receipt must be inserted in the same transaction as the canonical mutation.
- Rollback is compensating and append-only with respect to history.
- Unknown action name must never map directly to `UNAUTHORIZED`.
- Canonical Markdown/UTF-8 source uses `$...$` and `$$...$$` only.

---

### Task 1: Autonomy schema migration and immutable ledgers

**Files:**
- Modify: `src/sedb/db.py`
- Create: `tests/test_autonomy_migration.py`

**Interfaces:**
- Produces tables: `autonomy_envelopes`, `autonomy_constraint_snapshots`, `autonomy_decisions`, `autonomy_commit_receipts`, `autonomy_commit_events`, `autonomy_rollback_receipts`.

- [ ] Write a migration test that opens a v0.4A-shaped DB, preserves an existing cell, and asserts all six autonomy tables exist.
- [ ] Run `pytest tests/test_autonomy_migration.py -q` and verify RED because tables are absent.
- [ ] Add `AUTONOMY_SCHEMA` and execute it after `CAMPAIGN_SCHEMA` in `Database.__init__`.
- [ ] Add SQLite `BEFORE UPDATE/DELETE` triggers for envelopes, snapshots, decisions, commit receipts, commit events, and rollback receipts.
- [ ] Verify direct update/delete of Decision and Commit receipts raises `sqlite3.IntegrityError`.
- [ ] Run full suite and commit `feat: add autonomy commit ledgers`.

### Task 2: Open-world effect classifier and immutable authority envelopes

**Files:**
- Create: `src/sedb/autonomy.py`
- Create: `tests/test_autonomy_authority.py`

**Interfaces:**
- `AutonomyService.install_envelope(...) -> dict`
- `AutonomyService.ensure_default_envelope() -> dict`
- `AutonomyService.classify_action(action: dict) -> dict`
- `AutonomyService.decide(action, envelope_id, *, evidence=None, evaluator='') -> dict`

- [ ] Test default envelope grants local `sedb.canonical`, shared-world, reversible, bounded-cost actions but not external or irreversible authority.
- [ ] Test known `accept_proposal` properties are inferred.
- [ ] Test novel action with explicit legal properties receives `EXECUTE`, proving action-name absence is not denial.
- [ ] Test novel action without enough effect properties receives `DEFER`, not `REFUSE`.
- [ ] Test external/resource-owner/authority-domain boundary produces `ESCALATE`.
- [ ] Test no autonomous action adapter exists for envelope installation.
- [ ] Implement immutable envelope install/lookup, property classifier, evidence-aware authority decision, and Decision Receipt persistence.
- [ ] Run full suite and commit `feat: add open world authority decisions`.

### Task 3: Public-state self-constraint snapshots and evidence conflict handling

**Files:**
- Modify: `src/sedb/autonomy.py`
- Create: `tests/test_autonomy_constraints.py`

**Interfaces:**
- `AutonomyService.build_constraint_snapshot(action, properties, *, evidence=None) -> dict`
- Decision Receipt stores `constraint_snapshot_id` and hash.

- [ ] Test reversible inside-envelope action selects only minimal public `VERIFY` constraint.
- [ ] Test `disputed` or `incompatible` consensus selects `COMPARE` + `STOP` and forces `ESCALATE`.
- [ ] Test irreversible shared-world action adds `VERIFY` + `COUNTEREXAMPLE` and cannot execute under default envelope.
- [ ] Test snapshots contain public signal codes and no hidden reasoning field.
- [ ] Implement deterministic snapshot construction and persist immutable snapshots before decisions.
- [ ] Run full suite and commit `feat: add minimum necessary commit constraints`.

### Task 4: Atomic Decision-to-Commit kernel and bounded adapters

**Files:**
- Modify: `src/sedb/autonomy.py`
- Create: `tests/test_autonomy_commit.py`

**Interfaces:**
- `AutonomyService.commit_decision(decision_id: str) -> dict`
- `AutonomyService.execute_autonomously(action, envelope_id, *, evidence=None, evaluator='') -> dict`

- [ ] Test `accept_proposal` persists Decision first, then atomically changes proposal/canonical field state and inserts Commit Receipt.
- [ ] Test incompatible consensus returns `ESCALATE` and field count remains unchanged.
- [ ] Test novel legal action receives `EXECUTE` Decision but `commit_decision` records `CAPABILITY_MISSING` with no canonical mutation.
- [ ] Test stale proposal/field basis rejects commit and records failed event.
- [ ] Test `transition_field`, `update_definition`, and `set_guardrail` adapters preserve existing event/version semantics.
- [ ] Implement action-specific basis snapshots and direct-SQL transaction adapters so mutation and Commit Receipt share one transaction.
- [ ] Implement failed commit event persistence outside rolled-back mutation transaction.
- [ ] Run full suite and commit `feat: add atomic autonomous canonical commits`.

### Task 5: Compensating rollback and autonomy metrics

**Files:**
- Modify: `src/sedb/autonomy.py`
- Create: `tests/test_autonomy_rollback.py`

**Interfaces:**
- `AutonomyService.rollback_commit(commit_id: str, *, evaluator='') -> dict`
- `AutonomyService.stats() -> dict`

- [ ] Test field lifecycle commit can be rolled back by an inverse transition and both histories remain.
- [ ] Test definition rollback appends a new restoring version instead of deleting versions.
- [ ] Test guardrail rollback appends opposite state.
- [ ] Test accept-proposal rollback uses compensation and never deletes Decision/Commit receipts.
- [ ] Test second rollback of same commit is rejected.
- [ ] Test stats report execute/escalate/defer/commit/failure/rollback counts and rates.
- [ ] Implement rollback adapters, immutable Rollback Receipt, rollback events, and derived metrics.
- [ ] Run full suite and commit `feat: add compensating rollback receipts`.

### Task 6: HTTP API, browser panel, release demo, and v0.4B validation

**Files:**
- Modify: `src/sedb/server.py`
- Modify: `src/sedb/web/index.html`
- Modify: `src/sedb/web/app.js`
- Modify: `src/sedb/__init__.py`
- Modify: `pyproject.toml`
- Create: `examples/autonomy_demo.py`
- Create: `tests/test_autonomy_server.py`
- Create: `tests/test_autonomy_demo.py`
- Create: `docs/RELEASE_NOTES_v0.4B.md`
- Modify: `README.md`
- Modify: `demo/README.md`

**Interfaces:**
- `GET/POST /api/autonomy/envelopes`
- `POST /api/autonomy/decide`
- `POST /api/autonomy/execute`
- `GET /api/autonomy/decisions`
- `POST /api/autonomy/decisions/{id}/commit`
- `POST /api/autonomy/commits/{id}/rollback`
- `GET /api/autonomy/stats`

- [ ] Add API/UI tests proving autonomous execute can create a field from a proposal and incompatible evidence cannot commit.
- [ ] Expose no autonomous endpoint that modifies authority envelopes through an Agent action.
- [ ] Update version to `0.4.0b1` / `v0.4B`.
- [ ] Build a reproducible governance demo containing: autonomous proposal commit, escalated conflict, novel authority-valid/capability-missing action, rollback, and unchanged external-resource state.
- [ ] Record exact release fixture statistics with an environment-specific timing disclaimer.
- [ ] Run full tests, Python compile/AST, JS syntax, UTF-8 source validation, Markdown delimiter validation, SQLite `integrity_check`, manifest verification, and ZIP CRC.
- [ ] Build clean ZIP from final Git HEAD plus explicitly listed SQLite demos; re-extract and repeat verification.
