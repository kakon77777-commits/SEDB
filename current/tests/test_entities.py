from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService


def make_services(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    fields = FieldService(db)
    entities = EntityService(db)
    return db, fields, entities


def test_create_and_list_entity(tmp_path):
    _, _, entities = make_services(tmp_path)
    entity = entities.create_entity(label="Paper 001", kind="paper")

    assert entity["label"] == "Paper 001"
    assert entity["kind"] == "paper"
    listed = entities.list_entities()
    assert [item["id"] for item in listed] == [entity["id"]]


def test_missing_cell_is_blank_by_absence(tmp_path):
    db, fields, entities = make_services(tmp_path)
    fields.create_field(key="year", label="Year", value_type="integer")
    entity = entities.create_entity(label="Paper 001")

    loaded = entities.get_entity(entity["id"])

    assert loaded["values"] == {}
    assert db.scalar("SELECT COUNT(*) FROM cells") == 0


def test_sparse_cells_preserve_json_value_types(tmp_path):
    db, fields, entities = make_services(tmp_path)
    for key, value_type in [
        ("year", "integer"),
        ("verified", "boolean"),
        ("tags", "array"),
        ("meta", "object"),
        ("nullable", "json"),
    ]:
        fields.create_field(key=key, label=key.title(), value_type=value_type)
    entity = entities.create_entity(label="Paper 001")

    entities.set_cell(entity["id"], "year", 2026, source="manual", confidence=1.0)
    entities.set_cell(entity["id"], "verified", False)
    entities.set_cell(entity["id"], "tags", ["AI", "database"])
    entities.set_cell(entity["id"], "meta", {"rank": 3})
    entities.set_cell(entity["id"], "nullable", None)

    loaded = entities.get_entity(entity["id"])
    assert loaded["values"] == {
        "meta": {"rank": 3},
        "nullable": None,
        "tags": ["AI", "database"],
        "verified": False,
        "year": 2026,
    }
    assert loaded["cells"]["year"]["source"] == "manual"
    assert loaded["cells"]["year"]["confidence"] == 1.0
    assert db.scalar("SELECT COUNT(*) FROM cells") == 5


def test_set_cell_upserts_without_creating_duplicate_cell(tmp_path):
    db, fields, entities = make_services(tmp_path)
    fields.create_field(key="year", label="Year")
    entity = entities.create_entity(label="Paper 001")

    entities.set_cell(entity["id"], "year", 2025)
    entities.set_cell(entity["id"], "year", 2026, source="revision")

    assert entities.get_entity(entity["id"])["values"]["year"] == 2026
    assert entities.get_entity(entity["id"])["cells"]["year"]["source"] == "revision"
    assert db.scalar("SELECT COUNT(*) FROM cells") == 1


def test_delete_cell_restores_blank_state(tmp_path):
    db, fields, entities = make_services(tmp_path)
    fields.create_field(key="country", label="Country")
    entity = entities.create_entity(label="Researcher")
    entities.set_cell(entity["id"], "country", "Taiwan")

    deleted = entities.delete_cell(entity["id"], "country")

    assert deleted is True
    assert entities.get_entity(entity["id"])["values"] == {}
    assert db.scalar("SELECT COUNT(*) FROM cells") == 0
    assert entities.delete_cell(entity["id"], "country") is False


def test_unknown_entity_or_field_is_rejected(tmp_path):
    _, fields, entities = make_services(tmp_path)
    entity = entities.create_entity(label="Paper")

    try:
        entities.set_cell(entity["id"], "missing_field", "x")
    except KeyError as exc:
        assert "field not found" in str(exc)
    else:
        raise AssertionError("missing field was accepted")

    fields.create_field(key="known", label="Known")
    try:
        entities.set_cell("missing_entity", "known", "x")
    except KeyError as exc:
        assert "entity not found" in str(exc)
    else:
        raise AssertionError("missing entity was accepted")
