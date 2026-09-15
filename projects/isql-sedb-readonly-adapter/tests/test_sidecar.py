from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from isql_core.semantic_addressing import semantic_address_from_analysis
from isql_core.semantics import SemanticAnalysis, SemanticCoordinateSet
from isql_sedb_readonly import SEDBReadOnlyAdapter
from isql_sedb_readonly.active_domain import ActiveDomainBudget, plan_active_domain
from isql_sedb_readonly.materializer import materialize_partial_domain
from isql_sedb_readonly.sidecar import (
    ProofSidecar,
    build_proof_sidecar,
    verify_sidecar_proof_envelope,
)
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


def semantic(*concepts: str) -> SemanticAnalysis:
    return SemanticAnalysis(
        analyzer_id="sidecar-fixture",
        analyzer_contract="sidecar-contract-v1",
        coordinates=SemanticCoordinateSet(
            summary="fixture",
            concepts=tuple(concepts),
            entities=(),
            relations=(),
            claims=(),
            intent=None,
            uncertainty=(),
            tags=(),
            language="en",
        ),
    )


class ProofSidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "sedb.sqlite3"
        self.db = Database(self.db_path)
        self.fields = FieldService(self.db)
        self.entities = EntityService(self.db)
        self.views = ViewService(self.db)

        for key in ("topic", "nullable", "missing", "hidden"):
            self.fields.create_field(key=key, label=key.title(), value_type="json")

        self.entities.create_entity(label="Alpha", kind="record", entity_id="Entity-A")
        self.entities.create_entity(label="Beta", kind="record", entity_id="Entity-B")
        self.entities.set_cell(
            "Entity-A", "topic", {"name": "ISQL"}, source="fixture", confidence=0.9
        )
        self.entities.set_cell(
            "Entity-A", "nullable", None, source="fixture:blank", confidence=1.0
        )
        self.entities.set_cell(
            "Entity-A", "hidden", "secret-but-unloaded", source="fixture:hidden"
        )
        self.entities.set_cell(
            "Entity-B", "topic", {"name": "OTHER"}, source="fixture:beta", confidence=0.7
        )

        self.view = self.views.create_view(
            "sidecar-task",
            ["topic", "nullable", "missing", "hidden"],
        )
        self.adapter = SEDBReadOnlyAdapter(self.db_path)
        self.query = semantic_address_from_analysis(semantic("isql"))
        self._rebuild_query_state()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _rebuild_query_state(self) -> None:
        self.index = self.adapter.build_semantic_index({
            "Entity-A": semantic("isql"),
            "Entity-B": semantic("other"),
        })
        self.plan = plan_active_domain(
            self.adapter,
            self.query,
            self.index,
            view_id=self.view["id"],
            budget=ActiveDomainBudget(
                max_candidate_scan=4,
                max_entities=1,
                max_fields=3,
                max_cells=10,
            ),
        )
        self.projection = materialize_partial_domain(
            self.adapter,
            self.plan,
        ).projections[0]

    def _build(self, name: str = "proofs.sqlite3"):
        path = self.root / name
        result = build_proof_sidecar(self.adapter, path)
        return path, result, ProofSidecar(path)

    def test_sidecar_checkpoint_is_deterministic_for_same_source_state(self):
        _, first, _ = self._build("first.sqlite3")
        _, second, _ = self._build("second.sqlite3")
        self.assertEqual(first.checkpoint, second.checkpoint)
        self.assertEqual(first.checkpoint_sha256, second.checkpoint_sha256)
        self.assertEqual(first.entity_count, 2)
        self.assertEqual(first.field_count, 4)

    def test_sidecar_is_sqlite_valid_and_reader_is_query_only(self):
        path, _, sidecar = self._build()
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        with sidecar._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM entity_commitments")

    def test_sidecar_issues_and_verifies_after_source_database_is_removed(self):
        _, _, sidecar = self._build()
        self.db_path.unlink()
        envelope = sidecar.issue_projection(self.projection)
        self.assertTrue(verify_sidecar_proof_envelope(envelope))
        self.assertEqual(
            envelope.proof_bundle.entity_commitment.legacy_snapshot_sha256,
            self.projection.source_exact.state_sha256,
        )

    def test_read_stats_show_unloaded_field_never_touches_cell_proof_state(self):
        _, _, sidecar = self._build()
        envelope = sidecar.issue_projection(self.projection)
        # Four task-view fields are proven in the registry. Only the three selected
        # D2 fields touch the cell side; hidden is D3 `unloaded` and remains opaque.
        self.assertEqual(envelope.read_stats.field_leaf_reads, 4)
        self.assertEqual(envelope.read_stats.cell_leaf_reads, 3)
        self.assertEqual(envelope.read_stats.commitment_reads, 3)
        self.assertEqual(envelope.read_stats.node_hash_lookups, 8 * 256)

    def test_checkpoint_anchors_entity_commitment_and_field_registry_commitment(self):
        _, _, sidecar = self._build()
        envelope = sidecar.issue_projection(self.projection)
        self.assertTrue(verify_sidecar_proof_envelope(envelope))
        self.assertEqual(
            envelope.checkpoint.field_registry_commitment_sha256,
            envelope.proof_bundle.field_registry_commitment.commitment_sha256(),
        )
        self.assertEqual(
            envelope.entity_commitment_membership.payload,
            {
                "entity_commitment_sha256":
                    envelope.proof_bundle.entity_commitment.commitment_sha256()
            },
        )

    def test_tampered_checkpoint_entity_root_fails(self):
        _, _, sidecar = self._build()
        envelope = sidecar.issue_projection(self.projection)
        checkpoint = replace(envelope.checkpoint, entity_root_sha256="11" * 32)
        self.assertFalse(verify_sidecar_proof_envelope(replace(envelope, checkpoint=checkpoint)))

    def test_tampered_entity_commitment_membership_path_fails(self):
        _, _, sidecar = self._build()
        envelope = sidecar.issue_projection(self.projection)
        proof = envelope.entity_commitment_membership
        siblings = list(proof.siblings)
        siblings[0] = "22" * 32
        tampered = replace(proof, siblings=tuple(siblings))
        self.assertFalse(verify_sidecar_proof_envelope(
            replace(envelope, entity_commitment_membership=tampered)
        ))

    def test_old_sidecar_remains_historical_after_source_mutation(self):
        _, old_build, old_sidecar = self._build("old.sqlite3")
        old_envelope = old_sidecar.issue_projection(self.projection)
        self.assertTrue(verify_sidecar_proof_envelope(old_envelope))

        self.entities.set_cell(
            "Entity-A", "topic", {"name": "ISQL-v2"}, source="mutation", confidence=0.95
        )
        self._rebuild_query_state()

        # Historical sidecar still verifies its old proof, but refuses the new exact state.
        self.assertTrue(verify_sidecar_proof_envelope(old_envelope))
        with self.assertRaisesRegex(Exception, "SIDECAR_PROJECTION_LEGACY_HASH_MISMATCH"):
            old_sidecar.issue_projection(self.projection)

        _, new_build, new_sidecar = self._build("new.sqlite3")
        new_envelope = new_sidecar.issue_projection(self.projection)
        self.assertTrue(verify_sidecar_proof_envelope(new_envelope))
        self.assertNotEqual(old_build.checkpoint_sha256, new_build.checkpoint_sha256)

    def test_unrelated_global_field_changes_checkpoint_but_not_entity_commitment(self):
        _, before_build, before_sidecar = self._build("before.sqlite3")
        before = before_sidecar.issue_projection(self.projection)

        self.fields.create_field(
            key="unrelated-global-field",
            label="Unrelated",
            value_type="text",
        )
        _, after_build, after_sidecar = self._build("after.sqlite3")
        after = after_sidecar.issue_projection(self.projection)

        self.assertEqual(
            before.proof_bundle.entity_commitment,
            after.proof_bundle.entity_commitment,
        )
        self.assertNotEqual(
            before.proof_bundle.field_registry_commitment,
            after.proof_bundle.field_registry_commitment,
        )
        self.assertNotEqual(before_build.checkpoint_sha256, after_build.checkpoint_sha256)

    def test_existing_sidecar_requires_explicit_overwrite(self):
        path, first, _ = self._build()
        with self.assertRaises(FileExistsError):
            build_proof_sidecar(self.adapter, path)
        second = build_proof_sidecar(self.adapter, path, overwrite=True)
        self.assertEqual(first.checkpoint_sha256, second.checkpoint_sha256)

    def test_sidecar_path_cannot_overwrite_source_database(self):
        with self.assertRaisesRegex(Exception, "SIDECAR_PATH_MUST_DIFFER_FROM_SEDB"):
            build_proof_sidecar(self.adapter, self.db_path, overwrite=True)


if __name__ == "__main__":
    unittest.main()
