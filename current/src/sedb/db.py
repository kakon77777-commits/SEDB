from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .naming import normalize_field_key


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'record',
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fields (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'text',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('proposed','active','converged','merged','split','deprecated')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'global',
    normalized_key TEXT
);

CREATE TABLE IF NOT EXISTS cells (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    confidence REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(entity_id, field_id)
);

CREATE INDEX IF NOT EXISTS idx_cells_field_id ON cells(field_id);

CREATE TABLE IF NOT EXISTS field_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    reason TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    reversible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_proposals (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'text',
    description TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    proposed_by TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','accepted','rejected')),
    created_at TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'global'
);

CREATE TABLE IF NOT EXISTS task_views (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    query_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_view_fields (
    view_id TEXT NOT NULL REFERENCES task_views(id) ON DELETE CASCADE,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY(view_id, field_id),
    UNIQUE(view_id, ordinal)
);
"""


GOVERNANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS field_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT 'global',
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(namespace, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_field_aliases_field_id ON field_aliases(field_id);
CREATE INDEX IF NOT EXISTS idx_fields_namespace_normalized ON fields(namespace, normalized_key);

CREATE TABLE IF NOT EXISTS field_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    label TEXT NOT NULL,
    value_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(field_id, version)
);

CREATE TABLE IF NOT EXISTS field_lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    child_field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK(relation IN ('merged_into','split_into')),
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(parent_field_id, child_field_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_field_lineage_parent ON field_lineage(parent_field_id);
CREATE INDEX IF NOT EXISTS idx_field_lineage_child ON field_lineage(child_field_id);

CREATE TABLE IF NOT EXISTS proposal_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES field_proposals(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected')),
    outcome TEXT NOT NULL,
    target_field_id TEXT REFERENCES fields(id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


SEMANTIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT 'global',
    source_kind TEXT NOT NULL CHECK(source_kind IN ('proposal','field')),
    source_ref TEXT NOT NULL,
    candidate_field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    signals_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','reviewed')),
    created_at TEXT NOT NULL,
    UNIQUE(source_kind, source_ref, candidate_field_id)
);

CREATE INDEX IF NOT EXISTS idx_semantic_candidates_source
ON semantic_candidates(source_kind, source_ref);
CREATE INDEX IF NOT EXISTS idx_semantic_candidates_status
ON semantic_candidates(status, score DESC);

CREATE TABLE IF NOT EXISTS semantic_candidate_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL UNIQUE REFERENCES semantic_candidates(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK(decision IN ('alias','related','distinct','ignore')),
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT 'global',
    left_field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    right_field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK(relation IN ('related_to')),
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(left_field_id, right_field_id, relation),
    CHECK(left_field_id <> right_field_id)
);

CREATE INDEX IF NOT EXISTS idx_field_relations_left ON field_relations(left_field_id);
CREATE INDEX IF NOT EXISTS idx_field_relations_right ON field_relations(right_field_id);
"""


UTILITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS field_utility_assessments (
    id TEXT PRIMARY KEY,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    policy_version TEXT NOT NULL,
    field_status TEXT NOT NULL,
    score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
    recommendation TEXT NOT NULL CHECK(recommendation IN (
        'keep','review','converge_candidate','reactivate_candidate','insufficient_evidence'
    )),
    reason TEXT NOT NULL,
    evaluator TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    policy_json TEXT NOT NULL DEFAULT '{}',
    basis_sha256 TEXT NOT NULL,
    as_of TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_utility_assessments_field
ON field_utility_assessments(field_id, created_at DESC);

CREATE TABLE IF NOT EXISTS field_guardrails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    protected INTEGER NOT NULL CHECK(protected IN (0,1)),
    reason TEXT NOT NULL,
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_guardrails_field
ON field_guardrails(field_id, id DESC);

CREATE TRIGGER IF NOT EXISTS field_utility_assessments_no_update
BEFORE UPDATE ON field_utility_assessments
BEGIN
    SELECT RAISE(ABORT, 'field utility assessments are immutable');
END;

CREATE TRIGGER IF NOT EXISTS field_utility_assessments_no_delete
BEFORE DELETE ON field_utility_assessments
BEGIN
    SELECT RAISE(ABORT, 'field utility assessments are immutable');
END;
"""


FAMILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS field_family_proposals (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL DEFAULT 'global',
    policy_version TEXT NOT NULL,
    seed_field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    member_count INTEGER NOT NULL CHECK(member_count >= 1),
    min_pair_score REAL NOT NULL CHECK(min_pair_score >= 0.0 AND min_pair_score <= 1.0),
    avg_pair_score REAL NOT NULL CHECK(avg_pair_score >= 0.0 AND avg_pair_score <= 1.0),
    basis_sha256 TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_family_proposals_namespace
ON field_family_proposals(namespace, created_at DESC);

CREATE TABLE IF NOT EXISTS field_family_proposal_members (
    proposal_id TEXT NOT NULL REFERENCES field_family_proposals(id) ON DELETE CASCADE,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    seed_score REAL NOT NULL CHECK(seed_score >= 0.0 AND seed_score <= 1.0),
    min_peer_score REAL NOT NULL CHECK(min_peer_score >= 0.0 AND min_peer_score <= 1.0),
    avg_peer_score REAL NOT NULL CHECK(avg_peer_score >= 0.0 AND avg_peer_score <= 1.0),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(proposal_id, field_id),
    UNIQUE(proposal_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_field_family_proposal_members_field
ON field_family_proposal_members(field_id, proposal_id);

CREATE TABLE IF NOT EXISTS field_family_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES field_family_proposals(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK(decision IN ('duplicate_family','related_family','split','reject')),
    reason TEXT NOT NULL,
    decision_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_families (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL DEFAULT 'global',
    family_type TEXT NOT NULL CHECK(family_type IN ('duplicate','related')),
    label TEXT NOT NULL,
    source_proposal_id TEXT NOT NULL UNIQUE REFERENCES field_family_proposals(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','retired')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_family_members (
    family_id TEXT NOT NULL REFERENCES field_families(id) ON DELETE CASCADE,
    field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(family_id, field_id),
    UNIQUE(family_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_field_family_members_field
ON field_family_members(field_id, family_id);

CREATE TABLE IF NOT EXISTS field_family_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id TEXT NOT NULL REFERENCES field_families(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK(event_type IN ('created','retired')),
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS field_family_proposals_no_update
BEFORE UPDATE ON field_family_proposals
BEGIN
    SELECT RAISE(ABORT, 'field family proposals are immutable');
END;

CREATE TRIGGER IF NOT EXISTS field_family_proposals_no_delete
BEFORE DELETE ON field_family_proposals
BEGIN
    SELECT RAISE(ABORT, 'field family proposals are immutable');
END;

CREATE TRIGGER IF NOT EXISTS field_family_proposal_members_no_update
BEFORE UPDATE ON field_family_proposal_members
BEGIN
    SELECT RAISE(ABORT, 'field family proposal members are immutable');
END;

CREATE TRIGGER IF NOT EXISTS field_family_proposal_members_no_delete
BEFORE DELETE ON field_family_proposal_members
BEGIN
    SELECT RAISE(ABORT, 'field family proposal members are immutable');
END;
"""


AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS field_agent_runs (
    id TEXT PRIMARY KEY,
    backend TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'global',
    policy_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('created','running','completed','budget_exhausted','failed')),
    budget_json TEXT NOT NULL DEFAULT '{}',
    counters_json TEXT NOT NULL DEFAULT '{}',
    input_sha256 TEXT NOT NULL,
    basis_sha256 TEXT NOT NULL,
    evaluator TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_field_agent_runs_status
ON field_agent_runs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS field_agent_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES field_agent_runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_field_agent_observations_run
ON field_agent_observations(run_id, ordinal);

CREATE TABLE IF NOT EXISTS field_agent_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES field_agent_runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    intent TEXT NOT NULL,
    capability_decision TEXT NOT NULL CHECK(capability_decision IN ('ALLOWED','DENIED')),
    outcome TEXT NOT NULL,
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_field_agent_actions_run
ON field_agent_actions(run_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_field_agent_actions_intent
ON field_agent_actions(intent, outcome);

CREATE TABLE IF NOT EXISTS field_agent_run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES field_agent_runs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK(event_type IN ('created','started','completed','budget_exhausted','failed')),
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_agent_run_events_run
ON field_agent_run_events(run_id, id);

CREATE TRIGGER IF NOT EXISTS field_agent_observations_no_update
BEFORE UPDATE ON field_agent_observations
BEGIN
    SELECT RAISE(ABORT, 'field agent observations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_observations_no_delete
BEFORE DELETE ON field_agent_observations
BEGIN
    SELECT RAISE(ABORT, 'field agent observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS field_agent_actions_no_update
BEFORE UPDATE ON field_agent_actions
BEGIN
    SELECT RAISE(ABORT, 'field agent actions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_actions_no_delete
BEFORE DELETE ON field_agent_actions
BEGIN
    SELECT RAISE(ABORT, 'field agent actions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS field_agent_run_events_no_update
BEFORE UPDATE ON field_agent_run_events
BEGIN
    SELECT RAISE(ABORT, 'field agent run events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_run_events_no_delete
BEFORE DELETE ON field_agent_run_events
BEGIN
    SELECT RAISE(ABORT, 'field agent run events are immutable');
END;
"""


CAMPAIGN_SCHEMA = """
CREATE TABLE IF NOT EXISTS field_agent_campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    task_text TEXT NOT NULL DEFAULT '',
    namespace TEXT NOT NULL DEFAULT 'global',
    policy_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('created','running','completed','budget_exhausted','failed')),
    budget_json TEXT NOT NULL DEFAULT '{}',
    counters_json TEXT NOT NULL DEFAULT '{}',
    basis_sha256 TEXT NOT NULL,
    evaluator TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_field_agent_campaigns_status
ON field_agent_campaigns(status, created_at DESC);

CREATE TABLE IF NOT EXISTS field_agent_campaign_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL REFERENCES field_agent_campaigns(id) ON DELETE CASCADE,
    work_item_id TEXT REFERENCES field_agent_work_items(id) ON DELETE SET NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES field_agent_runs(id) ON DELETE CASCADE,
    agent_label TEXT NOT NULL DEFAULT '',
    backend TEXT NOT NULL,
    observation_root_sha256 TEXT NOT NULL DEFAULT '',
    basis_sha256 TEXT NOT NULL,
    cost_units INTEGER NOT NULL DEFAULT 1 CHECK(cost_units >= 0),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_agent_campaign_runs_campaign
ON field_agent_campaign_runs(campaign_id, id);

CREATE TABLE IF NOT EXISTS field_agent_work_items (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES field_agent_campaigns(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','completed','failed')),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(campaign_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_field_agent_work_items_campaign
ON field_agent_work_items(campaign_id, status, ordinal);

CREATE TABLE IF NOT EXISTS field_agent_work_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL REFERENCES field_agent_work_items(id) ON DELETE CASCADE,
    agent_label TEXT NOT NULL,
    lease_token TEXT NOT NULL UNIQUE,
    run_id TEXT REFERENCES field_agent_runs(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK(status IN ('active','released','expired','completed')),
    claimed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_field_agent_work_claims_active
ON field_agent_work_claims(work_item_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_field_agent_work_claims_item
ON field_agent_work_claims(work_item_id, id DESC);

CREATE TABLE IF NOT EXISTS field_agent_advisory_groups (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES field_agent_campaigns(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL DEFAULT 'global',
    normalized_key TEXT NOT NULL,
    raw_support INTEGER NOT NULL CHECK(raw_support >= 1),
    independent_support INTEGER NOT NULL CHECK(independent_support >= 1),
    backend_count INTEGER NOT NULL CHECK(backend_count >= 1),
    evidence_root_count INTEGER NOT NULL CHECK(evidence_root_count >= 1),
    conflict_count INTEGER NOT NULL DEFAULT 0 CHECK(conflict_count >= 0),
    basis_count INTEGER NOT NULL CHECK(basis_count >= 1),
    min_pair_score REAL NOT NULL CHECK(min_pair_score >= 0.0 AND min_pair_score <= 1.0),
    avg_pair_score REAL NOT NULL CHECK(avg_pair_score >= 0.0 AND avg_pair_score <= 1.0),
    metrics_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_agent_advisory_groups_campaign
ON field_agent_advisory_groups(campaign_id, normalized_key, created_at DESC);

CREATE TABLE IF NOT EXISTS field_agent_advisory_group_members (
    group_id TEXT NOT NULL REFERENCES field_agent_advisory_groups(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES field_agent_runs(id) ON DELETE CASCADE,
    action_id INTEGER NOT NULL REFERENCES field_agent_actions(id) ON DELETE CASCADE,
    backend TEXT NOT NULL,
    observation_root_sha256 TEXT NOT NULL,
    basis_sha256 TEXT NOT NULL,
    normalized_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    value_type TEXT NOT NULL DEFAULT 'text',
    reason TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY(group_id, action_id)
);

CREATE INDEX IF NOT EXISTS idx_field_agent_advisory_group_members_run
ON field_agent_advisory_group_members(run_id, group_id);

CREATE TABLE IF NOT EXISTS field_agent_consensus_packets (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES field_agent_campaigns(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL UNIQUE REFERENCES field_agent_advisory_groups(id) ON DELETE CASCADE,
    policy_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'strong_agreement','weak_agreement','disputed','incompatible',
        'insufficient_independence','basis_incompatible'
    )),
    summary TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    basis_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_agent_consensus_packets_campaign
ON field_agent_consensus_packets(campaign_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS field_agent_consensus_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL REFERENCES field_agent_campaigns(id) ON DELETE CASCADE,
    packet_id TEXT REFERENCES field_agent_consensus_packets(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK(event_type IN ('aggregation_started','packet_created','aggregation_completed')),
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_agent_consensus_events_campaign
ON field_agent_consensus_events(campaign_id, id);

CREATE TRIGGER IF NOT EXISTS field_agent_campaign_runs_no_update
BEFORE UPDATE ON field_agent_campaign_runs BEGIN
    SELECT RAISE(ABORT, 'field agent campaign run links are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_campaign_runs_no_delete
BEFORE DELETE ON field_agent_campaign_runs BEGIN
    SELECT RAISE(ABORT, 'field agent campaign run links are immutable');
END;

CREATE TRIGGER IF NOT EXISTS field_agent_advisory_groups_no_update
BEFORE UPDATE ON field_agent_advisory_groups BEGIN
    SELECT RAISE(ABORT, 'field agent advisory groups are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_advisory_groups_no_delete
BEFORE DELETE ON field_agent_advisory_groups BEGIN
    SELECT RAISE(ABORT, 'field agent advisory groups are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_advisory_group_members_no_update
BEFORE UPDATE ON field_agent_advisory_group_members BEGIN
    SELECT RAISE(ABORT, 'field agent advisory group members are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_advisory_group_members_no_delete
BEFORE DELETE ON field_agent_advisory_group_members BEGIN
    SELECT RAISE(ABORT, 'field agent advisory group members are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_consensus_packets_no_update
BEFORE UPDATE ON field_agent_consensus_packets BEGIN
    SELECT RAISE(ABORT, 'field agent consensus packets are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_consensus_packets_no_delete
BEFORE DELETE ON field_agent_consensus_packets BEGIN
    SELECT RAISE(ABORT, 'field agent consensus packets are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_consensus_events_no_update
BEFORE UPDATE ON field_agent_consensus_events BEGIN
    SELECT RAISE(ABORT, 'field agent consensus events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS field_agent_consensus_events_no_delete
BEFORE DELETE ON field_agent_consensus_events BEGIN
    SELECT RAISE(ABORT, 'field agent consensus events are immutable');
END;
"""


AUTONOMY_SCHEMA = """
CREATE TABLE IF NOT EXISTS autonomy_envelopes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    contract_ref TEXT NOT NULL DEFAULT '',
    authority_ref TEXT NOT NULL DEFAULT '',
    rules_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS autonomy_constraint_snapshots (
    id TEXT PRIMARY KEY,
    action_sha256 TEXT NOT NULL,
    basis_sha256 TEXT NOT NULL,
    constraints_json TEXT NOT NULL DEFAULT '{}',
    methods_json TEXT NOT NULL DEFAULT '[]',
    risk_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_decisions (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    action_json TEXT NOT NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    decision TEXT NOT NULL CHECK(decision IN ('EXECUTE','REFUSE','DEFER','IDLE','ESCALATE')),
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    envelope_id TEXT NOT NULL REFERENCES autonomy_envelopes(id),
    basis_sha256 TEXT NOT NULL,
    constraint_snapshot_id TEXT NOT NULL REFERENCES autonomy_constraint_snapshots(id),
    constraint_sha256 TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_autonomy_decisions_created
ON autonomy_decisions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_autonomy_decisions_outcome
ON autonomy_decisions(decision, created_at DESC);

CREATE TABLE IF NOT EXISTS autonomy_commit_receipts (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE REFERENCES autonomy_decisions(id),
    transaction_id TEXT NOT NULL UNIQUE,
    action_type TEXT NOT NULL,
    before_state_sha256 TEXT NOT NULL,
    after_state_sha256 TEXT NOT NULL,
    mutation_json TEXT NOT NULL DEFAULT '{}',
    rollback_action_json TEXT NOT NULL DEFAULT '{}',
    rollback_mode TEXT NOT NULL DEFAULT 'none',
    envelope_id TEXT NOT NULL REFERENCES autonomy_envelopes(id),
    constraint_snapshot_id TEXT NOT NULL REFERENCES autonomy_constraint_snapshots(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_commit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL REFERENCES autonomy_decisions(id),
    commit_id TEXT REFERENCES autonomy_commit_receipts(id),
    event_type TEXT NOT NULL CHECK(event_type IN ('preflight','committed','failed','rolled_back','rollback_failed')),
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_autonomy_commit_events_decision
ON autonomy_commit_events(decision_id, id);

CREATE TABLE IF NOT EXISTS autonomy_rollback_receipts (
    id TEXT PRIMARY KEY,
    commit_id TEXT NOT NULL UNIQUE REFERENCES autonomy_commit_receipts(id),
    before_state_sha256 TEXT NOT NULL,
    after_state_sha256 TEXT NOT NULL,
    mutation_json TEXT NOT NULL DEFAULT '{}',
    evaluator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS autonomy_envelopes_no_update
BEFORE UPDATE ON autonomy_envelopes BEGIN
    SELECT RAISE(ABORT, 'autonomy envelopes are immutable');
END;
CREATE TRIGGER IF NOT EXISTS autonomy_envelopes_no_delete
BEFORE DELETE ON autonomy_envelopes BEGIN
    SELECT RAISE(ABORT, 'autonomy envelopes are immutable');
END;

CREATE TRIGGER IF NOT EXISTS autonomy_constraint_snapshots_no_update
BEFORE UPDATE ON autonomy_constraint_snapshots BEGIN
    SELECT RAISE(ABORT, 'autonomy constraint snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS autonomy_constraint_snapshots_no_delete
BEFORE DELETE ON autonomy_constraint_snapshots BEGIN
    SELECT RAISE(ABORT, 'autonomy constraint snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS autonomy_decisions_no_update
BEFORE UPDATE ON autonomy_decisions BEGIN
    SELECT RAISE(ABORT, 'autonomy decisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS autonomy_decisions_no_delete
BEFORE DELETE ON autonomy_decisions BEGIN
    SELECT RAISE(ABORT, 'autonomy decisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS autonomy_commit_receipts_no_update
BEFORE UPDATE ON autonomy_commit_receipts BEGIN
    SELECT RAISE(ABORT, 'autonomy commit receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS autonomy_commit_receipts_no_delete
BEFORE DELETE ON autonomy_commit_receipts BEGIN
    SELECT RAISE(ABORT, 'autonomy commit receipts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS autonomy_commit_events_no_update
BEFORE UPDATE ON autonomy_commit_events BEGIN
    SELECT RAISE(ABORT, 'autonomy commit events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS autonomy_commit_events_no_delete
BEFORE DELETE ON autonomy_commit_events BEGIN
    SELECT RAISE(ABORT, 'autonomy commit events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS autonomy_rollback_receipts_no_update
BEFORE UPDATE ON autonomy_rollback_receipts BEGIN
    SELECT RAISE(ABORT, 'autonomy rollback receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS autonomy_rollback_receipts_no_delete
BEFORE DELETE ON autonomy_rollback_receipts BEGIN
    SELECT RAISE(ABORT, 'autonomy rollback receipts are immutable');
END;
"""


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _migrate_governance_schema(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "fields", "namespace", "namespace TEXT NOT NULL DEFAULT 'global'")
    _add_column_if_missing(conn, "fields", "normalized_key", "normalized_key TEXT")
    _add_column_if_missing(
        conn,
        "field_proposals",
        "namespace",
        "namespace TEXT NOT NULL DEFAULT 'global'",
    )

    rows = conn.execute("SELECT id,key FROM fields WHERE normalized_key IS NULL OR normalized_key='' ").fetchall()
    for row in rows:
        try:
            normalized = normalize_field_key(row["key"])
        except ValueError:
            normalized = f"legacy_{row['id'][:16]}"
        conn.execute(
            "UPDATE fields SET normalized_key=? WHERE id=?",
            (normalized, row["id"]),
        )

    conn.executescript(GOVERNANCE_SCHEMA)

    fields = conn.execute(
        """
        SELECT id,label,value_type,description,created_at
        FROM fields
        WHERE NOT EXISTS (
            SELECT 1 FROM field_versions fv WHERE fv.field_id=fields.id
        )
        """
    ).fetchall()
    for field in fields:
        conn.execute(
            """
            INSERT INTO field_versions(
                field_id,version,label,value_type,description,reason,evaluator,created_at
            ) VALUES(?,1,?,?,?,?,?,?)
            """,
            (
                field["id"],
                field["label"],
                field["value_type"],
                field["description"],
                "v0.2A migration snapshot",
                "system:migration",
                field["created_at"],
            ),
        )


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            _migrate_governance_schema(conn)
            conn.executescript(SEMANTIC_SCHEMA)
            conn.executescript(UTILITY_SCHEMA)
            conn.executescript(FAMILY_SCHEMA)
            conn.executescript(AGENT_SCHEMA)
            conn.executescript(CAMPAIGN_SCHEMA)
            conn.executescript(AUTONOMY_SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        with self.connect() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return None if row is None else row[0]
