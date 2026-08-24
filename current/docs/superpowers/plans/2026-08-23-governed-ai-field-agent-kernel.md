# Governed AI Field Agent Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement SEDB v0.3C as a provider-neutral, budgeted, auditable advisory Agent runtime that cannot mutate canonical field or cell state.

**Architecture:** Add append/audit-oriented agent tables and a new `sedb.agent` orchestration module. Existing proposal, semantic, utility, and family services remain authoritative for their own advisory artifacts; the Agent runtime exposes only their non-canonical operations through a capability and budget gate.

**Tech Stack:** Python standard library, SQLite, existing SEDB services, vanilla browser JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-23-governed-ai-field-agent-kernel-design.md`

## Global Constraints

- Local-first; no GitHub mutation.
- No external network or model dependency in the core runtime.
- Deterministic backend is a reference harness, not an LLM claim.
- Agent runs cannot change canonical field count or cell count.
- Denied mutation intents must be persisted as receipts.
- UTF-8 is canonical source encoding.

---

### Task 1: Agent schema and immutable receipts

**Files:**
- Modify: `src/sedb/db.py`
- Create: `tests/test_agent_migration.py`

**Interfaces:**
- Produces tables `field_agent_runs`, `field_agent_observations`, `field_agent_actions`, `field_agent_run_events`.

- [ ] Write a migration test from a v0.3B-style DB and immutable receipt tests.
- [ ] Run targeted test and verify RED because agent tables do not exist.
- [ ] Add idempotent `AGENT_SCHEMA`, indexes, and immutability triggers for observations/actions/events.
- [ ] Run targeted test and full regression.
- [ ] Commit `feat: add governed agent persistence schema`.

### Task 2: Backends and observation normalization

**Files:**
- Create: `src/sedb/agent.py`
- Create: `tests/test_agent_backends.py`

**Interfaces:**
- Produces `DeterministicDiscoveryBackend.suggest(observation)` and `ExternalSuggestionBackend.validate(packet)`.

- [ ] Write RED tests for nested-key discovery, array handling, primitive type inference, deterministic output, and malformed external suggestions.
- [ ] Implement minimal backend classes and canonical JSON hashing helpers.
- [ ] Verify targeted tests and full regression.
- [ ] Commit `feat: add provider neutral field agent backends`.

### Task 3: Run lifecycle, capability gate, and budgets

**Files:**
- Modify: `src/sedb/agent.py`
- Create: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces `AgentService.create_run`, `record_observation`, `execute_intent`, `get_run`, `list_runs`.

- [ ] Write RED tests for run creation/events, allowed capabilities, explicit denied receipts, and budget exhaustion.
- [ ] Implement run state, counters, capability allow/deny sets, append-only receipts, and atomic budget checks.
- [ ] Verify targeted tests and full regression.
- [ ] Commit `feat: add budgeted agent runtime and capability gate`.

### Task 4: Advisory workflow, idempotence, and staleness

**Files:**
- Modify: `src/sedb/agent.py`
- Create: `tests/test_agent_workflow.py`

**Interfaces:**
- Produces `AgentService.run_deterministic` and `AgentService.run_external`.

- [ ] Write RED tests that raw observations create proposals but preserve field/cell counts.
- [ ] Write RED tests for canonical/alias skip, same-run duplicate skip, and stale re-resolution.
- [ ] Implement proposal creation through `FieldService`, optional semantic scoring through `SemanticDedupService`, utility assessment through `UtilityService`, and bounded family proposal through `FieldFamilyService`.
- [ ] Verify receipts reference created advisory artifacts and no canonical mutation occurs.
- [ ] Verify targeted tests and full regression.
- [ ] Commit `feat: orchestrate governed advisory agent workflows`.

### Task 5: HTTP API and Browser UI

**Files:**
- Modify: `src/sedb/server.py`
- Modify: `src/sedb/web/index.html`
- Modify: `src/sedb/web/app.js`
- Create: `tests/test_agent_server.py`

**Interfaces:**
- Adds `/api/agent/runs`, `/api/agent/run/deterministic`, `/api/agent/run/external`, `/api/agent/runs/{id}`.

- [ ] Write RED integration tests for run APIs and absence of mutation endpoints in Agent panel.
- [ ] Add minimal routes and Browser panel for deterministic observation JSON and external suggestion JSON.
- [ ] Show receipts/events/counters only; no canonical mutation buttons.
- [ ] Verify HTTP tests, JavaScript syntax, and full regression.
- [ ] Commit `feat: expose governed agent runtime locally`.

### Task 6: Release v0.3C, demos, and artifact validation

**Files:**
- Modify: `src/sedb/__init__.py`
- Modify: `README.md`
- Create: `docs/RELEASE_NOTES_v0.3C.md`
- Create: `examples/agent_demo.py`
- Create: `tests/test_agent_demo.py`

**Interfaces:**
- Release identity `0.3.0c1`, local checkpoint `v0.3C`.

- [ ] Write RED release identity and demo tests.
- [ ] Build a governance demo proving proposal growth with unchanged field/cell counts, denied mutation receipt, external adapter, and budget exhaustion.
- [ ] Build a bounded larger observation demo without external model calls.
- [ ] Run full tests, compileall, JS syntax, UTF-8/math validation, SQLite integrity, manifest verification.
- [ ] Build ZIP from clean Git HEAD plus explicit demo DBs.
- [ ] Extract ZIP and repeat artifact verification.
- [ ] Keep `local-v0.3c` local; do not push GitHub.
