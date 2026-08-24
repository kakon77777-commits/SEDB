import importlib

import pytest

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


def make_services(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    fields = FieldService(db)
    entities = EntityService(db)
    views = ViewService(db)
    governance_module = importlib.import_module("sedb.governance")
    governance = governance_module.FieldGovernanceService(db)
    return db, fields, entities, views, governance


def test_alias_resolves_to_same_canonical_field_for_cells_and_views(tmp_path):
    db, fields, entities, views, governance = make_services(tmp_path)
    field = fields.create_field(key="author_country", label="Author country")
    alias = governance.add_alias(
        field["id"],
        "country-of-author",
        reason="Legacy/import vocabulary",
    )
    entity = entities.create_entity(label="Paper 1", kind="paper")

    cell = entities.set_cell(entity["id"], "country-of-author", "Taiwan", source="test")
    view = views.create_view("Alias view", ["country-of-author"])
    resolved = governance.resolve_field("country-of-author")

    assert alias["field_id"] == field["id"]
    assert resolved["id"] == field["id"]
    assert cell["value"] == "Taiwan"
    assert view["fields"][0]["id"] == field["id"]
    assert db.scalar("SELECT COUNT(*) FROM fields") == 1


def test_alias_collision_cannot_point_to_two_fields(tmp_path):
    _, fields, _, _, governance = make_services(tmp_path)
    first = fields.create_field(key="author_country", label="Author country")
    second = fields.create_field(key="institution_country", label="Institution country")
    governance.add_alias(first["id"], "research-country", reason="first mapping")

    with pytest.raises(ValueError, match="alias"):
        governance.add_alias(second["id"], "research country", reason="conflicting mapping")


def test_accept_unique_proposal_creates_one_canonical_field_and_decision(tmp_path):
    db, fields, _, _, governance = make_services(tmp_path)
    proposal = fields.create_proposal(
        key="ai_evidence",
        label="AI evidence",
        reason="Useful discriminator",
        proposed_by="agent:test",
    )

    decision = governance.decide_proposal(
        proposal["id"],
        "accept",
        reason="Approved after deterministic review",
        evaluator="reviewer:test",
        evidence={"review": "ok"},
    )

    assert decision["decision"] == "accepted"
    assert decision["outcome"] == "created"
    assert decision["target_field_id"]
    assert fields.get_proposal(proposal["id"])["status"] == "accepted"
    assert db.scalar("SELECT COUNT(*) FROM fields") == 1
    assert governance.resolve_field("ai_evidence")["id"] == decision["target_field_id"]


def test_accept_normalized_duplicate_aliases_existing_field_without_new_canonical(tmp_path):
    db, fields, _, _, governance = make_services(tmp_path)
    existing = fields.create_field(key="author_country", label="Author country")
    proposal = fields.create_proposal(
        key="Author-Country",
        label="Author country duplicate wording",
        reason="Imported vocabulary",
        proposed_by="agent:test",
    )

    decision = governance.decide_proposal(
        proposal["id"],
        "accept",
        reason="Same normalized identity; keep as alias",
        evaluator="reviewer:test",
    )

    assert decision["decision"] == "accepted"
    assert decision["outcome"] == "alias_existing"
    assert decision["target_field_id"] == existing["id"]
    assert db.scalar("SELECT COUNT(*) FROM fields") == 1
    assert governance.resolve_field("Author-Country")["id"] == existing["id"]
    aliases = governance.list_aliases(existing["id"])
    assert any(item["alias"] == "Author-Country" for item in aliases)


def test_reject_proposal_requires_reason_and_cannot_be_decided_twice(tmp_path):
    db, fields, _, _, governance = make_services(tmp_path)
    proposal = fields.create_proposal(
        key="weak_field",
        label="Weak field",
        reason="Agent proposed it",
        proposed_by="agent:test",
    )

    with pytest.raises(ValueError, match="reason"):
        governance.decide_proposal(proposal["id"], "reject", reason="")

    decision = governance.decide_proposal(
        proposal["id"],
        "reject",
        reason="No measurable utility",
        evaluator="reviewer:test",
    )

    assert decision["decision"] == "rejected"
    assert decision["outcome"] == "rejected"
    assert decision["target_field_id"] is None
    assert fields.get_proposal(proposal["id"])["status"] == "rejected"
    assert db.scalar("SELECT COUNT(*) FROM fields") == 0

    with pytest.raises(ValueError, match="already decided"):
        governance.decide_proposal(
            proposal["id"],
            "accept",
            reason="Changed mind",
            evaluator="reviewer:test",
        )


def test_new_field_starts_with_immutable_version_one(tmp_path):
    _, fields, _, _, governance = make_services(tmp_path)
    field = fields.create_field(
        key="evidence_quality",
        label="Evidence quality",
        value_type="number",
        description="Initial definition",
    )

    versions = governance.list_versions(field["id"])

    assert [(v["version"], v["label"], v["description"]) for v in versions] == [
        (1, "Evidence quality", "Initial definition")
    ]


def test_definition_update_requires_reason_and_appends_without_rewriting_history(tmp_path):
    _, fields, _, _, governance = make_services(tmp_path)
    field = fields.create_field(
        key="source_quality",
        label="Source quality",
        description="Original definition",
    )

    with pytest.raises(ValueError, match="reason"):
        governance.update_definition(field["id"], label="Source reliability", reason="")

    updated = governance.update_definition(
        field["id"],
        label="Source reliability",
        description="Revised definition",
        reason="Clarified operational meaning",
        evaluator="reviewer:test",
    )
    versions = governance.list_versions(field["id"])

    assert updated["label"] == "Source reliability"
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["label"] == "Source quality"
    assert versions[0]["description"] == "Original definition"
    assert versions[1]["label"] == "Source reliability"
    assert versions[1]["description"] == "Revised definition"
    assert versions[1]["reason"] == "Clarified operational meaning"


def test_merge_records_lineage_and_leaves_source_cells_in_place(tmp_path):
    db, fields, entities, _, governance = make_services(tmp_path)
    source = fields.create_field(key="author_nation", label="Author nation")
    target = fields.create_field(key="author_country", label="Author country")
    entity = entities.create_entity(label="Paper 1", kind="paper")
    entities.set_cell(entity["id"], source["key"], "Taiwan", source="legacy")

    edges = governance.merge_fields(
        [source["id"]],
        target["id"],
        reason="Canonicalize equivalent geography field",
        evaluator="reviewer:test",
        evidence={"comparison": "equivalent"},
    )

    assert fields.get_field(source["id"])["status"] == "merged"
    assert [(edge["parent_field_id"], edge["child_field_id"], edge["relation"]) for edge in edges] == [
        (source["id"], target["id"], "merged_into")
    ]
    assert db.scalar("SELECT COUNT(*) FROM cells WHERE field_id=?", (source["id"],)) == 1
    assert db.scalar("SELECT COUNT(*) FROM cells WHERE field_id=?", (target["id"],)) == 0


def test_split_records_multiple_child_edges_without_copying_cells(tmp_path):
    db, fields, entities, _, governance = make_services(tmp_path)
    source = fields.create_field(key="country", label="Country")
    child_a = fields.create_field(key="author_country", label="Author country")
    child_b = fields.create_field(key="institution_country", label="Institution country")
    entity = entities.create_entity(label="Paper 1", kind="paper")
    entities.set_cell(entity["id"], source["key"], "Taiwan", source="legacy")

    edges = governance.split_field(
        source["id"],
        [child_a["id"], child_b["id"]],
        reason="Separate author and institution geography",
        evaluator="reviewer:test",
    )

    assert fields.get_field(source["id"])["status"] == "split"
    assert {(edge["child_field_id"], edge["relation"]) for edge in edges} == {
        (child_a["id"], "split_into"),
        (child_b["id"], "split_into"),
    }
    assert db.scalar("SELECT COUNT(*) FROM cells WHERE field_id=?", (source["id"],)) == 1
    assert db.scalar("SELECT COUNT(*) FROM cells WHERE field_id IN (?,?)", (child_a["id"], child_b["id"])) == 0


def test_direct_merge_or_split_transition_is_rejected_without_lineage(tmp_path):
    _, fields, _, _, _ = make_services(tmp_path)
    field = fields.create_field(key="legacy_country", label="Legacy country")

    with pytest.raises(ValueError, match="governance"):
        fields.transition(field["id"], "merged", reason="manual")
    with pytest.raises(ValueError, match="governance"):
        fields.transition(field["id"], "split", reason="manual")
