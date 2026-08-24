import importlib.util


def test_utility_module_exists():
    assert importlib.util.find_spec("sedb.utility") is not None

import pytest

from sedb.db import Database
from sedb.fields import FieldService
from sedb.utility import UtilityService


def make_services(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    return db, FieldService(db), UtilityService(db)


def test_guardrail_requires_reason_and_history_is_append_only(tmp_path):
    _, fields, utility = make_services(tmp_path)
    field = fields.create_field(key="rare_signal", label="Rare signal")

    with pytest.raises(ValueError, match="reason"):
        utility.set_guardrail(field["id"], True, reason="   ")

    protected = utility.set_guardrail(
        field["id"], True, reason="Rare but safety-critical", evaluator="human:test"
    )
    unprotected = utility.set_guardrail(
        field["id"], False, reason="Protection no longer required", evaluator="human:test"
    )

    assert protected["protected"] is True
    assert unprotected["protected"] is False
    current = utility.get_guardrail(field["id"])
    history = utility.list_guardrail_history(field["id"])
    assert current["id"] == unprotected["id"]
    assert [item["protected"] for item in history] == [True, False]
    assert [item["reason"] for item in history] == [
        "Rare but safety-critical",
        "Protection no longer required",
    ]


def test_guardrail_field_alias_resolves_to_canonical_field(tmp_path):
    from sedb.governance import FieldGovernanceService

    _, fields, utility = make_services(tmp_path)
    field = fields.create_field(key="source_quality", label="Source quality")
    FieldGovernanceService(utility.db).add_alias(
        field["id"], "source-reliability", reason="Legacy term"
    )

    event = utility.set_guardrail(
        "source-reliability", True, reason="Preserve audit dimension", evaluator="agent:test"
    )

    assert event["field_id"] == field["id"]
    assert utility.get_guardrail(field["id"])["protected"] is True

from datetime import datetime, timedelta, timezone

from sedb.entities import EntityService
from sedb.views import ViewService


def plus_days(iso_text: str, days: int) -> str:
    dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00")) + timedelta(days=days)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_new_empty_field_is_insufficient_evidence(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    field = fields.create_field(key="fresh_signal", label="Fresh signal")

    assessment = utility.assess_field(field["id"], as_of=field["created_at"])

    assert assessment["recommendation"] == "insufficient_evidence"
    assert assessment["metrics"]["field_age_days"] == 0.0
    assert assessment["metrics"]["cell_count"] == 0


def test_old_unused_field_is_convergence_candidate(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    field = fields.create_field(key="old_unused", label="Old unused")

    assessment = utility.assess_field(field["id"], as_of=plus_days(field["created_at"], 8))

    assert assessment["recommendation"] == "converge_candidate"
    assert assessment["score"] == pytest.approx(0.15)
    assert assessment["metrics"]["coverage"] == 0.0
    assert assessment["metrics"]["task_support"] == 0.0
    assert assessment["metrics"]["semantic_redundancy"] == 0.0


def test_protected_old_unused_field_is_kept(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    field = fields.create_field(key="protected_unused", label="Protected unused")
    utility.set_guardrail(field["id"], True, reason="Rare compliance dimension")

    assessment = utility.assess_field(field["id"], as_of=plus_days(field["created_at"], 30))

    assert assessment["recommendation"] == "keep"
    assert assessment["metrics"]["protected"] is True


def test_task_view_support_keeps_sparse_field(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    field = fields.create_field(key="rare_task_signal", label="Rare task signal")
    ViewService(utility.db).create_view("Rare audit", [field["key"]])

    assessment = utility.assess_field(field["id"], as_of=plus_days(field["created_at"], 30))

    assert assessment["recommendation"] == "keep"
    assert assessment["score"] == pytest.approx(0.55)
    assert assessment["metrics"]["task_view_count"] == 1
    assert assessment["metrics"]["task_support"] == 1.0


def test_assessment_is_persisted_with_policy_and_explainable_components(tmp_path):
    _, fields, utility = make_services(tmp_path)
    entity_service = EntityService(utility.db)
    first = entity_service.create_entity(label="Row 1")
    entity_service.create_entity(label="Row 2")
    field = fields.create_field(key="coverage_signal", label="Coverage signal")
    entity_service.set_cell(first["id"], field["key"], True)

    assessment = utility.assess_field(field["id"], as_of=plus_days(field["created_at"], 30))
    loaded = utility.get_assessment(assessment["id"])
    history = utility.list_assessments(field["id"])

    assert assessment["policy_version"] == "utility-v1"
    assert assessment["evaluator"] == "system:utility"
    assert assessment["metrics"]["coverage"] == pytest.approx(0.5)
    assert assessment["score"] == pytest.approx(0.375)
    assert loaded["id"] == assessment["id"]
    assert history[-1]["id"] == assessment["id"]
    assert assessment["policy"]["weights"] == {
        "coverage": 0.45,
        "task_support": 0.40,
        "inverse_semantic_redundancy": 0.15,
    }

from sedb.semantic import SemanticDedupService


def test_pending_semantic_candidate_lowers_operational_utility(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    left = fields.create_field(key="source_quality", label="Source quality")
    fields.create_field(key="quality_source", label="Quality source")
    as_of = plus_days(left["created_at"], 30)

    before = utility.assess_field(left["id"], as_of=as_of)
    found = SemanticDedupService(utility.db).scan_field_similarity(
        namespace="global", threshold=0.70, max_neighbors=4
    )
    after = utility.assess_field(left["id"], as_of=as_of)

    assert found
    assert before["metrics"]["semantic_redundancy"] == 0.0
    assert after["metrics"]["semantic_redundancy"] >= 0.70
    assert after["score"] < before["score"]
    assert after["evidence"]["semantic_candidate_ids"]


def test_converged_field_with_post_convergence_cell_is_reactivation_candidate(tmp_path):
    _, fields, utility = make_services(tmp_path)
    entity_service = EntityService(utility.db)
    entity = entity_service.create_entity(label="Row 1")
    field = fields.create_field(key="revived_by_cell", label="Revived by cell")
    fields.transition(field["id"], "converged", reason="No current use")
    entity_service.set_cell(entity["id"], field["key"], "new evidence")

    assessment = utility.assess_field(field["id"])

    assert assessment["recommendation"] == "reactivate_candidate"
    assert assessment["evidence"]["latest_converged_at"] is not None
    assert assessment["metrics"]["post_convergence_cell"] is True


def test_converged_field_with_new_task_view_is_reactivation_candidate(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    field = fields.create_field(key="revived_by_view", label="Revived by view")
    fields.transition(field["id"], "converged", reason="No current task support")
    ViewService(utility.db).create_view("New task", [field["key"]])

    assessment = utility.assess_field(field["id"])

    assert assessment["recommendation"] == "reactivate_candidate"
    assert assessment["metrics"]["post_convergence_task_view"] is True


def test_apply_convergence_candidate_requires_reason_and_preserves_assessment_audit(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    field = fields.create_field(key="apply_unused", label="Apply unused")
    assessment = utility.assess_field(field["id"], as_of=plus_days(field["created_at"], 30))
    assert assessment["recommendation"] == "converge_candidate"

    with pytest.raises(ValueError, match="reason"):
        utility.apply_assessment(assessment["id"], reason="   ")

    result = utility.apply_assessment(
        assessment["id"], reason="Reviewed low-utility assessment", evaluator="human:test"
    )
    evaluations = fields.list_evaluations(field["id"])

    assert result["field"]["status"] == "converged"
    assert result["assessment"]["id"] == assessment["id"]
    assert evaluations[-1]["decision"] == "converge"
    assert evaluations[-1]["evidence"]["assessment_id"] == assessment["id"]
    assert evaluations[-1]["evidence"]["policy_version"] == "utility-v1"
    assert evaluations[-1]["metrics"] == assessment["metrics"]


def test_apply_rejects_stale_assessment_after_cell_basis_changes(tmp_path):
    _, fields, utility = make_services(tmp_path)
    entity_service = EntityService(utility.db)
    entity = entity_service.create_entity(label="Row 1")
    field = fields.create_field(key="stale_unused", label="Stale unused")
    assessment = utility.assess_field(field["id"], as_of=plus_days(field["created_at"], 30))
    assert assessment["recommendation"] == "converge_candidate"

    entity_service.set_cell(entity["id"], field["key"], "new evidence")

    with pytest.raises(ValueError, match="stale"):
        utility.apply_assessment(
            assessment["id"], reason="Attempt to apply old assessment", evaluator="human:test"
        )
    assert fields.get_field(field["id"])["status"] == "active"


def test_non_actionable_assessment_cannot_be_applied(tmp_path):
    _, fields, utility = make_services(tmp_path)
    EntityService(utility.db).create_entity(label="Row 1")
    field = fields.create_field(key="fresh_non_actionable", label="Fresh non actionable")
    assessment = utility.assess_field(field["id"], as_of=field["created_at"])
    assert assessment["recommendation"] == "insufficient_evidence"

    with pytest.raises(ValueError, match="not actionable"):
        utility.apply_assessment(
            assessment["id"], reason="No lifecycle mutation", evaluator="human:test"
        )


def test_apply_reactivation_candidate_uses_existing_transition_path(tmp_path):
    _, fields, utility = make_services(tmp_path)
    entity_service = EntityService(utility.db)
    entity = entity_service.create_entity(label="Row 1")
    field = fields.create_field(key="apply_reactivation", label="Apply reactivation")
    fields.transition(field["id"], "converged", reason="Temporarily unused")
    entity_service.set_cell(entity["id"], field["key"], 1)
    assessment = utility.assess_field(field["id"])
    assert assessment["recommendation"] == "reactivate_candidate"

    result = utility.apply_assessment(
        assessment["id"], reason="New evidence reviewed", evaluator="human:test"
    )

    assert result["field"]["status"] == "active"
    assert fields.list_evaluations(field["id"])[-1]["decision"] == "reactivate"


def test_registry_assessment_is_bounded_and_respects_statuses(tmp_path):
    db, fields, utility = make_services(tmp_path)
    EntityService(db).create_entity(label="Row 1")
    created = [
        fields.create_field(key=f"batch_{i:02d}", label=f"Batch {i:02d}")
        for i in range(12)
    ]
    fields.transition(created[-1]["id"], "converged", reason="Batch converged fixture")

    active = utility.assess_registry(
        statuses=("active",), limit_fields=5, offset=0, evaluator="batch:test"
    )
    converged = utility.assess_registry(
        statuses=("converged",), limit_fields=5, offset=0, evaluator="batch:test"
    )

    assert len(active) == 5
    assert {item["field_status"] for item in active} == {"active"}
    assert len(converged) == 1
    assert converged[0]["field_status"] == "converged"
    assert db.scalar("SELECT COUNT(*) FROM field_utility_assessments") == 6


def test_registry_assessment_limit_is_capped_and_empty_statuses_rejected(tmp_path):
    _, fields, utility = make_services(tmp_path)
    fields.bulk_create_fields(
        {"key": f"cap_{i:02d}", "label": f"Cap {i:02d}"} for i in range(20)
    )

    with pytest.raises(ValueError, match="status"):
        utility.assess_registry(statuses=(), limit_fields=5)

    items = utility.assess_registry(statuses=("active",), limit_fields=3)
    assert len(items) == 3
