import sqlite3

import pytest

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService


CAMPAIGN_TABLES = {
    "field_agent_campaigns",
    "field_agent_campaign_runs",
    "field_agent_work_items",
    "field_agent_work_claims",
    "field_agent_advisory_groups",
    "field_agent_advisory_group_members",
    "field_agent_consensus_packets",
    "field_agent_consensus_events",
}


def test_v03c_database_migrates_campaign_schema_without_losing_cells(tmp_path):
    path = tmp_path / "campaign.sqlite"
    db = Database(path)
    field = FieldService(db).create_field(key="paper", label="Paper")
    entity = EntityService(db).create_entity(label="P1")
    EntityService(db).set_cell(entity["id"], field["key"], "paper-1")

    # Re-opening is the migration boundary used by every release.
    Database(path)
    with db.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        value = conn.execute(
            "SELECT value_json FROM cells WHERE entity_id=? AND field_id=?",
            (entity["id"], field["id"]),
        ).fetchone()[0]

    assert CAMPAIGN_TABLES <= tables
    assert value == '"paper-1"'


def test_advisory_group_and_consensus_packet_are_sqlite_immutable(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO field_agent_campaigns(
                id,name,task_text,namespace,policy_version,status,budget_json,counters_json,
                basis_sha256,evaluator,created_at
            ) VALUES('c1','C','task','global','campaign-v1','created','{}','{}','basis','test','now')
            """
        )
        conn.execute(
            """
            INSERT INTO field_agent_advisory_groups(
                id,campaign_id,namespace,normalized_key,raw_support,independent_support,
                backend_count,evidence_root_count,conflict_count,basis_count,min_pair_score,
                avg_pair_score,metrics_json,evidence_json,created_at
            ) VALUES('g1','c1','global','new_signal',1,1,1,1,0,1,1.0,1.0,'{}','{}','now')
            """
        )
        conn.execute(
            """
            INSERT INTO field_agent_consensus_packets(
                id,campaign_id,group_id,policy_version,status,summary,metrics_json,evidence_json,
                basis_sha256,created_at
            ) VALUES('p1','c1','g1','consensus-v1','insufficient_independence','summary','{}','{}','basis','now')
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.connect() as conn:
            conn.execute("UPDATE field_agent_advisory_groups SET raw_support=2 WHERE id='g1'")

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.connect() as conn:
            conn.execute("DELETE FROM field_agent_consensus_packets WHERE id='p1'")
