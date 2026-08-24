import sqlite3

from sedb.db import Database


def build_v01_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL DEFAULT 'record',
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE fields (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'text',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE cells (
            entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            field_id TEXT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
            value_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            confidence REAL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(entity_id, field_id)
        );
        CREATE TABLE field_proposals (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL,
            label TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'text',
            description TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            proposed_by TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        """
    )
    now = "2026-08-20T00:00:00Z"
    conn.execute(
        "INSERT INTO fields VALUES(?,?,?,?,?,?,?,?)",
        ("field-1", "Author-Country", "Author country", "text", "legacy", "active", now, now),
    )
    conn.execute(
        "INSERT INTO entities VALUES(?,?,?,?,?)",
        ("entity-1", "paper", "Paper 1", now, now),
    )
    conn.execute(
        "INSERT INTO cells VALUES(?,?,?,?,?,?)",
        ("entity-1", "field-1", '"Taiwan"', "legacy", 1.0, now),
    )
    conn.commit()
    conn.close()


def test_v01_database_forward_migrates_without_losing_ids_or_cells(tmp_path):
    path = tmp_path / "legacy-v01.sqlite"
    build_v01_database(path)

    db = Database(path)

    with db.connect() as conn:
        field_columns = {row[1] for row in conn.execute("PRAGMA table_info(fields)")}
        proposal_columns = {row[1] for row in conn.execute("PRAGMA table_info(field_proposals)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        field = conn.execute("SELECT * FROM fields WHERE id='field-1'").fetchone()
        cell = conn.execute(
            "SELECT entity_id,field_id,value_json FROM cells WHERE entity_id='entity-1' AND field_id='field-1'"
        ).fetchone()
        versions = conn.execute(
            "SELECT version,label,value_type,description FROM field_versions WHERE field_id='field-1' ORDER BY version"
        ).fetchall()

    assert {"namespace", "normalized_key"} <= field_columns
    assert "namespace" in proposal_columns
    assert {"field_aliases", "field_versions", "field_lineage", "proposal_decisions"} <= tables
    assert field["id"] == "field-1"
    assert field["namespace"] == "global"
    assert field["normalized_key"] == "author_country"
    assert tuple(cell) == ("entity-1", "field-1", '"Taiwan"')
    assert [tuple(row) for row in versions] == [(1, "Author country", "text", "legacy")]


def test_field_key_normalization_is_deterministic():
    import importlib

    naming = importlib.import_module("sedb.naming")

    assert naming.normalize_field_key("  Author-Country  ") == "author_country"
    assert naming.normalize_field_key("AUTHOR / COUNTRY") == "author_country"
    assert naming.normalize_field_key("Ａｕｔｈｏｒ．Ｃｏｕｎｔｒｙ") == "author_country"


def test_field_key_normalization_rejects_empty_result():
    import importlib

    naming = importlib.import_module("sedb.naming")

    import pytest
    with pytest.raises(ValueError, match="normalize"):
        naming.normalize_field_key("--- / ...")


def test_v02a_database_forward_migration_adds_semantic_candidate_tables(tmp_path):
    path = tmp_path / "legacy-v02a.sqlite"
    db = Database(path)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO fields(id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("field-a", "author_country", "Author country", "text", "", "active", "2026-08-20T00:00:00Z", "2026-08-20T00:00:00Z", "global", "author_country"),
        )
        conn.execute(
            "INSERT INTO entities(id,kind,label,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("entity-a", "paper", "Paper A", "2026-08-20T00:00:00Z", "2026-08-20T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO cells(entity_id,field_id,value_json,source,confidence,updated_at) VALUES(?,?,?,?,?,?)",
            ("entity-a", "field-a", '"Taiwan"', "legacy", 1.0, "2026-08-20T00:00:00Z"),
        )

    # Re-open through a fresh Database instance to exercise forward migration.
    migrated = Database(path)
    with migrated.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cell = conn.execute(
            "SELECT entity_id,field_id,value_json FROM cells WHERE entity_id='entity-a' AND field_id='field-a'"
        ).fetchone()

    assert {"semantic_candidates", "semantic_candidate_reviews", "field_relations"} <= tables
    assert tuple(cell) == ("entity-a", "field-a", '"Taiwan"')


def build_v02b_database(path):
    from sedb.db import GOVERNANCE_SCHEMA, SCHEMA, SEMANTIC_SCHEMA

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript(GOVERNANCE_SCHEMA)
    conn.executescript(SEMANTIC_SCHEMA)
    now = "2026-08-20T00:00:00Z"
    conn.execute(
        """
        INSERT INTO fields(
            id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        ("field-v02b", "legacy_signal", "Legacy signal", "text", "", "active", now, now, "global", "legacy_signal"),
    )
    conn.execute(
        "INSERT INTO entities(id,kind,label,created_at,updated_at) VALUES(?,?,?,?,?)",
        ("entity-v02b", "record", "Legacy row", now, now),
    )
    conn.execute(
        "INSERT INTO cells(entity_id,field_id,value_json,source,confidence,updated_at) VALUES(?,?,?,?,?,?)",
        ("entity-v02b", "field-v02b", '"x"', "legacy", 1.0, now),
    )
    conn.commit()
    conn.close()


def test_v02b_database_forward_migration_adds_utility_tables_without_data_loss(tmp_path):
    path = tmp_path / "legacy-v02b.sqlite"
    build_v02b_database(path)

    migrated = Database(path)
    with migrated.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cell = conn.execute(
            "SELECT entity_id,field_id,value_json FROM cells WHERE entity_id='entity-v02b' AND field_id='field-v02b'"
        ).fetchone()

    assert {"field_utility_assessments", "field_guardrails"} <= tables
    assert tuple(cell) == ("entity-v02b", "field-v02b", '"x"')


def test_field_utility_assessments_are_sqlite_immutable(tmp_path):
    path = tmp_path / "immutable.sqlite"
    db = Database(path)
    now = "2026-08-21T00:00:00Z"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO fields(
                id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            ("field-immutable", "immutable_field", "Immutable field", "text", "", "active", now, now, "global", "immutable_field"),
        )
        conn.execute(
            """
            INSERT INTO field_utility_assessments(
                id,field_id,policy_version,field_status,score,recommendation,reason,
                metrics_json,evidence_json,policy_json,basis_sha256,as_of,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "assessment-1", "field-immutable", "utility-v1", "active", 0.15,
                "review", "fixture", "{}", "{}", "{}", "abc", now, now,
            ),
        )

    import pytest
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE field_utility_assessments SET reason='changed' WHERE id='assessment-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM field_utility_assessments WHERE id='assessment-1'")
