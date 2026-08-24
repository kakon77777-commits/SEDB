import csv
import json

import pytest

from sedb.db import Database
from sedb.entities import EntityService
from sedb.exchange import ExchangeService
from sedb.fields import FieldService


def make_services(path):
    db = Database(path)
    return db, FieldService(db), EntityService(db), ExchangeService(db)


def seed(db_path):
    db, fields, entities, exchange = make_services(db_path)
    for key, value_type in [
        ("year", "integer"),
        ("verified", "boolean"),
        ("tags", "array"),
        ("note", "text"),
        ("nullable", "json"),
    ]:
        fields.create_field(key=key, label=key.title(), value_type=value_type)
    one = entities.create_entity(label="Paper One", kind="paper", entity_id="paper-1")
    two = entities.create_entity(label="Paper Two", kind="paper", entity_id="paper-2")
    entities.set_cell(one["id"], "year", 2026)
    entities.set_cell(one["id"], "verified", False)
    entities.set_cell(one["id"], "tags", ["AI", "SEDB"])
    entities.set_cell(one["id"], "nullable", None)
    entities.set_cell(two["id"], "note", "sparse")
    return db, fields, entities, exchange


def test_jsonl_round_trip_preserves_sparse_values_and_types(tmp_path):
    source_db, _, _, source_exchange = seed(tmp_path / "source.sqlite")
    out = tmp_path / "entities.jsonl"
    source_exchange.export_jsonl(out)

    target_db, _, target_entities, target_exchange = make_services(tmp_path / "target.sqlite")
    imported = target_exchange.import_jsonl(out, create_missing_fields=True)

    assert imported == 2
    one = target_entities.get_entity("paper-1")
    two = target_entities.get_entity("paper-2")
    assert one["values"] == {
        "nullable": None,
        "tags": ["AI", "SEDB"],
        "verified": False,
        "year": 2026,
    }
    assert two["values"] == {"note": "sparse"}
    assert target_db.scalar("SELECT COUNT(*) FROM cells") == 5
    assert target_db.scalar("SELECT COUNT(*) FROM fields") == 5


def test_csv_round_trip_keeps_empty_cells_absent(tmp_path):
    _, _, _, source_exchange = seed(tmp_path / "source.sqlite")
    out = tmp_path / "entities.csv"
    source_exchange.export_csv(out)

    target_db, _, target_entities, target_exchange = make_services(tmp_path / "target.sqlite")
    imported = target_exchange.import_csv(out, create_missing_fields=True)

    assert imported == 2
    assert target_entities.get_entity("paper-1")["values"]["verified"] is False
    assert "note" not in target_entities.get_entity("paper-1")["values"]
    assert target_entities.get_entity("paper-2")["values"] == {"note": "sparse"}
    assert target_db.scalar("SELECT COUNT(*) FROM cells") == 5


def test_csv_export_encodes_present_values_as_json_but_blank_as_empty(tmp_path):
    _, _, _, exchange = seed(tmp_path / "source.sqlite")
    out = tmp_path / "entities.csv"
    exchange.export_csv(out, field_keys=["year", "verified", "note"])

    with out.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    one = next(row for row in rows if row["id"] == "paper-1")
    two = next(row for row in rows if row["id"] == "paper-2")
    assert one["year"] == "2026"
    assert one["verified"] == "false"
    assert one["note"] == ""
    assert two["year"] == ""
    assert json.loads(two["note"]) == "sparse"


def test_import_rejects_missing_fields_when_creation_disabled(tmp_path):
    payload = tmp_path / "one.jsonl"
    payload.write_text(
        json.dumps({"id": "x", "kind": "record", "label": "X", "values": {"new_field": 1}}) + "\n",
        encoding="utf-8",
    )
    _, _, _, exchange = make_services(tmp_path / "target.sqlite")

    with pytest.raises(KeyError, match="new_field"):
        exchange.import_jsonl(payload, create_missing_fields=False)
