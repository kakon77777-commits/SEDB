import sqlite3

import pytest

from sedb.db import Database, FAMILY_SCHEMA, GOVERNANCE_SCHEMA, SCHEMA, SEMANTIC_SCHEMA, UTILITY_SCHEMA


def build_v03b_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript(GOVERNANCE_SCHEMA)
    conn.executescript(SEMANTIC_SCHEMA)
    conn.executescript(UTILITY_SCHEMA)
    conn.executescript(FAMILY_SCHEMA)
    now = "2026-08-23T00:00:00Z"
    conn.execute(
        """
        INSERT INTO fields(
            id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        ("field-v03b", "legacy_signal", "Legacy signal", "text", "", "active", now, now, "global", "legacy_signal"),
    )
    conn.execute(
        "INSERT INTO entities(id,kind,label,created_at,updated_at) VALUES(?,?,?,?,?)",
        ("entity-v03b", "record", "Legacy row", now, now),
    )
    conn.execute(
        "INSERT INTO cells(entity_id,field_id,value_json,source,confidence,updated_at) VALUES(?,?,?,?,?,?)",
        ("entity-v03b", "field-v03b", '"x"', "legacy", 1.0, now),
    )
    conn.commit()
    conn.close()


def test_v03b_database_forward_migration_adds_agent_tables_without_data_loss(tmp_path):
    path = tmp_path / "legacy-v03b.sqlite"
    build_v03b_database(path)

    migrated = Database(path)
    with migrated.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cell = conn.execute(
            "SELECT entity_id,field_id,value_json FROM cells WHERE entity_id='entity-v03b' AND field_id='field-v03b'"
        ).fetchone()

    assert {
        "field_agent_runs",
        "field_agent_observations",
        "field_agent_actions",
        "field_agent_run_events",
    } <= tables
    assert tuple(cell) == ("entity-v03b", "field-v03b", '"x"')


def test_agent_observations_actions_and_events_are_sqlite_immutable(tmp_path):
    db = Database(tmp_path / "immutable-agent.sqlite")
    now = "2026-08-23T00:00:00Z"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO field_agent_runs(
                id,backend,namespace,policy_version,status,budget_json,counters_json,
                input_sha256,basis_sha256,evaluator,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("run-1", "deterministic", "global", "agent-v1", "created", "{}", "{}", "in", "basis", "test", now),
        )
        obs_id = conn.execute(
            """
            INSERT INTO field_agent_observations(run_id,ordinal,payload_json,payload_sha256,created_at)
            VALUES(?,?,?,?,?)
            """,
            ("run-1", 0, '{"x":1}', "obs", now),
        ).lastrowid
        action_id = conn.execute(
            """
            INSERT INTO field_agent_actions(
                run_id,ordinal,intent,capability_decision,outcome,input_json,output_json,
                reason,evidence_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            ("run-1", 0, "create_proposal", "ALLOWED", "created", "{}", "{}", "", "{}", now),
        ).lastrowid
        event_id = conn.execute(
            "INSERT INTO field_agent_run_events(run_id,event_type,detail_json,created_at) VALUES(?,?,?,?)",
            ("run-1", "created", "{}", now),
        ).lastrowid

    for table, row_id in [
        ("field_agent_observations", obs_id),
        ("field_agent_actions", action_id),
        ("field_agent_run_events", event_id),
    ]:
        with db.connect() as conn:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(f"UPDATE {table} SET created_at='changed' WHERE id=?", (row_id,))
        with db.connect() as conn:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
