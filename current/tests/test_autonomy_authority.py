from sedb.autonomy import AutonomyService
from sedb.db import Database


def service(tmp_path):
    return AutonomyService(Database(tmp_path / "sedb.sqlite"))


def test_default_envelope_is_local_shared_reversible_not_external(tmp_path):
    svc = service(tmp_path)
    env = svc.ensure_default_envelope()

    assert env["id"] == "sedb-local-canonical-v1"
    assert env["rules"]["authority_domains"] == ["sedb.canonical"]
    assert env["rules"]["resource_owners"] == ["local_database"]
    assert env["rules"]["allow_shared_world"] is True
    assert env["rules"]["allow_external"] is False
    assert env["rules"]["allow_irreversible"] is False


def test_known_accept_proposal_properties_are_inferred(tmp_path):
    props = service(tmp_path).classify_action({"type": "accept_proposal", "proposal_id": "p1"})

    assert props["complete"] is True
    assert props["shared_world"] is True
    assert props["external"] is False
    assert props["reversible"] is True
    assert props["authority_domain"] == "sedb.canonical"


def test_novel_action_with_explicit_legal_properties_can_receive_execute(tmp_path):
    svc = service(tmp_path)
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

    decision = svc.decide(action, env["id"], evaluator="test:novel")

    assert decision["decision"] == "EXECUTE"
    assert "unknown_action" in decision["reason_codes"]
    assert "unauthorized" not in " ".join(decision["reason_codes"]).lower()


def test_novel_action_without_effect_classification_defers_not_refuses(tmp_path):
    svc = service(tmp_path)
    env = svc.ensure_default_envelope()

    decision = svc.decide({"type": "novel_thing"}, env["id"])

    assert decision["decision"] == "DEFER"
    assert "effect_classification_incomplete" in decision["reason_codes"]


def test_external_or_wrong_authority_domain_escalates(tmp_path):
    svc = service(tmp_path)
    env = svc.ensure_default_envelope()
    action = {
        "type": "novel_external_publish",
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
    }

    decision = svc.decide(action, env["id"])

    assert decision["decision"] == "ESCALATE"
    assert "external_effect_not_delegated" in decision["reason_codes"]
    assert "authority_domain_not_delegated" in decision["reason_codes"]


def test_envelope_installation_is_not_an_autonomous_commit_adapter(tmp_path):
    svc = service(tmp_path)
    assert "install_envelope" not in svc.commit_adapter_names()
