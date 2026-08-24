from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


def make_services(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    fields = FieldService(db)
    entities = EntityService(db)
    views = ViewService(db)
    return db, fields, entities, views


def seed_small_dataset(tmp_path):
    db, fields, entities, views = make_services(tmp_path)
    for key, label in [
        ("title", "Title"),
        ("year", "Publication year"),
        ("verified", "Verified"),
        ("country", "Country"),
    ]:
        fields.create_field(key=key, label=label)
    p1 = entities.create_entity(label="AI Native Paper", kind="paper")
    p2 = entities.create_entity(label="Sparse Paper", kind="paper")
    entities.set_cell(p1["id"], "title", "Dynamic Field Databases")
    entities.set_cell(p1["id"], "year", 2026)
    entities.set_cell(p1["id"], "verified", False)
    entities.set_cell(p2["id"], "year", 2025)
    return db, fields, entities, views, p1, p2


def test_task_view_projects_selected_fields_without_copying_cells(tmp_path):
    db, _, _, views, p1, p2 = seed_small_dataset(tmp_path)
    before = db.scalar("SELECT COUNT(*) FROM cells")

    view = views.create_view("Audit", ["year", "verified", "country"])
    matrix = views.get_view_matrix(view["id"], field_offset=0, field_limit=10)

    assert [field["key"] for field in matrix["fields"]] == ["year", "verified", "country"]
    by_id = {row["id"]: row for row in matrix["rows"]}
    assert by_id[p1["id"]]["values"] == {"year": 2026, "verified": False}
    assert by_id[p2["id"]]["values"] == {"year": 2025}
    assert db.scalar("SELECT COUNT(*) FROM cells") == before


def test_matrix_field_window_slices_only_requested_columns(tmp_path):
    _, _, _, views, _, _ = seed_small_dataset(tmp_path)
    view = views.create_view("Window", ["title", "year", "verified", "country"])

    matrix = views.get_view_matrix(view["id"], field_offset=1, field_limit=2)

    assert matrix["total_fields"] == 4
    assert matrix["field_offset"] == 1
    assert [field["key"] for field in matrix["fields"]] == ["year", "verified"]
    assert all(set(row["values"]) <= {"year", "verified"} for row in matrix["rows"])


def test_search_finds_fields_entities_and_cell_text(tmp_path):
    _, _, _, views, _, _ = seed_small_dataset(tmp_path)

    field_results = views.search("Publication")
    entity_results = views.search("Sparse Paper")
    cell_results = views.search("Dynamic Field")

    assert any(item["type"] == "field" and item["key"] == "year" for item in field_results)
    assert any(item["type"] == "entity" and item["label"] == "Sparse Paper" for item in entity_results)
    assert any(item["type"] == "cell" and item["field_key"] == "title" for item in cell_results)


def test_stats_show_logical_width_and_sparse_density(tmp_path):
    db, fields, entities, views = make_services(tmp_path)
    fields.bulk_create_fields(
        {"key": f"f_{i:05d}", "label": f"Field {i:05d}"}
        for i in range(10_000)
    )
    entity = entities.create_entity(label="One sparse record")
    entities.set_cell(entity["id"], "f_00000", "only value")

    stats = views.stats()

    assert stats["fields"] == 10_000
    assert stats["active_fields"] == 10_000
    assert stats["entities"] == 1
    assert stats["cells"] == 1
    assert stats["logical_capacity"] == 10_000
    assert stats["density"] == 0.0001


def test_create_view_rejects_unknown_field(tmp_path):
    _, fields, _, views = make_services(tmp_path)
    fields.create_field(key="known", label="Known")

    try:
        views.create_view("Bad", ["known", "missing"])
    except KeyError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("unknown field was accepted")
