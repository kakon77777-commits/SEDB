from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from isql_core.semantic_addressing import SemanticProfileBinding
from isql_sedb_readonly.world_head import WorldHeadManifest
from isql_world_materializer import (
    LocalDirectoryProvider,
    MaterializationError,
    MaterializationRangeReader,
    PhysicalPlacementResolver,
    PlacementCatalog,
    PlacementRecord,
    RangeProofIndex,
    VerifiedRangeFetcher,
    build_materialization_manifest,
    build_range_proof_sidecar,
    verify_materialization_manifest,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _world_head() -> WorldHeadManifest:
    return WorldHeadManifest(
        world_id="world:alpha",
        reservoir_stream_id="world:alpha",
        reservoir_sequence=3,
        reservoir_record_sha256=_sha("reservoir-record"),
        reservoir_checkpoint_sha256=_sha("reservoir-checkpoint"),
        dsr_record_sha256=_sha("dsr-record"),
        dsr_record_kind="branch_head",
        dsr_base_revision=0,
        dsr_base_hash=_sha("dsr-base"),
        dsr_result_state_hash=_sha("dsr-state"),
        dsr_branch_ref=7,
        dsr_source_branch_refs=(),
        dsr_source_head_sha256s=(),
    )


class D13MaterializationManifestTests(unittest.TestCase):
    def _commitment(self, root: Path, name: str, content: bytes, chunk_size: int):
        source = root / f"{name}.source"
        sidecar = root / f"{name}.range.sqlite3"
        source.write_bytes(content)
        from isql_world_materializer import ExactContentIdentity
        identity = ExactContentIdentity("sha256", hashlib.sha256(content).hexdigest())
        commitment = build_range_proof_sidecar(source, sidecar, identity, chunk_size=chunk_size)
        return sidecar, commitment

    def test_manifest_binds_real_d9_world_head_and_real_isql_dependency(self):
        profile = SemanticProfileBinding("analyzer:test", 1, _sha("contract"))
        self.assertEqual(profile.analyzer_id, "analyzer:test")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a_sidecar, a = self._commitment(root, "a", b"A" * 32, 8)
            z_sidecar, z = self._commitment(root, "z", b"Z" * 48, 16)
            world = _world_head()
            manifest = build_materialization_manifest(
                world_id=world.world_id,
                world_head_manifest_sha256=world.manifest_sha256(),
                profile_id="materialization:desktop-v1",
                commitments={"asset:z": z, "asset:a": a},
            )
            self.assertEqual([b.artifact_ref for b in manifest.artifacts], ["asset:a", "asset:z"])
            verification = verify_materialization_manifest(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256,
                expected_world_head_manifest_sha256=world.manifest_sha256(),
                proof_indexes={"asset:a": RangeProofIndex(a_sidecar), "asset:z": RangeProofIndex(z_sidecar)},
            )
            self.assertTrue(verification.valid)

    def test_manifest_identity_is_input_order_independent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, a = self._commitment(root, "a", b"alpha" * 8, 8)
            _, b = self._commitment(root, "b", b"beta" * 8, 8)
            world_hash = _world_head().manifest_sha256()
            m1 = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"b": b, "a": a})
            m2 = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"a": a, "b": b})
            self.assertEqual(m1.manifest_sha256, m2.manifest_sha256)

    def test_extra_local_proof_cache_does_not_invalidate_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a_sidecar, a = self._commitment(root, "a", b"A" * 24, 8)
            extra_sidecar, _ = self._commitment(root, "extra", b"E" * 24, 8)
            world_hash = _world_head().manifest_sha256()
            manifest = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"asset:a": a})
            verification = verify_materialization_manifest(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256,
                expected_world_head_manifest_sha256=world_hash,
                proof_indexes={"asset:a": RangeProofIndex(a_sidecar), "cached:other": RangeProofIndex(extra_sidecar)},
            )
            self.assertTrue(verification.valid)

    def test_hash_and_world_head_failures_are_separate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sidecar, commitment = self._commitment(root, "a", b"A" * 24, 8)
            world_hash = _world_head().manifest_sha256()
            manifest = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"asset:a": commitment})
            wrong_manifest = verify_materialization_manifest(manifest, expected_manifest_sha256="0" * 64, expected_world_head_manifest_sha256=world_hash, proof_indexes={"asset:a": RangeProofIndex(sidecar)})
            self.assertFalse(wrong_manifest.manifest_hash_valid)
            self.assertTrue(wrong_manifest.world_head_binding_valid)
            wrong_world = verify_materialization_manifest(manifest, expected_manifest_sha256=manifest.manifest_sha256, expected_world_head_manifest_sha256="1" * 64, proof_indexes={"asset:a": RangeProofIndex(sidecar)})
            self.assertTrue(wrong_world.manifest_hash_valid)
            self.assertFalse(wrong_world.world_head_binding_valid)

    def test_wrong_sidecar_cannot_satisfy_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, a = self._commitment(root, "a", b"A" * 24, 8)
            b_sidecar, _ = self._commitment(root, "b", b"B" * 24, 8)
            world_hash = _world_head().manifest_sha256()
            manifest = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"asset:a": a})
            verification = verify_materialization_manifest(manifest, expected_manifest_sha256=manifest.manifest_sha256, expected_world_head_manifest_sha256=world_hash, proof_indexes={"asset:a": RangeProofIndex(b_sidecar)})
            self.assertFalse(verification.artifact_commitments_valid)

    def test_proof_layout_can_change_without_changing_source_or_world_identity(self):
        content = b"same-world-object" * 4
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.bin"; source.write_bytes(content)
            from isql_world_materializer import ExactContentIdentity
            identity = ExactContentIdentity("sha256", hashlib.sha256(content).hexdigest())
            c8 = build_range_proof_sidecar(source, root / "c8.sqlite3", identity, chunk_size=8)
            c16 = build_range_proof_sidecar(source, root / "c16.sqlite3", identity, chunk_size=16)
            world_hash = _world_head().manifest_sha256()
            m8 = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"asset": c8})
            m16 = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"asset": c16})
            self.assertEqual(c8.source_identity, c16.source_identity)
            self.assertEqual(m8.world_head_manifest_sha256, m16.world_head_manifest_sha256)
            self.assertNotEqual(c8.commitment_sha256, c16.commitment_sha256)
            self.assertNotEqual(m8.manifest_sha256, m16.manifest_sha256)

    def test_reader_hands_exact_binding_to_d12(self):
        content = bytes(range(64))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sidecar, commitment = self._commitment(root, "asset", content, 16)
            provider_root = root / "provider"; provider_root.mkdir()
            (provider_root / "asset.bin").write_bytes(content)
            catalog = PlacementCatalog(root / "placements.sqlite3")
            catalog.register(PlacementRecord(identity=commitment.source_identity, placement_id="copy", provider_id="local", object_key="asset.bin", size_bytes=len(content), region="local", tier="hot"))
            world_hash = _world_head().manifest_sha256()
            manifest = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"asset:main": commitment})
            reader = MaterializationRangeReader(
                manifest,
                expected_manifest_sha256=manifest.manifest_sha256,
                expected_world_head_manifest_sha256=world_hash,
                proof_indexes={"asset:main": RangeProofIndex(sidecar)},
                range_fetcher=VerifiedRangeFetcher(PhysicalPlacementResolver(catalog), {"local": LocalDirectoryProvider(provider_root)}),
            )
            result = reader.fetch_range("asset:main", offset=15, length=19)
            self.assertEqual(result.content, content[15:34])
            self.assertEqual(result.identity, commitment.source_identity)
            self.assertEqual(result.range_commitment_sha256, commitment.commitment_sha256)

    def test_reader_rejects_untrusted_materialization_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sidecar, commitment = self._commitment(root, "asset", b"trust-boundary" * 4, 8)
            world_hash = _world_head().manifest_sha256()
            manifest = build_materialization_manifest(world_id="world:alpha", world_head_manifest_sha256=world_hash, profile_id="p", commitments={"asset": commitment})
            with self.assertRaises(MaterializationError) as ctx:
                MaterializationRangeReader(
                    manifest,
                    expected_manifest_sha256="0" * 64,
                    expected_world_head_manifest_sha256=world_hash,
                    proof_indexes={"asset": RangeProofIndex(sidecar)},
                    range_fetcher=VerifiedRangeFetcher(PhysicalPlacementResolver(PlacementCatalog(root / "placements.sqlite3")), {}),
                )
            self.assertEqual(ctx.exception.code, "MATERIALIZATION_MANIFEST_VERIFICATION_FAILED")


if __name__ == "__main__":
    unittest.main()
