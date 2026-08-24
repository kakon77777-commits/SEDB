import json

import pytest

from sedb.db import Database
from sedb.fields import FieldService


def make_service(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    return db, FieldService(db)


def test_create_field_does_not_create_cells(tmp_path):
    db, fields = make_service(tmp_path)
    created = fields.create_field(
        key="author_country",
        label="Author country",
        value_type="text",
        description="Country associated with the author.",
    )

    assert created["key"] == "author_country"
    assert created["status"] == "active"
    assert db.scalar("SELECT COUNT(*) FROM fields") == 1
    assert db.scalar("SELECT COUNT(*) FROM cells") == 0


def test_field_key_must_be_unique(tmp_path):
    _, fields = make_service(tmp_path)
    fields.create_field(key="year", label="Year")

    with pytest.raises(ValueError, match="already exists"):
        fields.create_field(key="year", label="Duplicate year")


def test_bulk_registers_ten_thousand_fields_without_cells(tmp_path):
    db, fields = make_service(tmp_path)
    specs = [
        {
            "key": f"field_{i:05d}",
            "label": f"Field {i:05d}",
            "value_type": "text",
        }
        for i in range(10_000)
    ]

    inserted = fields.bulk_create_fields(specs)

    assert inserted == 10_000
    assert db.scalar("SELECT COUNT(*) FROM fields") == 10_000
    assert db.scalar("SELECT COUNT(*) FROM cells") == 0


def test_convergence_requires_non_empty_reason(tmp_path):
    _, fields = make_service(tmp_path)
    field = fields.create_field(key="nationality", label="Nationality")

    with pytest.raises(ValueError, match="reason"):
        fields.transition(field["id"], "converged", reason="   ")


def test_convergence_writes_reason_evidence_metrics_and_event(tmp_path):
    db, fields = make_service(tmp_path)
    field = fields.create_field(key="nationality", label="Nationality")

    transitioned = fields.transition(
        field["id"],
        "converged",
        reason="Low marginal discrimination for the current task.",
        evidence={"coverage": 0.81},
        metrics={"missing_rate": 0.19, "utility": 0.08},
        evaluator="agent:test",
        reversible=True,
    )

    assert transitioned["status"] == "converged"
    evaluations = fields.list_evaluations(field["id"])
    assert len(evaluations) == 1
    assert evaluations[0]["decision"] == "converge"
    assert evaluations[0]["reason"].startswith("Low marginal")
    assert evaluations[0]["evidence"] == {"coverage": 0.81}
    assert evaluations[0]["metrics"]["missing_rate"] == 0.19
    assert evaluations[0]["reversible"] is True
    assert db.scalar("SELECT COUNT(*) FROM field_events") == 2


def test_converged_field_can_reactivate_with_reason(tmp_path):
    _, fields = make_service(tmp_path)
    field = fields.create_field(key="ai_evidence", label="AI evidence")
    fields.transition(
        field["id"],
        "converged",
        reason="No current evidence sources add information.",
        evaluator="agent:test",
    )

    with pytest.raises(ValueError, match="reason"):
        fields.transition(field["id"], "active", reason="")

    active = fields.transition(
        field["id"],
        "active",
        reason="A new provenance source became available.",
        evidence={"source": "new-corpus"},
        evaluator="agent:test",
    )

    assert active["status"] == "active"
    evaluations = fields.list_evaluations(field["id"])
    assert [item["decision"] for item in evaluations] == ["converge", "reactivate"]


def test_field_proposals_are_separate_from_active_registry(tmp_path):
    db, fields = make_service(tmp_path)

    proposal = fields.create_proposal(
        key="ai_use_verifiability",
        label="AI use verifiability",
        reason="May distinguish AI-native research production.",
        proposed_by="agent:test",
    )

    assert proposal["status"] == "pending"
    assert db.scalar("SELECT COUNT(*) FROM field_proposals") == 1
    assert db.scalar("SELECT COUNT(*) FROM fields") == 0


def test_normalized_duplicate_field_key_is_rejected(tmp_path):
    _, fields = make_service(tmp_path)
    original = fields.create_field(key="Author-Country", label="Author country", namespace="global")

    assert original["namespace"] == "global"
    assert original["normalized_key"] == "author_country"
    with pytest.raises(ValueError, match="normalized"):
        fields.create_field(key=" author / country ", label="Same semantic key", namespace="global")
