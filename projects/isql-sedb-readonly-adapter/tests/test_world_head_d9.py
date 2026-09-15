import hashlib
import tempfile
import unittest
from pathlib import Path

from isql_sedb_readonly.history import CheckpointHistoryLedger
from isql_sedb_readonly.sidecar import ProofSidecarCheckpoint
from isql_sedb_readonly.world_head import build_world_head_manifest, verify_world_head_manifest

try:
    from isql_dsr.branch import NativeBranch
    from isql_dsr.branch_history import BranchHistoryLedger
    from isql_dsr.canonical import state_hash
    from isql_dsr.events import TransitionEvent
    from isql_dsr.machine import compile_registered_state, registered_state_hash
    from isql_dsr.model import PointValue, SemanticState, SpectrumAxis, TypedRelation
    from isql_dsr.registry import NativeSymbolRegistry, SymbolNamespace, extend_registry_for_events, extend_registry_for_state
    from isql_dsr.runtime import apply_event
    from isql_dsr.stream import build_event_stream
except ModuleNotFoundError as exc:
    if exc.name == "isql_dsr" or (exc.name or "").startswith("isql_dsr."):
        raise unittest.SkipTest("D9 cross-repo tests require merged ISQL-DSP") from exc
    raise


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class WorldHeadD9Tests(unittest.TestCase):
    def _reservoir(self, root: Path):
        ledger = CheckpointHistoryLedger(root / "reservoir.sqlite3", create=True)
        c1 = ProofSidecarCheckpoint(
            field_registry_commitment_sha256=_sha("field-1"),
            entity_root_sha256=_sha("entity-1"),
            entity_count=2,
        )
        r1 = ledger.append(
            c1,
            stream_id="world:alpha",
            observed_at="2026-09-15T08:00:00Z",
            authority_ref="authority:local",
            expected_head_sha256=None,
            note="initial",
        )
        return ledger, r1

    def _dsr(self, root: Path):
        base = SemanticState(identity="obj:world-alpha")
        left1 = TransitionEvent(
            event_id="left-1",
            operation="upsert_axis",
            payload={"axis": SpectrumAxis("risk", "ordinal", PointValue(1)).to_dict()},
            base_revision=0,
            previous_hash=state_hash(base),
        )
        left_state = apply_event(base, left1).state
        left2 = TransitionEvent(
            event_id="left-2",
            operation="set_context",
            payload={"context": {"phase": "two"}},
            base_revision=1,
            previous_hash=state_hash(left_state),
        )
        right1 = TransitionEvent(
            event_id="right-1",
            operation="upsert_relation",
            payload={"relation": TypedRelation("a", "supports", "b").to_dict()},
            base_revision=0,
            previous_hash=state_hash(base),
        )

        reg = extend_registry_for_state(NativeSymbolRegistry(), base)
        for event in (left1, left2, right1):
            reg = extend_registry_for_events(reg, (event,))
        reg, left_ref = reg.intern_text(SymbolNamespace.BRANCH_ID, "left")
        reg, right_ref = reg.intern_text(SymbolNamespace.BRANCH_ID, "right")
        native_base = compile_registered_state(base, reg)
        base_hash = registered_state_hash(native_base)

        left_v1 = NativeBranch(left_ref, 0, base_hash, build_event_stream(base, (left1,), reg))
        left_v2 = NativeBranch(left_ref, 0, base_hash, build_event_stream(base, (left1, left2), reg))
        right = NativeBranch(right_ref, 0, base_hash, build_event_stream(base, (right1,), reg))

        ledger = BranchHistoryLedger(root / "dsr.sqlite3")
        left_receipt = ledger.publish_branch(native_base, left_v1, reg, expected_head_sha256=None)
        right_receipt = ledger.publish_branch(native_base, right, reg, expected_head_sha256=None)
        return ledger, native_base, reg, left_v1, left_v2, right, left_receipt, right_receipt

    def test_current_manifest_requires_both_domains_current(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reservoir, rr = self._reservoir(root)
            dsr, _, _, left, _, _, left_receipt, _ = self._dsr(root)
            manifest = build_world_head_manifest(
                world_id="world:alpha",
                reservoir_record=rr,
                dsr_record=left_receipt.record,
            )
            verification = verify_world_head_manifest(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256(),
                reservoir_ledger=reservoir,
                dsr_ledger=dsr,
            )
            self.assertTrue(verification.valid)
            self.assertTrue(verification.current)
            self.assertTrue(verification.reservoir_is_head)
            self.assertTrue(verification.dsr_is_current)
            self.assertEqual(manifest.dsr_branch_ref, left.branch_ref)

    def test_reservoir_advance_makes_manifest_historical_not_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reservoir, rr = self._reservoir(root)
            dsr, _, _, _, _, _, left_receipt, _ = self._dsr(root)
            manifest = build_world_head_manifest(world_id="world:alpha", reservoir_record=rr, dsr_record=left_receipt.record)

            c2 = ProofSidecarCheckpoint(
                field_registry_commitment_sha256=_sha("field-2"),
                entity_root_sha256=_sha("entity-2"),
                entity_count=3,
            )
            reservoir.append(
                c2,
                stream_id=rr.stream_id,
                observed_at="2026-09-15T08:01:00Z",
                authority_ref="authority:local",
                expected_head_sha256=rr.record_sha256(),
                note="next",
            )
            verification = verify_world_head_manifest(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256(),
                reservoir_ledger=reservoir,
                dsr_ledger=dsr,
            )
            self.assertTrue(verification.valid)
            self.assertFalse(verification.current)
            self.assertTrue(verification.reservoir_record_valid)
            self.assertFalse(verification.reservoir_is_head)
            self.assertTrue(verification.dsr_is_current)

    def test_dsr_advance_makes_manifest_historical_not_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reservoir, rr = self._reservoir(root)
            dsr, base, reg, _, left_v2, _, left_receipt, _ = self._dsr(root)
            manifest = build_world_head_manifest(world_id="world:alpha", reservoir_record=rr, dsr_record=left_receipt.record)

            dsr.publish_branch(
                base,
                left_v2,
                reg,
                expected_head_sha256=left_receipt.record.record_sha256,
            )
            verification = verify_world_head_manifest(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256(),
                reservoir_ledger=reservoir,
                dsr_ledger=dsr,
            )
            self.assertTrue(verification.valid)
            self.assertFalse(verification.current)
            self.assertTrue(verification.reservoir_is_head)
            self.assertTrue(verification.dsr_record_valid)
            self.assertFalse(verification.dsr_is_current)

    def test_merge_manifest_tracks_all_source_heads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reservoir, rr = self._reservoir(root)
            dsr, base, reg, _, left_v2, right, left_receipt, right_receipt = self._dsr(root)
            merge = dsr.merge_current_heads(
                base,
                (left_receipt.branch.branch_ref, right.branch_ref),
                reg,
                expected_heads={
                    left_receipt.branch.branch_ref: left_receipt.record.record_sha256,
                    right.branch_ref: right_receipt.record.record_sha256,
                },
            )
            manifest = build_world_head_manifest(world_id="world:alpha", reservoir_record=rr, dsr_record=merge.record)
            verification = verify_world_head_manifest(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256(),
                reservoir_ledger=reservoir,
                dsr_ledger=dsr,
            )
            self.assertTrue(verification.current)
            self.assertEqual(manifest.dsr_source_branch_refs, merge.record.source_branch_refs)
            self.assertEqual(manifest.dsr_source_head_sha256s, merge.record.source_head_sha256s)

            dsr.publish_branch(
                base,
                left_v2,
                reg,
                expected_head_sha256=left_receipt.record.record_sha256,
            )
            stale = verify_world_head_manifest(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256(),
                reservoir_ledger=reservoir,
                dsr_ledger=dsr,
            )
            self.assertTrue(stale.valid)
            self.assertFalse(stale.current)
            self.assertFalse(stale.dsr_is_current)

    def test_wrong_manifest_hash_fails_without_erasing_record_validity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reservoir, rr = self._reservoir(root)
            dsr, _, _, _, _, _, left_receipt, _ = self._dsr(root)
            manifest = build_world_head_manifest(world_id="world:alpha", reservoir_record=rr, dsr_record=left_receipt.record)
            verification = verify_world_head_manifest(
                manifest,
                expected_manifest_sha256="0" * 64,
                reservoir_ledger=reservoir,
                dsr_ledger=dsr,
            )
            self.assertFalse(verification.valid)
            self.assertFalse(verification.current)
            self.assertFalse(verification.manifest_hash_valid)
            self.assertTrue(verification.reservoir_record_valid)
            self.assertTrue(verification.dsr_record_valid)


if __name__ == "__main__":
    unittest.main()
