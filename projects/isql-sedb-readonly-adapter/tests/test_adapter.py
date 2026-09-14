from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from isql_core.semantic_addressing import semantic_address_from_analysis
from isql_core.semantics import SemanticAnalysis, SemanticCoordinateSet
from isql_sedb_readonly import (
    SEDBExactStateMismatch,
    SEDBReadOnlyAdapter,
)
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService


def semantic(*concepts: str) -> SemanticAnalysis:
    return SemanticAnalysis(
        analyzer_id="fixture-analyzer",
        analyzer_contract="fixture-contract-v1",
        coordinates=SemanticCoordinateSet(
            summary="fixture",
            concepts=tuple(concepts),
            entities=(),
            relations=(),
            claims=(),
            intent="retrieve state",
            uncertainty=(),
            tags=("sedb",),
            language="en",
        ),
    )


class ISQLSEDBReadOnlyAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "sedb.sqlite3"
        self.db = Database(self.db_path)
        self.fields = FieldService(self.db)
        self.entities = EntityService(self.db)

        topic = self.fields.create_field(
            key="topic",
            label="Topic",
            value_type="object",
            description="Semantic topic payload.",
            namespace="research",
        )
        score = self.fields.create_field(
            key="score",
            label="Score",
            value_type="number",
            description="Fixture score.",
            namespace="research",
        )
        self.topic_field_id = topic["id"]
        self.score_field_id = score["id"]

        self.entities.create_entity(label="Alpha", kind="paper", entity_id="Entity-A")
        self.entities.create_entity(label="Beta", kind="paper", entity_id="Entity-B")
        self.entities.set_cell(
            "Entity-A",
            "topic",
            {"name": "ISQL", "phase": 2},
            source="fixture:alpha",
            confidence=0.95,
        )
        self.entities.set_cell(
            "Entity-A",
            "score",
            0.9,
            source="fixture:alpha",
            confidence=1.0,
        )
        self.entities.set_cell(
            "Entity-B",
            "topic",
            {"name": "Other", "phase": 1},
            source="fixture:beta",
            confidence=0.8,
        )
        self.adapter = SEDBReadOnlyAdapter(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_is_deterministic_and_contains_stable_field_binding(self):
        first = self.adapter.read_entity_snapshot("Entity-A")
        second = self.adapter.read_entity_snapshot("Entity-A")
        self.assertEqual(first, second)
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())
        self.assertEqual(first.sha256(), second.sha256())

        payload = first.to_dict()
        self.assertEqual(payload["entity"]["id"], "Entity-A")
        field_ids = {cell["field"]["field_id"] for cell in payload["cells"]}
        self.assertEqual(field_ids, {self.topic_field_id, self.score_field_id})
        topic = next(cell for cell in payload["cells"] if cell["field"]["field_id"] == self.topic_field_id)
        self.assertEqual(topic["field"]["key"], "topic")
        self.assertEqual(topic["field"]["namespace"], "research")
        self.assertEqual(topic["source"], "fixture:alpha")
        self.assertEqual(topic["confidence"], 0.95)

    def test_adapter_connection_is_query_only(self):
        with self.adapter._connect() as conn:
            query_only = conn.execute("PRAGMA query_only").fetchone()[0]
            self.assertEqual(query_only, 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM entities WHERE id='Entity-A'")
        self.assertEqual(self.entities.get_entity("Entity-A")["id"], "Entity-A")

    def test_entity_ids_are_listed_deterministically(self):
        self.assertEqual(self.adapter.list_entity_ids(), ("Entity-A", "Entity-B"))
        self.assertEqual(self.adapter.list_entity_ids(limit=1, offset=1), ("Entity-B",))

    def test_missing_entity_fails_closed(self):
        with self.assertRaises(KeyError):
            self.adapter.read_entity_snapshot("missing")

    def test_end_to_end_semantic_candidate_to_verified_sedb_read(self):
        analyses = {
            "Entity-A": semantic("isql", "semantic-memory"),
            "Entity-B": semantic("unrelated"),
        }
        index = self.adapter.build_semantic_index(analyses)
        query = semantic_address_from_analysis(semantic("isql", "semantic-memory"))

        result, verified = self.adapter.resolve_and_read_verified(query, index, top_k=1)
        self.assertEqual(result.probe_count, 1)
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].candidate.exact.entity_id, "Entity-A")
        self.assertEqual(verified[0].snapshot.entity_id, "Entity-A")
        self.assertEqual(
            verified[0].candidate.exact.state_sha256,
            verified[0].snapshot.sha256(),
        )

    def test_stale_semantic_index_fails_exact_verification_after_sedb_mutation(self):
        analyses = {"Entity-A": semantic("isql")}
        index = self.adapter.build_semantic_index(analyses)
        query = semantic_address_from_analysis(semantic("isql"))
        result = self.adapter.resolve_and_read_verified(query, index, top_k=1)[0]
        exact = result.candidates[0].exact

        before = self.adapter.read_current_exact(exact)
        self.entities.set_cell(
            "Entity-A",
            "topic",
            {"name": "ISQL", "phase": 3},
            source="fixture:alpha-updated",
            confidence=0.97,
        )
        after = self.adapter.read_entity_snapshot("Entity-A")
        self.assertNotEqual(before.sha256(), after.sha256())
        with self.assertRaises(SEDBExactStateMismatch):
            self.adapter.read_current_exact(exact)

    def test_provenance_change_changes_exact_snapshot_even_when_value_is_same(self):
        before = self.adapter.read_entity_snapshot("Entity-B")
        self.entities.set_cell(
            "Entity-B",
            "topic",
            {"name": "Other", "phase": 1},
            source="fixture:beta-new-source",
            confidence=0.8,
        )
        after = self.adapter.read_entity_snapshot("Entity-B")
        self.assertNotEqual(before.sha256(), after.sha256())

    def test_semantic_index_contains_adapter_snapshot_hash_not_jsonl_projection_hash(self):
        index = self.adapter.build_semantic_index({"Entity-A": semantic("isql")})
        snapshot = self.adapter.read_entity_snapshot("Entity-A")
        self.assertEqual(index.entries[0].exact.entity_id, "Entity-A")
        self.assertEqual(index.entries[0].exact.state_sha256, snapshot.sha256())


if __name__ == "__main__":
    unittest.main()
