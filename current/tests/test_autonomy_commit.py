from uuid import uuid4

import pytest

from sedb.autonomy import AutonomyService
from sedb.campaign import CampaignService
from sedb.db import Database
from sedb.fields import FieldService
from sedb.governance import FieldGovernanceService
from sedb.utility import UtilityService


def make_packet(db, status: str) -> str:
    campaign = CampaignService(db).create_campaign(name=f"C-{status}")
    group_id = uuid4().hex
    packet_id = uuid4().hex
    now = "2026-08-23T00:00:00Z"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO field_agent_advisory_groups(
                id,campaign_id,namespace,normalized_key,raw_support,independent_support,
                backend_count,evidence_root_count,conflict_count,basis_count,min_pair_score,
                avg_pair_score,metrics_json,evidence_json,created_at
            ) VALUES(?,?, 'global','candidate',3,2,2,2,0,1,1.0,1.0,'{}','{}',?)
            """,
            (group_id, campaign["id"], now),
        )
        conn.execute(
            """
            INSERT INTO field_agent_consensus_packets(
                id,campaign_id,group_id,policy_version,status,summary,metrics_json,
                evidence_json,basis_sha256,created_at
            ) VALUES(?,?,?,'consensus-v1',?,'fixture','{}','{}','basis',?)
            """,
            (packet_id, campaign["id"], group_id, status, now),
        )
    return packet_id


def test_autonomous_accept_proposal_persists_decision_then_atomic_commit(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    fields = FieldService(db)
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    proposal = fields.create_proposal(
        key="ai_assistance_disclosed",
        label="AI assistance disclosed",
        value_type="boolean",
        reason="Observed repeatedly",
        proposed_by="agent:test",
    )

    result = svc.execute_autonomously(
        {
            "type": "accept_proposal",
            "proposal_id": proposal["id"],
            "reason": "Independent evidence supports canonicalization",
        },
        env["id"],
        evaluator="agent:governed",
    )

    assert result["decision"]["decision"] == "EXECUTE"
    assert result["commit"]["action_type"] == "accept_proposal"
    assert result["commit"]["mutation"]["outcome"] == "created"
    assert fields.get_proposal(proposal["id"])["status"] == "accepted"
    assert db.scalar("SELECT COUNT(*) FROM fields") == 1
    assert db.scalar("SELECT COUNT(*) FROM autonomy_decisions") == 1
    assert db.scalar("SELECT COUNT(*) FROM autonomy_commit_receipts") == 1
    events = svc.list_commit_events(result["decision"]["id"])
    assert [event["event_type"] for event in events] == ["preflight", "committed"]


def test_incompatible_consensus_escalates_without_commit(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    fields = FieldService(db)
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    proposal = fields.create_proposal(
        key="review_status",
        label="Review status",
        reason="Candidate",
        proposed_by="agent:test",
    )
    packet = make_packet(db, "incompatible")

    result = svc.execute_autonomously(
        {"type": "accept_proposal", "proposal_id": proposal["id"], "reason": "test"},
        env["id"],
        evidence={"consensus_packet_id": packet},
    )

    assert result["decision"]["decision"] == "ESCALATE"
    assert result["commit"] is None
    assert fields.get_proposal(proposal["id"])["status"] == "pending"
    assert db.scalar("SELECT COUNT(*) FROM fields") == 0


def test_novel_authorized_action_can_fail_commit_for_capability_not_authority(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    action = {
        "type": "novel_index_rebalance",
        "properties": {
            "external": False,
            "shared_world": True,
            "reversible": True,
            "cost_units": 1,
            "resource_owner": "local_database",
            "authority_domain": "sedb.canonical",
            "public_commitment": False,
            "irreversible": False,
        },
    }
    decision = svc.decide(action, env["id"])
    assert decision["decision"] == "EXECUTE"

    with pytest.raises(RuntimeError, match="CAPABILITY_MISSING"):
        svc.commit_decision(decision["id"])

    events = svc.list_commit_events(decision["id"])
    assert events[-1]["event_type"] == "failed"
    assert events[-1]["detail"]["code"] == "CAPABILITY_MISSING"
    assert db.scalar("SELECT COUNT(*) FROM autonomy_commit_receipts") == 0


def test_stale_decision_cannot_commit_after_proposal_changes(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    fields = FieldService(db)
    governance = FieldGovernanceService(db)
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    proposal = fields.create_proposal(
        key="stale_signal", label="Stale signal", reason="test", proposed_by="agent:test"
    )
    decision = svc.decide(
        {"type": "accept_proposal", "proposal_id": proposal["id"], "reason": "auto"},
        env["id"],
    )
    governance.decide_proposal(proposal["id"], "reject", reason="changed elsewhere")

    with pytest.raises(ValueError, match="STALE_BASIS"):
        svc.commit_decision(decision["id"])

    assert svc.list_commit_events(decision["id"])[-1]["detail"]["code"] == "STALE_BASIS"
    assert db.scalar("SELECT COUNT(*) FROM autonomy_commit_receipts") == 0


def test_transition_definition_and_guardrail_adapters_use_existing_semantics(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    fields = FieldService(db)
    governance = FieldGovernanceService(db)
    utility = UtilityService(db)
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    field = fields.create_field(key="quality", label="Quality")

    transition = svc.execute_autonomously(
        {
            "type": "transition_field",
            "field_id": field["id"],
            "to_status": "converged",
            "reason": "No current operational support",
        },
        env["id"],
    )
    assert transition["commit"] is not None
    assert fields.get_field(field["id"])["status"] == "converged"
    assert fields.list_evaluations(field["id"])[-1]["decision"] == "converge"

    definition = svc.execute_autonomously(
        {
            "type": "update_definition",
            "field_id": field["id"],
            "label": "Quality signal",
            "reason": "Clarify semantics",
        },
        env["id"],
    )
    assert definition["commit"] is not None
    assert governance.list_versions(field["id"])[-1]["label"] == "Quality signal"

    guard = svc.execute_autonomously(
        {
            "type": "set_guardrail",
            "field_id": field["id"],
            "protected": True,
            "reason": "Rare but important",
        },
        env["id"],
    )
    assert guard["commit"] is not None
    assert utility.get_guardrail(field["id"])["protected"] is True
