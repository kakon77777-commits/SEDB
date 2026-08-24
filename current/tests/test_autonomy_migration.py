import sqlite3

import pytest

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService


AUTONOMY_TABLES = {
    "autonomy_envelopes",
    "autonomy_constraint_snapshots",
    "autonomy_decisions",
    "autonomy_commit_receipts",
    "autonomy_commit_events",
    "autonomy_rollback_receipts",
}


def test_v04a_database_migrates_to_autonomy_schema_and_preserves_cells(tmp_path):
    path = tmp_path / "sedb.sqlite"
    db = Database(path)
    fields = FieldService(db)
    entities = EntityService(db)
    field = fields.create_field(key="signal", label="Signal")
    entity = entities.create_entity(label="Row 1", entity_id="row-1")
    entities.set_cell(entity["id"], field["id"], "kept", source="migration-test")

    # Re-open as a migration boundary.
    Database(path)

    with db.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        cell = conn.execute(
            "SELECT value_json FROM cells WHERE entity_id=? AND field_id=?",
            (entity["id"], field["id"]),
        ).fetchone()

    assert AUTONOMY_TABLES <= tables
    assert cell is not None
    assert cell[0] == '"kept"'


def test_decision_and_commit_receipts_are_sqlite_immutable(tmp_path):
    db = Database(tmp_path / "sedb.sqlite")
    now = "2026-08-23T00:00:00Z"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO autonomy_envelopes(
                id,name,version,contract_ref,authority_ref,rules_json,created_by,created_at
            ) VALUES('env','Local',1,'contract:test','authority:test','{}','test',?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO autonomy_constraint_snapshots(
                id,action_sha256,basis_sha256,constraints_json,methods_json,risk_json,created_at
            ) VALUES('cs','a','b','{}','[]','{}',?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO autonomy_decisions(
                id,action_type,action_json,properties_json,decision,reason_codes_json,summary,
                envelope_id,basis_sha256,constraint_snapshot_id,constraint_sha256,evidence_json,
                evaluator,created_at
            ) VALUES('d','x','{}','{}','EXECUTE','[]','ok','env','b','cs','c','{}','test',?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO autonomy_commit_receipts(
                id,decision_id,transaction_id,action_type,before_state_sha256,after_state_sha256,
                mutation_json,rollback_action_json,rollback_mode,envelope_id,constraint_snapshot_id,created_at
            ) VALUES('c','d','tx','x','before','after','{}','{}','none','env','cs',?)
            """,
            (now,),
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.connect() as conn:
            conn.execute("UPDATE autonomy_decisions SET summary='changed' WHERE id='d'")

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.connect() as conn:
            conn.execute("DELETE FROM autonomy_commit_receipts WHERE id='c'")
