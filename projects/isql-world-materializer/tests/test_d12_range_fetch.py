from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from isql_world_materializer import (
    ExactContentIdentity,
    LocalDirectoryProvider,
    PhysicalPlacementResolver,
    PlacementCatalog,
    PlacementRecord,
    RangeProofError,
    RangeProofIndex,
    VerifiedRangeFetchError,
    VerifiedRangeFetcher,
    build_range_proof_sidecar,
    verify_chunk_proof,
)


def _identity(content: bytes) -> ExactContentIdentity:
    return ExactContentIdentity("sha256", hashlib.sha256(content).hexdigest())


def _placement(identity, placement_id, provider_id, key, size, priority=100):
    return PlacementRecord(
        identity=identity,
        placement_id=placement_id,
        provider_id=provider_id,
        object_key=key,
        size_bytes=size,
        region="local",
        tier="hot",
        priority=priority,
    )


class CountingRangeProvider:
    def __init__(self, provider: LocalDirectoryProvider):
        self.provider = provider
        self.calls: list[tuple[int, int]] = []
        self.bytes_requested = 0

    def read_range(self, object_key: str, *, offset: int, length: int, max_bytes=None) -> bytes:
        self.calls.append((offset, length))
        self.bytes_requested += length
        return self.provider.read_range(object_key, offset=offset, length=length, max_bytes=max_bytes)


class D12RangeFetchTests(unittest.TestCase):
    def _build(self, root: Path, content: bytes, *, chunk_size: int = 8):
        source = root / "source.bin"
        source.write_bytes(content)
        identity = _identity(content)
        sidecar = root / "range.sqlite3"
        commitment = build_range_proof_sidecar(source, sidecar, identity, chunk_size=chunk_size)
        return source, identity, sidecar, commitment

    def _resolver(self, root: Path):
        catalog = PlacementCatalog(root / "placement.sqlite3")
        return catalog, PhysicalPlacementResolver(catalog)

    def test_sidecar_binds_full_source_identity_and_each_chunk_proof(self):
        content = b"abcdefghijklmnopqrstuvwxyz"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, identity, sidecar, commitment = self._build(root, content, chunk_size=8)
            self.assertEqual(commitment.source_identity, identity)
            self.assertEqual(commitment.size_bytes, len(content))
            self.assertEqual(commitment.chunk_count, 4)
            index = RangeProofIndex(sidecar)
            self.assertEqual(index.commitment(), commitment)
            for chunk_index in range(commitment.chunk_count):
                start = chunk_index * commitment.chunk_size
                block = content[start : start + commitment.expected_chunk_length(chunk_index)]
                self.assertTrue(verify_chunk_proof(commitment, block, index.proof(chunk_index)))

    def test_build_rejects_wrong_full_source_identity(self):
        content = b"real-source"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.bin"
            source.write_bytes(content)
            with self.assertRaises(RangeProofError) as ctx:
                build_range_proof_sidecar(
                    source,
                    root / "proof.sqlite3",
                    _identity(b"different-source"),
                    chunk_size=4,
                )
            self.assertEqual(ctx.exception.code, "RANGE_SOURCE_DIGEST_MISMATCH")

    def test_single_chunk_range_reads_only_one_covering_chunk(self):
        content = bytes(range(64))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, identity, sidecar, commitment = self._build(root, content, chunk_size=16)
            provider_root = root / "provider"; provider_root.mkdir()
            (provider_root / "object.bin").write_bytes(content)
            catalog, resolver = self._resolver(root)
            catalog.register(_placement(identity, "copy", "local", "object.bin", len(content)))
            counting = CountingRangeProvider(LocalDirectoryProvider(provider_root))
            result = VerifiedRangeFetcher(resolver, {"local": counting}).fetch_range(
                identity,
                RangeProofIndex(sidecar),
                expected_commitment_sha256=commitment.commitment_sha256,
                offset=18,
                length=5,
            )
            self.assertEqual(result.content, content[18:23])
            self.assertEqual(result.chunk_indices, (1,))
            self.assertEqual(counting.calls, [(16, 16)])
            self.assertEqual(counting.bytes_requested, 16)
            self.assertLess(counting.bytes_requested, len(content))

    def test_cross_chunk_range_reads_only_covering_chunks(self):
        content = bytes(range(80))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, identity, sidecar, commitment = self._build(root, content, chunk_size=16)
            provider_root = root / "provider"; provider_root.mkdir()
            (provider_root / "object.bin").write_bytes(content)
            catalog, resolver = self._resolver(root)
            catalog.register(_placement(identity, "copy", "local", "object.bin", len(content)))
            counting = CountingRangeProvider(LocalDirectoryProvider(provider_root))
            result = VerifiedRangeFetcher(resolver, {"local": counting}).fetch_range(
                identity,
                RangeProofIndex(sidecar),
                expected_commitment_sha256=commitment.commitment_sha256,
                offset=14,
                length=21,
            )
            self.assertEqual(result.content, content[14:35])
            self.assertEqual(result.chunk_indices, (0, 1, 2))
            self.assertEqual(counting.bytes_requested, 48)
            self.assertLess(counting.bytes_requested, len(content))

    def test_corrupt_preferred_replica_fails_proof_then_valid_replica_succeeds(self):
        content = b"0123456789abcdef" * 4
        corrupted = bytearray(content)
        corrupted[20] ^= 0xFF
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, identity, sidecar, commitment = self._build(root, content, chunk_size=16)
            bad_root = root / "bad"; good_root = root / "good"
            bad_root.mkdir(); good_root.mkdir()
            (bad_root / "object.bin").write_bytes(bytes(corrupted))
            (good_root / "object.bin").write_bytes(content)
            catalog, resolver = self._resolver(root)
            catalog.register(_placement(identity, "bad", "bad", "object.bin", len(content), priority=0))
            catalog.register(_placement(identity, "good", "good", "object.bin", len(content), priority=1))
            result = VerifiedRangeFetcher(
                resolver,
                {"bad": LocalDirectoryProvider(bad_root), "good": LocalDirectoryProvider(good_root)},
            ).fetch_range(
                identity,
                RangeProofIndex(sidecar),
                expected_commitment_sha256=commitment.commitment_sha256,
                offset=18,
                length=5,
            )
            self.assertEqual(result.content, content[18:23])
            self.assertEqual(result.placement.placement_id, "good")
            self.assertEqual(result.attempted_placement_ids, ("bad", "good"))

    def test_wrong_expected_commitment_fails_before_physical_read(self):
        content = b"abcdefghijklmnop"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, identity, sidecar, _ = self._build(root, content, chunk_size=8)
            provider_root = root / "provider"; provider_root.mkdir()
            (provider_root / "object.bin").write_bytes(content)
            catalog, resolver = self._resolver(root)
            catalog.register(_placement(identity, "copy", "local", "object.bin", len(content)))
            counting = CountingRangeProvider(LocalDirectoryProvider(provider_root))
            with self.assertRaises(VerifiedRangeFetchError) as ctx:
                VerifiedRangeFetcher(resolver, {"local": counting}).fetch_range(
                    identity,
                    RangeProofIndex(sidecar),
                    expected_commitment_sha256="0" * 64,
                    offset=0,
                    length=4,
                )
            self.assertEqual(ctx.exception.code, "RANGE_FETCH_COMMITMENT_MISMATCH")
            self.assertEqual(counting.calls, [])

    def test_source_identity_mismatch_fails_before_physical_read(self):
        content = b"abcdefghijklmnop"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, sidecar, commitment = self._build(root, content, chunk_size=8)
            other = _identity(b"different-content")
            catalog, resolver = self._resolver(root)
            with self.assertRaises(VerifiedRangeFetchError) as ctx:
                VerifiedRangeFetcher(resolver, {}).fetch_range(
                    other,
                    RangeProofIndex(sidecar),
                    expected_commitment_sha256=commitment.commitment_sha256,
                    offset=0,
                    length=4,
                )
            self.assertEqual(ctx.exception.code, "RANGE_FETCH_SOURCE_IDENTITY_MISMATCH")

    def test_placement_size_mismatch_can_fail_over(self):
        content = b"0123456789abcdef"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, identity, sidecar, commitment = self._build(root, content, chunk_size=8)
            provider_root = root / "provider"; provider_root.mkdir()
            (provider_root / "object.bin").write_bytes(content)
            catalog, resolver = self._resolver(root)
            catalog.register(_placement(identity, "wrong-size", "local", "object.bin", len(content) + 1, priority=0))
            catalog.register(_placement(identity, "correct", "local", "object.bin", len(content), priority=1))
            result = VerifiedRangeFetcher(resolver, {"local": LocalDirectoryProvider(provider_root)}).fetch_range(
                identity,
                RangeProofIndex(sidecar),
                expected_commitment_sha256=commitment.commitment_sha256,
                offset=1,
                length=3,
            )
            self.assertEqual(result.placement.placement_id, "correct")
            self.assertEqual(result.attempted_placement_ids, ("wrong-size", "correct"))

    def test_out_of_bounds_and_zero_length_are_rejected(self):
        content = b"12345678"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, identity, sidecar, commitment = self._build(root, content, chunk_size=4)
            catalog, resolver = self._resolver(root)
            fetcher = VerifiedRangeFetcher(resolver, {})
            with self.assertRaises(VerifiedRangeFetchError) as ctx:
                fetcher.fetch_range(identity, RangeProofIndex(sidecar), expected_commitment_sha256=commitment.commitment_sha256, offset=7, length=2)
            self.assertEqual(ctx.exception.code, "RANGE_FETCH_OUT_OF_BOUNDS")
            with self.assertRaises(VerifiedRangeFetchError) as ctx:
                fetcher.fetch_range(identity, RangeProofIndex(sidecar), expected_commitment_sha256=commitment.commitment_sha256, offset=0, length=0)
            self.assertEqual(ctx.exception.code, "RANGE_FETCH_LENGTH_INVALID")

    def test_tampered_proof_node_is_detected(self):
        content = bytes(range(40))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, identity, sidecar, commitment = self._build(root, content, chunk_size=8)
            with sqlite3.connect(sidecar) as con:
                con.execute("DROP TRIGGER nodes_no_update")
                con.execute("UPDATE nodes SET node_hash=? WHERE level=0 AND node_index=1", (b"\x00" * 32,))
            provider_root = root / "provider"; provider_root.mkdir()
            (provider_root / "object.bin").write_bytes(content)
            catalog, resolver = self._resolver(root)
            catalog.register(_placement(identity, "copy", "local", "object.bin", len(content)))
            with self.assertRaises(VerifiedRangeFetchError) as ctx:
                VerifiedRangeFetcher(resolver, {"local": LocalDirectoryProvider(provider_root)}).fetch_range(
                    identity,
                    RangeProofIndex(sidecar),
                    expected_commitment_sha256=commitment.commitment_sha256,
                    offset=0,
                    length=4,
                )
            self.assertEqual(ctx.exception.code, "RANGE_FETCH_ALL_PLACEMENTS_FAILED")
            self.assertEqual(ctx.exception.attempts[0].code, "RANGE_FETCH_CHUNK_PROOF_INVALID")

    def test_sidecar_can_issue_proof_after_original_source_is_removed(self):
        content = b"proof-index-survives-source-removal"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, _, sidecar, commitment = self._build(root, content, chunk_size=8)
            source.unlink()
            index = RangeProofIndex(sidecar)
            proof = index.proof(0)
            self.assertEqual(index.commitment(), commitment)
            self.assertEqual(proof.chunk_length, 8)

    def test_sidecar_tables_are_immutable_under_normal_writes(self):
        content = b"immutable-proof-sidecar"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, sidecar, _ = self._build(root, content, chunk_size=8)
            with sqlite3.connect(sidecar) as con:
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute("UPDATE chunks SET chunk_length=0 WHERE chunk_index=0")
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute("DELETE FROM nodes WHERE level=0 AND node_index=0")


if __name__ == "__main__":
    unittest.main()
