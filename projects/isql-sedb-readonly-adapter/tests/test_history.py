from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from isql_core.semantic_addressing import semantic_address_from_analysis
from isql_core.semantics import SemanticAnalysis, SemanticCoordinateSet
from isql_sedb_readonly import SEDBReadOnlyAdapter
from isql_sedb_readonly.active_domain import ActiveDomainBudget, plan_active_domain
from isql_sedb_readonly.history import (
    CheckpointHistoryConflict,
    CheckpointHistoryLedger,
    verify_sidecar_envelope_at_head,
)
from isql_sedb_readonly.materializer import materialize_partial_domain
from isql_sedb_readonly.sidecar import ProofSidecar, build_proof_sidecar
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


def semantic(*concepts: str) -> SemanticAnalysis:
    return SemanticAnalysis(
        analyzer_id="history-fixture",
        analyzer_contract="history-contract-v1",
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


class CheckpointHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "sedb.sqlite3"
        self.db = Database(self.db_path)
        self.fields = FieldService(self.db)
        self.entities = EntityService(self.db)
        self.views = ViewService(self.db)

        for key in ("topic", "missing", "hidden"):
            self.fields.create_field(key=key, label=key.title(), value_type="json")
        self.entities.create_entity(label="Alpha", kind="record", entity_id="Entity-A")
        self.entities.set_cell(
            "Entity-A", "topic", {"name": "ISQL"}, source="fixture", confidence=0.9
        )
        self.entities.set_cell(
            "Entity-A", "hidden", "unloaded-value", source="fixture:hidden"
        )
        self.view = self.views.create_view("history-task", ["topic", "missing", "hidden"])
        self.adapter = SEDBReadOnlyAdapter(self.db_path)
        self.query = semantic_address_from_analysis(semantic("isql"))
        self._refresh_projection()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _refresh_projection(self) -> None:
        index = self.adapter.build_semantic_index({"Entity-A": semantic("isql")})
        plan = plan_active_domain(
            self.adapter,
            self.query,
            index,
            view_id=self.view["id"],
            budget=ActiveDomainBudget(
                max_candidate_scan=4,
                max_entities=1,
                max_fields=2,
                max_cells=10,
            ),
        )
        self.projection = materialize_partial_domain(
            self.adapter,
            plan,
        ).projections[0]

    def _sidecar(self, name: str):
        path = self.root / name
        build = build_proof_sidecar(self.adapter, path)
        sidecar = ProofSidecar(path)
        envelope = sidecar.issue_projection(self.projection)
        return build, sidecar, envelope

    def test_genesis_and_second_append_form_hash_chain(self):
        old_build, _, _ = self._sidecar("old.sqlite3")
        ledger = CheckpointHistoryLedger(self.root / "history.sqlite3", create=True)
        first = ledger.append(
            old_build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T08:00:00+08:00",
            authority_ref="Authority/Main",
            expected_head_sha256=None,
            note="genesis",
        )
        self.assertEqual(first.sequence, 0)
        self.assertIsNone(first.parent_record_sha256)
        self.assertEqual(first.observed_at, "2026-09-15T00:00:00.000000Z")
        self.assertEqual(first.authority_ref, "Authority/Main")

        self.entities.set_cell(
            "Entity-A", "topic", {"name": "ISQL-v2"}, source="mutation", confidence=0.95
        )
        self._refresh_projection()
        new_build, _, _ = self._sidecar("new.sqlite3")
        second = ledger.append(
            new_build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T00:01:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=first.record_sha256(),
            note="next state",
        )
        self.assertEqual(second.sequence, 1)
        self.assertEqual(second.parent_record_sha256, first.record_sha256())
        verification = ledger.verify_stream("world/main")
        self.assertTrue(verification.valid)
        self.assertEqual(verification.record_count, 2)
        self.assertEqual(verification.head_record_sha256, second.record_sha256())
        self.assertEqual(verification.head_checkpoint_sha256, new_build.checkpoint_sha256)

    def test_stale_expected_head_fails_closed(self):
        build, _, _ = self._sidecar("proofs.sqlite3")
        ledger = CheckpointHistoryLedger(self.root / "history.sqlite3", create=True)
        first = ledger.append(
            build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T00:00:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=None,
        )
        with self.assertRaises(CheckpointHistoryConflict):
            ledger.append(
                build.checkpoint,
                stream_id="world/main",
                observed_at="2026-09-15T00:01:00Z",
                authority_ref="Authority/Main",
                expected_head_sha256="00" * 32,
            )
        self.assertEqual(ledger.head("world/main").record_sha256(), first.record_sha256())

    def test_genesis_rejects_non_null_expected_head(self):
        build, _, _ = self._sidecar("proofs.sqlite3")
        ledger = CheckpointHistoryLedger(self.root / "history.sqlite3", create=True)
        with self.assertRaises(CheckpointHistoryConflict):
            ledger.append(
                build.checkpoint,
                stream_id="world/new",
                observed_at="2026-09-15T00:00:00Z",
                authority_ref="Authority/Main",
                expected_head_sha256="00" * 32,
            )

    def test_streams_have_independent_heads_and_identity_text_is_case_sensitive(self):
        build, _, _ = self._sidecar("proofs.sqlite3")
        ledger = CheckpointHistoryLedger(self.root / "history.sqlite3", create=True)
        main = ledger.append(
            build.checkpoint,
            stream_id="World/Main",
            observed_at="2026-09-15T00:00:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=None,
        )
        alt = ledger.append(
            build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T00:00:00Z",
            authority_ref="authority/main",
            expected_head_sha256=None,
        )
        self.assertNotEqual(main.record_sha256(), alt.record_sha256())
        self.assertEqual(ledger.head("World/Main").authority_ref, "Authority/Main")
        self.assertEqual(ledger.head("world/main").authority_ref, "authority/main")

    def test_append_only_triggers_reject_update_and_delete(self):
        build, _, _ = self._sidecar("proofs.sqlite3")
        ledger = CheckpointHistoryLedger(self.root / "history.sqlite3", create=True)
        ledger.append(
            build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T00:00:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=None,
        )
        with ledger._connect() as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE checkpoint_records SET checkpoint_sha256=?", ("00" * 32,))
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM checkpoint_records")

    def test_hash_chain_verifier_detects_offline_record_tampering(self):
        build, _, _ = self._sidecar("proofs.sqlite3")
        ledger = CheckpointHistoryLedger(self.root / "history.sqlite3", create=True)
        ledger.append(
            build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T00:00:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=None,
        )
        with sqlite3.connect(ledger.path) as conn:
            conn.execute("DROP TRIGGER checkpoint_records_no_update")
            conn.execute("UPDATE checkpoint_records SET record_json='{}' WHERE sequence=0")
        verification = ledger.verify_stream("world/main")
        self.assertFalse(verification.valid)

    def test_same_logical_genesis_has_same_record_hash_across_ledgers(self):
        build, _, _ = self._sidecar("proofs.sqlite3")
        left = CheckpointHistoryLedger(self.root / "left.sqlite3", create=True)
        right = CheckpointHistoryLedger(self.root / "right.sqlite3", create=True)
        kwargs = dict(
            stream_id="world/main",
            observed_at="2026-09-15T00:00:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=None,
            note="same",
        )
        a = left.append(build.checkpoint, **kwargs)
        b = right.append(build.checkpoint, **kwargs)
        self.assertEqual(a, b)
        self.assertEqual(a.record_sha256(), b.record_sha256())

    def test_old_proof_remains_valid_but_ceases_to_be_current_head(self):
        old_build, _, old_envelope = self._sidecar("old.sqlite3")
        ledger = CheckpointHistoryLedger(self.root / "history.sqlite3", create=True)
        first = ledger.append(
            old_build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T00:00:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=None,
        )
        old_at_head = verify_sidecar_envelope_at_head(
            old_envelope,
            ledger,
            stream_id="world/main",
        )
        self.assertTrue(old_at_head.valid)

        self.entities.set_cell(
            "Entity-A", "topic", {"name": "ISQL-v2"}, source="mutation", confidence=0.95
        )
        self._refresh_projection()
        new_build, _, new_envelope = self._sidecar("new.sqlite3")
        second = ledger.append(
            new_build.checkpoint,
            stream_id="world/main",
            observed_at="2026-09-15T00:01:00Z",
            authority_ref="Authority/Main",
            expected_head_sha256=first.record_sha256(),
        )

        old_after = verify_sidecar_envelope_at_head(
            old_envelope,
            ledger,
            stream_id="world/main",
        )
        self.assertTrue(old_after.chain_valid)
        self.assertTrue(old_after.proof_valid)
        self.assertFalse(old_after.checkpoint_is_head)
        self.assertFalse(old_after.valid)

        new_after = verify_sidecar_envelope_at_head(
            new_envelope,
            ledger,
            stream_id="world/main",
        )
        self.assertTrue(new_after.valid)
        self.assertEqual(new_after.head_record_sha256, second.record_sha256())
        self.assertEqual(new_after.authority_ref, "Authority/Main")

    def test_history_file_requires_explicit_overwrite(self):
        path = self.root / "history.sqlite3"
        CheckpointHistoryLedger(path, create=True)
        with self.assertRaises(FileExistsError):
            CheckpointHistoryLedger(path, create=True)
        replacement = CheckpointHistoryLedger(path, create=True, overwrite=True)
        self.assertTrue(replacement.verify_stream("world/main").valid)
        self.assertEqual(replacement.verify_stream("world/main").record_count, 0)


if __name__ == "__main__":
    unittest.main()
