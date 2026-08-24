from sedb.agent import AgentService
from sedb.db import Database


def test_agent_run_creation_records_policy_budget_and_created_event(tmp_path):
    service = AgentService(Database(tmp_path / "agent.sqlite"))

    run = service.create_run(
        backend="deterministic-discovery-v1",
        budget={"max_steps": 7, "max_proposals": 2},
        input_payload={"records": []},
        evaluator="test:agent",
    )

    assert run["status"] == "created"
    assert run["budget"]["max_steps"] == 7
    assert run["budget"]["max_proposals"] == 2
    assert run["counters"]["steps"] == 0
    assert run["events"][0]["event_type"] == "created"
    assert len(run["input_sha256"]) == 64
    assert len(run["basis_sha256"]) == 64


def test_record_observation_starts_run_and_increments_counters(tmp_path):
    service = AgentService(Database(tmp_path / "agent.sqlite"))
    run = service.create_run(backend="deterministic-discovery-v1")

    observation = service.record_observation(run["id"], {"records": [{"x": 1}]})
    detail = service.get_run(run["id"])

    assert observation["ordinal"] == 0
    assert observation["payload"] == {"records": [{"x": 1}]}
    assert detail["status"] == "running"
    assert detail["counters"]["observations"] == 1
    assert detail["counters"]["steps"] == 1
    assert [event["event_type"] for event in detail["events"]] == ["created", "started"]


def test_capability_gate_persists_denied_mutation_receipt(tmp_path):
    service = AgentService(Database(tmp_path / "agent.sqlite"))
    run = service.create_run(backend="external-suggestion-v1")

    receipt = service.execute_intent(
        run["id"],
        "set_cell",
        {"entity_id": "e1", "field": "x", "value": 1},
        evidence_refs=["obs:1#/x"],
    )

    assert receipt["capability_decision"] == "DENIED"
    assert receipt["outcome"] == "DENIED"
    assert "canonical mutation" in receipt["reason"].lower()
    assert receipt["evidence_refs"] == ["obs:1#/x"]


def test_allowed_advisory_intent_is_authorized_without_mutation(tmp_path):
    service = AgentService(Database(tmp_path / "agent.sqlite"))
    run = service.create_run(backend="deterministic-discovery-v1")

    receipt = service.execute_intent(run["id"], "create_proposal", {"key": "new_signal"})

    assert receipt["capability_decision"] == "ALLOWED"
    assert receipt["outcome"] == "AUTHORIZED"
    assert service.get_run(run["id"])["counters"]["proposals"] == 1


def test_budget_exhaustion_halts_future_actions_and_records_event(tmp_path):
    service = AgentService(Database(tmp_path / "agent.sqlite"))
    run = service.create_run(
        backend="deterministic-discovery-v1",
        budget={"max_steps": 1, "max_observations": 1, "max_proposals": 5},
    )

    service.record_observation(run["id"], {"x": 1})
    receipt = service.execute_intent(run["id"], "create_proposal", {"key": "y"})
    detail = service.get_run(run["id"])

    assert receipt["outcome"] == "BUDGET_EXHAUSTED"
    assert detail["status"] == "budget_exhausted"
    assert detail["counters"]["proposals"] == 0
    assert detail["counters"]["steps"] == 1
    assert detail["events"][-1]["event_type"] == "budget_exhausted"


def test_list_runs_returns_decoded_budget_and_counters(tmp_path):
    service = AgentService(Database(tmp_path / "agent.sqlite"))
    first = service.create_run(backend="deterministic-discovery-v1")
    second = service.create_run(backend="external-suggestion-v1")

    rows = service.list_runs(limit=10)

    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert all(isinstance(row["budget"], dict) for row in rows)
    assert all(isinstance(row["counters"], dict) for row in rows)


def test_completed_run_rejects_late_intents_without_appending_receipt(tmp_path):
    import pytest

    service = AgentService(Database(tmp_path / "agent.sqlite"))
    run = service.run_deterministic({}, score_proposals=False, assess_existing=False)
    before_actions = len(run["actions"])

    with pytest.raises(ValueError, match="terminal"):
        service.execute_intent(run["id"], "set_cell", {"value": 1})

    assert len(service.get_run(run["id"])["actions"]) == before_actions
