from __future__ import annotations

import json
import sqlite3

import pytest

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService


FAMILY_TABLES = {
    "field_family_proposals",
    "field_family_proposal_members",
    "field_family_reviews",
    "field_families",
    "field_family_members",
    "field_family_events",
}


def test_family_schema_migrates_without_data_loss(tmp_path):
    path = tmp_path / "migration.sqlite"
    db = Database(path)
    fields = FieldService(db)
    entities = EntityService(db)
    field = fields.create_field(key="legacy_signal", label="Legacy signal")
    entity = entities.create_entity(label="Legacy row")
    entities.set_cell(entity["id"], field["key"], {"kept": True})

    reopened = Database(path)
    with reopened.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        stored = conn.execute(
            "SELECT entity_id,field_id,value_json FROM cells"
        ).fetchone()

    assert FAMILY_TABLES <= tables
    assert stored["entity_id"] == entity["id"]
    assert stored["field_id"] == field["id"]
    assert json.loads(stored["value_json"]) == {"kept": True}


def test_family_proposal_header_and_members_are_sqlite_immutable(tmp_path):
    db = Database(tmp_path / "immutable.sqlite")
    field = FieldService(db).create_field(key="alpha", label="Alpha")
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO field_family_proposals(
                id,namespace,policy_version,seed_field_id,member_count,
                min_pair_score,avg_pair_score,basis_sha256,parameters_json,evidence_json,created_at
            ) VALUES('p1','global','family-v1',?,1,1.0,1.0,'basis','{}','{}','2026-08-22T00:00:00Z')
            """,
            (field["id"],),
        )
        conn.execute(
            """
            INSERT INTO field_family_proposal_members(
                proposal_id,field_id,ordinal,seed_score,min_peer_score,avg_peer_score,evidence_json
            ) VALUES('p1',?,0,1.0,1.0,1.0,'{}')
            """,
            (field["id"],),
        )

    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE field_family_proposals SET member_count=2 WHERE id='p1'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM field_family_proposal_members WHERE proposal_id='p1'")


def _family_services(tmp_path):
    from sedb.family import FieldFamilyService

    db = Database(tmp_path / "family.sqlite")
    return db, FieldService(db), FieldFamilyService(db)


def _create_source_quality_fixture(fields):
    return [
        fields.create_field(
            key="source_quality", label="Source quality", value_type="number",
            description="quality of source",
        ),
        fields.create_field(
            key="quality_source", label="Quality source", value_type="number",
            description="source quality metric",
        ),
        fields.create_field(
            key="source_quality_score", label="Source quality score", value_type="number",
            description="score for source quality",
        ),
    ]


def test_coherent_seed_proposal_contains_all_three_members(tmp_path):
    _, fields, families = _family_services(tmp_path)
    created = _create_source_quality_fixture(fields)

    proposal = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.70,
        max_neighbors=8, max_members=5,
    )

    assert proposal is not None
    assert proposal["member_count"] == 3
    assert {item["field_id"] for item in proposal["members"]} == {
        item["id"] for item in created
    }
    assert proposal["min_pair_score"] >= 0.70
    assert proposal["avg_pair_score"] >= proposal["min_pair_score"]
    assert len(proposal["basis_sha256"]) == 64


def test_complete_link_guard_blocks_semantic_chain_member(tmp_path):
    _, fields, families = _family_services(tmp_path)
    created = _create_source_quality_fixture(fields)

    proposal = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.72,
        max_neighbors=8, max_members=5,
    )

    assert proposal is not None
    assert {item["field_id"] for item in proposal["members"]} == {
        created[0]["id"], created[1]["id"]
    }
    assert created[2]["id"] not in {item["field_id"] for item in proposal["members"]}


def test_family_proposal_excludes_type_and_namespace_conflicts(tmp_path):
    _, fields, families = _family_services(tmp_path)
    seed = fields.create_field(
        key="source_quality", label="Source quality", value_type="number", namespace="global"
    )
    compatible = fields.create_field(
        key="quality_source", label="Quality source", value_type="number", namespace="global"
    )
    type_conflict = fields.create_field(
        key="source_quality_text", label="Source quality text", value_type="text", namespace="global"
    )
    namespace_conflict = fields.create_field(
        key="source_quality_external", label="Source quality external", value_type="number", namespace="external"
    )

    proposal = families.propose_from_seed(
        seed["id"], seed_threshold=0.65, min_coherence=0.65,
        max_neighbors=8, max_members=8, namespace="global",
    )

    assert proposal is not None
    member_ids = {item["field_id"] for item in proposal["members"]}
    assert compatible["id"] in member_ids
    assert type_conflict["id"] not in member_ids
    assert namespace_conflict["id"] not in member_ids


def test_duplicate_family_review_creates_family_without_mutating_fields_or_cells(tmp_path):
    from sedb.entities import EntityService

    db, fields, families = _family_services(tmp_path)
    created = _create_source_quality_fixture(fields)
    entity_service = EntityService(db)
    entity = entity_service.create_entity(label="Row 1")
    entity_service.set_cell(entity["id"], created[1]["key"], 7)
    proposal = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.70
    )
    before_fields = db.scalar("SELECT COUNT(*) FROM fields")
    before_cells = db.scalar("SELECT COUNT(*) FROM cells")
    before_statuses = {
        row["id"]: row["status"] for row in fields.list_fields(limit=100)
    }

    result = families.review_proposal(
        proposal["id"], "duplicate_family", reason="Reviewed as one duplicate field family",
        evaluator="human:test",
    )
    family = result["family"]

    assert family["family_type"] == "duplicate"
    assert {m["field_id"] for m in family["members"]} == {
        item["id"] for item in created
    }
    assert db.scalar("SELECT COUNT(*) FROM fields") == before_fields
    assert db.scalar("SELECT COUNT(*) FROM cells") == before_cells
    assert {
        row["id"]: row["status"] for row in fields.list_fields(limit=100)
    } == before_statuses
    assert entity_service.get_entity(entity["id"])["cells"][created[1]["key"]]["value"] == 7


def test_related_and_reject_reviews_are_auditable_and_one_shot(tmp_path):
    _, fields, families = _family_services(tmp_path)
    created = _create_source_quality_fixture(fields)
    related = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.70
    )
    related_result = families.review_proposal(
        related["id"], "related_family", reason="Same semantic neighborhood"
    )
    assert related_result["family"]["family_type"] == "related"
    assert related_result["review"]["decision"] == "related_family"

    other_fields = FieldService(families.db)
    seed = other_fields.create_field(key="model_latency", label="Model latency", value_type="number")
    peer = other_fields.create_field(key="latency_model", label="Latency model", value_type="number")
    rejected = families.propose_from_seed(
        seed["id"], seed_threshold=0.70, min_coherence=0.70
    )
    assert rejected is not None
    rejected_result = families.review_proposal(
        rejected["id"], "reject", reason="Names overlap but semantics are not one family"
    )
    assert rejected_result["family"] is None
    assert rejected_result["review"]["decision"] == "reject"
    with pytest.raises(ValueError, match="already reviewed"):
        families.review_proposal(rejected["id"], "reject", reason="Second review")


def test_stale_family_proposal_cannot_be_reviewed_after_definition_change(tmp_path):
    from sedb.governance import FieldGovernanceService

    db, fields, families = _family_services(tmp_path)
    created = _create_source_quality_fixture(fields)
    proposal = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.70
    )
    FieldGovernanceService(db).update_definition(
        created[1]["id"], label="Source quality reliability",
        reason="Semantic definition refined", evaluator="human:test",
    )

    with pytest.raises(ValueError, match="stale"):
        families.review_proposal(
            proposal["id"], "duplicate_family", reason="Old proposal should not apply"
        )
    assert db.scalar("SELECT COUNT(*) FROM field_families") == 0


def test_split_review_requires_exact_partition_and_creates_no_family(tmp_path):
    _, fields, families = _family_services(tmp_path)
    created = _create_source_quality_fixture(fields)
    proposal = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.70
    )
    member_ids = [m["field_id"] for m in proposal["members"]]

    with pytest.raises(ValueError, match="partition"):
        families.review_proposal(
            proposal["id"], "split", reason="Bad split",
            partitions=[[member_ids[0]], [member_ids[1]]],
        )

    result = families.review_proposal(
        proposal["id"], "split", reason="Third field is a separate subfamily",
        partitions=[[member_ids[0], member_ids[1]], [member_ids[2]]],
    )
    assert result["family"] is None
    assert result["review"]["decision"] == "split"
    assert result["review"]["decision_data"]["partitions"] == [
        [member_ids[0], member_ids[1]], [member_ids[2]]
    ]
    assert families.db.scalar("SELECT COUNT(*) FROM field_families") == 0


def test_active_duplicate_family_membership_cannot_overlap(tmp_path):
    _, fields, families = _family_services(tmp_path)
    created = _create_source_quality_fixture(fields)
    proposal = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.72
    )
    first = families.review_proposal(
        proposal["id"], "duplicate_family", reason="First confirmed duplicate family"
    )
    assert first["family"] is not None

    second = families.propose_from_seed(
        created[0]["id"], seed_threshold=0.70, min_coherence=0.72
    )
    assert second is not None
    assert {m["field_id"] for m in second["members"]} == {
        created[0]["id"], created[1]["id"]
    }
    with pytest.raises(ValueError, match="duplicate family"):
        families.review_proposal(
            second["id"], "duplicate_family", reason="Would overlap existing duplicate family"
        )


def _create_latency_fixture(fields):
    return [
        fields.create_field(
            key="model_latency", label="Model latency", value_type="number",
            description="latency of model",
        ),
        fields.create_field(
            key="latency_model", label="Latency model", value_type="number",
            description="model latency metric",
        ),
        fields.create_field(
            key="model_latency_score", label="Model latency score", value_type="number",
            description="score for model latency",
        ),
    ]


def test_registry_scan_finds_multiple_coherent_families_without_component_chaining(tmp_path):
    _, fields, families = _family_services(tmp_path)
    quality = _create_source_quality_fixture(fields)
    latency = _create_latency_fixture(fields)

    proposals = families.scan_registry(
        namespace="global", seed_threshold=0.70, min_coherence=0.70,
        max_neighbors=8, max_members=5, limit_fields=100, max_proposals=10,
    )
    member_sets = [{m["field_id"] for m in proposal["members"]} for proposal in proposals]

    assert {item["id"] for item in quality} in member_sets
    assert {item["id"] for item in latency} in member_sets
    assert all(len(member_set) <= 3 for member_set in member_sets)


def test_registry_scan_complete_link_guard_prevents_three_node_chain(tmp_path):
    _, fields, families = _family_services(tmp_path)
    _create_source_quality_fixture(fields)

    proposals = families.scan_registry(
        namespace="global", seed_threshold=0.70, min_coherence=0.72,
        max_neighbors=8, max_members=5, limit_fields=100, max_proposals=10,
    )

    assert proposals
    assert all(proposal["member_count"] == 2 for proposal in proposals)


def test_registry_scan_respects_proposal_and_member_caps(tmp_path):
    _, fields, families = _family_services(tmp_path)
    for index in range(8):
        fields.create_field(
            key=f"metric_{index}_value", label=f"Metric {index} value", value_type="number"
        )
        fields.create_field(
            key=f"value_metric_{index}", label=f"Value metric {index}", value_type="number"
        )

    proposals = families.scan_registry(
        namespace="global", seed_threshold=0.75, min_coherence=0.75,
        max_neighbors=4, max_members=2, limit_fields=8, max_proposals=2,
    )

    assert len(proposals) <= 2
    assert all(proposal["member_count"] <= 2 for proposal in proposals)
