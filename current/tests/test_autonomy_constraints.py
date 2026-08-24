from uuid import uuid4

from sedb.autonomy import AutonomyService
from sedb.campaign import CampaignService
from sedb.db import Database


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
            ) VALUES(?,?, 'global','candidate',2,2,2,2,0,1,1.0,1.0,'{}','{}',?)
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


def test_reversible_inside_envelope_uses_minimal_verify_constraint(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()

    decision = svc.decide(
        {"type": "transition_field", "field_id": "missing", "to_status": "converged"},
        env["id"],
    )
    snapshot = svc.get_constraint_snapshot(decision["constraint_snapshot_id"])

    assert snapshot["methods"] == ["VERIFY"]
    assert snapshot["constraints"]["authority_integrity"] is True
    assert "hidden_cot" not in snapshot


def test_incompatible_consensus_adds_compare_stop_and_escalates(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    packet_id = make_packet(db, "incompatible")

    decision = svc.decide(
        {"type": "accept_proposal", "proposal_id": "p1"},
        env["id"],
        evidence={"consensus_packet_id": packet_id},
    )
    snapshot = svc.get_constraint_snapshot(decision["constraint_snapshot_id"])

    assert decision["decision"] == "ESCALATE"
    assert "consensus_conflict" in decision["reason_codes"]
    assert snapshot["methods"] == ["VERIFY", "COMPARE", "STOP"]
    assert snapshot["constraints"]["consensus_compatible"] is False


def test_irreversible_shared_action_adds_counterexample_and_cannot_execute(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    action = {
        "type": "novel_destructive_compaction",
        "properties": {
            "external": False,
            "shared_world": True,
            "reversible": False,
            "cost_units": 1,
            "resource_owner": "local_database",
            "authority_domain": "sedb.canonical",
            "public_commitment": False,
            "irreversible": True,
        },
    }

    decision = svc.decide(action, env["id"])
    snapshot = svc.get_constraint_snapshot(decision["constraint_snapshot_id"])

    assert decision["decision"] == "ESCALATE"
    assert snapshot["methods"] == ["VERIFY", "COUNTEREXAMPLE"]
    assert snapshot["constraints"]["reversibility_ok"] is False


def test_constraint_snapshot_is_public_signal_record_not_private_reasoning(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    decision = svc.decide(
        {"type": "accept_proposal", "proposal_id": "p1"},
        env["id"],
        evaluator="test:constraint",
    )
    snapshot = svc.get_constraint_snapshot(decision["constraint_snapshot_id"])

    assert set(snapshot) >= {"constraints", "methods", "risk", "basis_sha256"}
    assert set(snapshot["constraints"]) <= {
        "authority_integrity",
        "basis_recorded",
        "consensus_compatible",
        "reversibility_ok",
    }
    assert all(isinstance(item, str) for item in snapshot["methods"])
