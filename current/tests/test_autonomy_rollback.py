import pytest

from sedb.autonomy import AutonomyService
from sedb.db import Database
from sedb.fields import FieldService
from sedb.governance import FieldGovernanceService
from sedb.utility import UtilityService


def setup(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    svc = AutonomyService(db)
    env = svc.ensure_default_envelope()
    return db, svc, env


def test_transition_commit_can_be_compensated_and_history_remains(tmp_path):
    db, svc, env = setup(tmp_path)
    fields = FieldService(db)
    field = fields.create_field(key="rare_signal", label="Rare signal")
    result = svc.execute_autonomously(
        {
            "type": "transition_field",
            "field_id": field["id"],
            "to_status": "converged",
            "reason": "Temporarily unused",
        },
        env["id"],
    )

    rollback = svc.rollback_commit(result["commit"]["id"], evaluator="test:rollback")

    assert fields.get_field(field["id"])["status"] == "active"
    assert rollback["commit_id"] == result["commit"]["id"]
    assert db.scalar("SELECT COUNT(*) FROM autonomy_decisions") == 1
    assert db.scalar("SELECT COUNT(*) FROM autonomy_commit_receipts") == 1
    assert db.scalar("SELECT COUNT(*) FROM autonomy_rollback_receipts") == 1
    assert [event["event_type"] for event in svc.list_commit_events(result["decision"]["id"])] == [
        "preflight", "committed", "rolled_back"
    ]


def test_definition_rollback_appends_restoring_version(tmp_path):
    db, svc, env = setup(tmp_path)
    fields = FieldService(db)
    governance = FieldGovernanceService(db)
    field = fields.create_field(key="quality", label="Quality")
    result = svc.execute_autonomously(
        {
            "type": "update_definition",
            "field_id": field["id"],
            "label": "Quality signal",
            "reason": "Clarify",
        },
        env["id"],
    )
    assert [v["label"] for v in governance.list_versions(field["id"])] == ["Quality", "Quality signal"]

    svc.rollback_commit(result["commit"]["id"])

    versions = governance.list_versions(field["id"])
    assert [v["label"] for v in versions] == ["Quality", "Quality signal", "Quality"]
    assert fields.get_field(field["id"])["label"] == "Quality"


def test_guardrail_rollback_appends_opposite_state(tmp_path):
    db, svc, env = setup(tmp_path)
    fields = FieldService(db)
    utility = UtilityService(db)
    field = fields.create_field(key="critical", label="Critical")
    result = svc.execute_autonomously(
        {
            "type": "set_guardrail",
            "field_id": field["id"],
            "protected": True,
            "reason": "Important",
        },
        env["id"],
    )

    svc.rollback_commit(result["commit"]["id"])

    history = utility.list_guardrail_history(field["id"])
    assert [item["protected"] for item in history] == [True, False]


def test_accept_proposal_rollback_compensates_without_erasing_receipts(tmp_path):
    db, svc, env = setup(tmp_path)
    fields = FieldService(db)
    proposal = fields.create_proposal(
        key="new_dimension",
        label="New dimension",
        reason="Agent evidence",
        proposed_by="agent:test",
    )
    result = svc.execute_autonomously(
        {"type": "accept_proposal", "proposal_id": proposal["id"], "reason": "Accepted autonomously"},
        env["id"],
    )
    target = result["commit"]["mutation"]["target_field_id"]
    assert fields.get_field(target)["status"] == "active"

    svc.rollback_commit(result["commit"]["id"])

    assert fields.get_field(target)["status"] == "deprecated"
    assert fields.get_proposal(proposal["id"])["status"] == "accepted"
    assert db.scalar("SELECT COUNT(*) FROM autonomy_commit_receipts") == 1
    assert db.scalar("SELECT COUNT(*) FROM autonomy_rollback_receipts") == 1


def test_commit_cannot_be_rolled_back_twice(tmp_path):
    db, svc, env = setup(tmp_path)
    fields = FieldService(db)
    field = fields.create_field(key="x", label="X")
    result = svc.execute_autonomously(
        {"type": "set_guardrail", "field_id": field["id"], "protected": True, "reason": "test"},
        env["id"],
    )
    svc.rollback_commit(result["commit"]["id"])

    with pytest.raises(ValueError, match="already rolled back"):
        svc.rollback_commit(result["commit"]["id"])


def test_autonomy_stats_separate_execution_escalation_failure_and_rollback(tmp_path):
    db, svc, env = setup(tmp_path)
    fields = FieldService(db)
    field = fields.create_field(key="stats_field", label="Stats field")
    committed = svc.execute_autonomously(
        {"type": "set_guardrail", "field_id": field["id"], "protected": True, "reason": "stats"},
        env["id"],
    )
    svc.rollback_commit(committed["commit"]["id"])

    svc.decide(
        {
            "type": "external_publish",
            "properties": {
                "external": True,
                "shared_world": True,
                "reversible": True,
                "cost_units": 1,
                "resource_owner": "local_database",
                "authority_domain": "external.publish",
                "public_commitment": True,
                "irreversible": False,
            },
        },
        env["id"],
    )
    novel = svc.decide(
        {
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
        },
        env["id"],
    )
    with pytest.raises(RuntimeError):
        svc.commit_decision(novel["id"])

    stats = svc.stats()

    assert stats["decision_count"] == 3
    assert stats["execute_count"] == 2
    assert stats["escalate_count"] == 1
    assert stats["commit_count"] == 1
    assert stats["commit_failure_count"] == 1
    assert stats["rollback_count"] == 1
    assert stats["autonomous_commit_rate"] == 0.5
    assert stats["escalation_rate"] == pytest.approx(1 / 3)
    assert stats["novel_action_execute_rate"] == pytest.approx(0.5)
