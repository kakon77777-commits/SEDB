# SEDB v0.4A Multi-Agent Coordination & Advisory Consensus Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build bounded, evidence-aware multi-Agent campaign coordination and immutable advisory consensus/conflict packets without canonical mutation authority.

**Architecture:** Add a migration-safe campaign schema and a new `CampaignService` that coordinates existing `AgentService` runs. Work claims use leases; aggregation consumes immutable Agent action/observation receipts and emits immutable advisory groups and packets.

**Tech Stack:** Python 3.11+, SQLite, stdlib HTTP server, vanilla browser JS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-multi-agent-coordination-consensus-design.md`

## Global Constraints

- Keep local-first operation and zero network/LLM dependency.
- Preserve every v0.3C test.
- Campaign/consensus code must not call canonical mutation services.
- Consensus packets and aggregation group snapshots are immutable.
- All new Markdown/source artifacts remain UTF-8.

---

### Task 1: Campaign schema migration and immutability

**Files:** `src/sedb/db.py`, `tests/test_campaign_migration.py`

**Interfaces:** Database initialization creates eight campaign tables and immutable triggers for campaign-run links, advisory groups/members, consensus packets/events.

- [ ] Write a failing migration test opening a v0.3C-style DB and asserting new tables exist while old cell data remains.
- [ ] Write a failing test proving consensus packet/group rows reject UPDATE/DELETE.
- [ ] Run the targeted tests and confirm RED.
- [ ] Add `CAMPAIGN_SCHEMA` and execute it from `Database.__init__`.
- [ ] Re-run targeted and full tests; commit.

### Task 2: Campaign lifecycle, budget, work queue, and leases

**Files:** `src/sedb/campaign.py`, `tests/test_campaign_runtime.py`

**Interfaces:** `CampaignService.create_campaign`, `add_work_item`, `claim_work_item`, `release_claim`, `get_campaign`, `list_campaigns`, `complete_campaign`.

- [ ] Test created campaign policy/budget/counters.
- [ ] Test one active claim per work item.
- [ ] Test expired claim can be reclaimed with deterministic `now`.
- [ ] Test terminal campaign rejects new work/claims.
- [ ] Test max_work_items budget produces `budget_exhausted`.
- [ ] Implement minimal runtime and pass full suite; commit.

### Task 3: Link existing Agent runs and aggregate campaign budget

**Files:** `src/sedb/campaign.py`, `tests/test_campaign_runs.py`

**Interfaces:** `link_run(campaign_id, work_item_id, run_id, agent_label, claim_token=None, cost_units=1)`.

- [ ] Test only terminal Agent runs can be linked.
- [ ] Test one run cannot be linked twice.
- [ ] Test linking completes the work item/claim and aggregates run/step/proposal/cost counters.
- [ ] Test campaign-level run/step/proposal/cost budget exhaustion blocks additional links.
- [ ] Implement minimal linking path; full regression; commit.

### Task 4: Evidence-aware advisory grouping and consensus packets

**Files:** `src/sedb/campaign.py`, `tests/test_campaign_consensus.py`

**Interfaces:** `aggregate_campaign(campaign_id, semantic_floor=0.72)` returns immutable packet snapshots.

- [ ] Test two same-backend/same-observation runs yield raw support 2 but independent support 1 and `insufficient_independence`.
- [ ] Test independent evidence/backend diversity yields `strong_agreement`.
- [ ] Test same normalized key with incompatible value types yields `incompatible`.
- [ ] Test low pairwise semantic compatibility yields `disputed`.
- [ ] Test divergent run basis hashes yields `basis_incompatible`.
- [ ] Test packets are immutable and campaign aggregation does not alter canonical field/cell counts.
- [ ] Implement grouping from Agent action receipts + observation hashes; pass full suite; commit.

### Task 5: Local API and browser campaign panel

**Files:** `src/sedb/server.py`, `src/sedb/web/index.html`, `src/sedb/web/app.js`, `tests/test_campaign_server.py`

**Interfaces:** campaign list/create/detail/work/claim/link-run/aggregate/complete routes.

- [ ] Write failing API tests and a browser marker test.
- [ ] Add routes that expose only coordination/advisory operations.
- [ ] Add minimal Campaign panel for creating/listing campaigns and viewing consensus packets.
- [ ] Run API/UI/full suite and JS syntax; commit.

### Task 6: Release v0.4A, demos, validation, ZIP

**Files:** version metadata, README, release notes, demo scripts/stats, provenance/manifest.

- [ ] RED-test version `0.4.0a1` and executable campaign demo.
- [ ] Add a governance demo proving a multi-Agent campaign changes advisory artifacts but not canonical fields/cells.
- [ ] Add a bounded campaign benchmark fixture and record environment-specific timings without extrapolation.
- [ ] Run full tests, compile, JS syntax, UTF-8/math checks, SQLite integrity, manifest, demo hashes.
- [ ] Build a clean ZIP from Git HEAD plus explicitly listed SQLite demos and re-run validation after extraction.
