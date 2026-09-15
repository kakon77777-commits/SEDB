from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from isql_world_materializer import (
    ExactContentIdentity,
    LocalDirectoryProvider,
    PhysicalPlacementResolver,
    PlacementCatalog,
    PlacementError,
    PlacementPolicy,
    PlacementRecord,
    ProviderReadError,
    VerifiedFetchError,
    VerifiedFetcher,
)


def _identity(content: bytes) -> ExactContentIdentity:
    return ExactContentIdentity("sha256", hashlib.sha256(content).hexdigest())


def _record(
    identity: ExactContentIdentity,
    placement_id: str,
    provider_id: str,
    key: str,
    size: int,
    *,
    region: str = "region-a",
    tier: str = "hot",
    priority: int = 100,
    enabled: bool = True,
) -> PlacementRecord:
    return PlacementRecord(
        identity=identity,
        placement_id=placement_id,
        provider_id=provider_id,
        object_key=key,
        size_bytes=size,
        region=region,
        tier=tier,
        priority=priority,
        enabled=enabled,
    )


class D11PhysicalResolverTests(unittest.TestCase):
    def _catalog(self, root: Path) -> tuple[PlacementCatalog, PhysicalPlacementResolver]:
        catalog = PlacementCatalog(root / "placement.sqlite3")
        return catalog, PhysicalPlacementResolver(catalog)

    def test_exact_file_fetch_verifies_identity(self):
        content = b"exact-world-object"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            provider_root = root / "provider"
            (provider_root / "objects").mkdir(parents=True)
            (provider_root / "objects" / "a.bin").write_bytes(content)
            catalog, resolver = self._catalog(root)
            catalog.register(_record(identity, "p1", "local-a", "objects/a.bin", len(content)))
            fetcher = VerifiedFetcher(resolver, {"local-a": LocalDirectoryProvider(provider_root)})
            result = fetcher.fetch(identity)
            self.assertEqual(result.identity, identity)
            self.assertEqual(result.content, content)
            self.assertEqual(result.placement.placement_id, "p1")
            self.assertEqual(result.attempted_placement_ids, ("p1",))

    def test_corrupt_preferred_replica_falls_back_without_changing_identity(self):
        good = b"same-exact-state"
        bad = b"corrupt-content!"
        self.assertEqual(len(good), len(bad))
        identity = _identity(good)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a"
            b = root / "b"
            a.mkdir(); b.mkdir()
            (a / "state.bin").write_bytes(bad)
            (b / "state.bin").write_bytes(good)
            catalog, resolver = self._catalog(root)
            catalog.register(_record(identity, "preferred", "a", "state.bin", len(good), region="near", priority=1))
            catalog.register(_record(identity, "fallback", "b", "state.bin", len(good), region="far", priority=2))
            fetcher = VerifiedFetcher(
                resolver,
                {"a": LocalDirectoryProvider(a), "b": LocalDirectoryProvider(b)},
            )
            result = fetcher.fetch(identity, PlacementPolicy(preferred_region="near"))
            self.assertEqual(result.identity, identity)
            self.assertEqual(result.content, good)
            self.assertEqual(result.placement.placement_id, "fallback")
            self.assertEqual(result.attempted_placement_ids, ("preferred", "fallback"))

    def test_all_wrong_replicas_fail_closed_with_exact_identity_unchanged(self):
        good = b"canonical"
        identity = _identity(good)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            provider = root / "provider"
            provider.mkdir()
            (provider / "bad.bin").write_bytes(b"xxxxxxxxx")
            catalog, resolver = self._catalog(root)
            catalog.register(_record(identity, "bad", "local", "bad.bin", len(good)))
            fetcher = VerifiedFetcher(resolver, {"local": LocalDirectoryProvider(provider)})
            with self.assertRaises(VerifiedFetchError) as ctx:
                fetcher.fetch(identity)
            self.assertEqual(ctx.exception.code, "FETCH_ALL_PLACEMENTS_FAILED")
            self.assertEqual(ctx.exception.attempts[0].code, "FETCH_DIGEST_MISMATCH")
            self.assertEqual(identity.digest, hashlib.sha256(good).hexdigest())

    def test_placement_migration_does_not_change_identity(self):
        content = b"portable-state"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "old"; new = root / "new"
            old.mkdir(); new.mkdir()
            (old / "x.bin").write_bytes(content)
            (new / "moved.bin").write_bytes(content)
            catalog, resolver = self._catalog(root)
            catalog.register(_record(identity, "old-copy", "old", "x.bin", len(content)))
            first = VerifiedFetcher(resolver, {"old": LocalDirectoryProvider(old)}).fetch(identity)
            self.assertEqual(first.identity, identity)
            catalog.remove(identity, "old-copy")
            catalog.register(_record(identity, "new-copy", "new", "moved.bin", len(content), region="region-b"))
            second = VerifiedFetcher(resolver, {"new": LocalDirectoryProvider(new)}).fetch(identity)
            self.assertEqual(second.identity, identity)
            self.assertEqual(first.content, second.content)
            self.assertNotEqual(first.placement.placement_id, second.placement.placement_id)

    def test_preferred_region_ranks_before_ordinary_priority(self):
        content = b"ranked"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, resolver = self._catalog(root)
            catalog.register(_record(identity, "fast-priority", "a", "a.bin", len(content), region="far", priority=0))
            catalog.register(_record(identity, "near-region", "b", "b.bin", len(content), region="near", priority=999))
            resolved = resolver.resolve(identity, PlacementPolicy(preferred_region="near"))
            self.assertEqual([r.placement_id for r in resolved], ["near-region", "fast-priority"])

    def test_provider_tier_and_size_filters_are_applied(self):
        identity = _identity(b"12345")
        with tempfile.TemporaryDirectory() as td:
            catalog, resolver = self._catalog(Path(td))
            catalog.register(_record(identity, "a", "provider-a", "a.bin", 5, tier="hot"))
            catalog.register(_record(identity, "b", "provider-b", "b.bin", 5, tier="cold"))
            catalog.register(_record(identity, "c", "provider-a", "c.bin", 50, tier="hot"))
            policy = PlacementPolicy(
                allowed_provider_ids=("provider-a",),
                allowed_tiers=("hot",),
                max_bytes=10,
            )
            self.assertEqual([r.placement_id for r in resolver.resolve(identity, policy)], ["a"])

    def test_disabled_placement_is_ignored(self):
        identity = _identity(b"state")
        with tempfile.TemporaryDirectory() as td:
            catalog, resolver = self._catalog(Path(td))
            catalog.register(_record(identity, "disabled", "a", "a.bin", 5, enabled=False, priority=0))
            catalog.register(_record(identity, "enabled", "b", "b.bin", 5, enabled=True, priority=10))
            self.assertEqual([r.placement_id for r in resolver.resolve(identity)], ["enabled"])

    def test_invalid_and_traversal_object_keys_are_rejected(self):
        identity = _identity(b"x")
        for key in ("../x", "/absolute", "a/../b", "a//b", "a\\b", "a/"):
            with self.subTest(key=key):
                with self.assertRaises(PlacementError):
                    _record(identity, "p", "provider", key, 1)

    def test_local_provider_rejects_resolved_symlink_escape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            provider_root = root / "provider"
            outside = root / "outside"
            provider_root.mkdir(); outside.mkdir()
            (outside / "secret.bin").write_bytes(b"secret")
            link = provider_root / "escape.bin"
            try:
                os.symlink(outside / "secret.bin", link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            provider = LocalDirectoryProvider(provider_root)
            with self.assertRaises(ProviderReadError) as ctx:
                provider.read("escape.bin")
            self.assertEqual(ctx.exception.code, "PROVIDER_OBJECT_ESCAPE")

    def test_duplicate_metadata_requires_explicit_replace(self):
        identity = _identity(b"state")
        with tempfile.TemporaryDirectory() as td:
            catalog, _ = self._catalog(Path(td))
            first = _record(identity, "copy", "a", "x.bin", 5, region="r1")
            changed = _record(identity, "copy", "b", "x.bin", 5, region="r2")
            catalog.register(first)
            catalog.register(first)  # exact idempotent retry
            with self.assertRaises(PlacementError) as ctx:
                catalog.register(changed)
            self.assertEqual(ctx.exception.code, "PLACEMENT_ALREADY_EXISTS")
            catalog.register(changed, replace=True)
            self.assertEqual(catalog.records(identity), (changed,))

    def test_replace_all_demonstrates_catalog_rebuildability(self):
        one = _identity(b"one")
        two = _identity(b"two")
        with tempfile.TemporaryDirectory() as td:
            catalog, _ = self._catalog(Path(td))
            old = _record(one, "old", "a", "old.bin", 3)
            new = _record(two, "new", "b", "new.bin", 3)
            catalog.register(old)
            catalog.replace_all((new,))
            self.assertEqual(catalog.records(one), ())
            self.assertEqual(catalog.records(two), (new,))

    def test_short_file_size_mismatch_fails_then_valid_replica_succeeds(self):
        content = b"abcdefgh"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            short_root = root / "short"; good_root = root / "good"
            short_root.mkdir(); good_root.mkdir()
            (short_root / "x.bin").write_bytes(b"abc")
            (good_root / "x.bin").write_bytes(content)
            catalog, resolver = self._catalog(root)
            catalog.register(_record(identity, "short", "short", "x.bin", len(content), priority=0))
            catalog.register(_record(identity, "good", "good", "x.bin", len(content), priority=1))
            result = VerifiedFetcher(
                resolver,
                {"short": LocalDirectoryProvider(short_root), "good": LocalDirectoryProvider(good_root)},
            ).fetch(identity)
            self.assertEqual(result.placement.placement_id, "good")
            self.assertEqual(result.attempted_placement_ids, ("short", "good"))

    def test_unavailable_provider_can_fail_over(self):
        content = b"available"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good_root = root / "good"; good_root.mkdir()
            (good_root / "x.bin").write_bytes(content)
            catalog, resolver = self._catalog(root)
            catalog.register(_record(identity, "missing-provider", "missing", "x.bin", len(content), priority=0))
            catalog.register(_record(identity, "good", "good", "x.bin", len(content), priority=1))
            result = VerifiedFetcher(resolver, {"good": LocalDirectoryProvider(good_root)}).fetch(identity)
            self.assertEqual(result.placement.placement_id, "good")
            self.assertEqual(result.attempted_placement_ids, ("missing-provider", "good"))

    def test_no_eligible_placement_fails_closed(self):
        identity = _identity(b"state")
        with tempfile.TemporaryDirectory() as td:
            catalog, resolver = self._catalog(Path(td))
            catalog.register(_record(identity, "cold", "a", "x.bin", 5, tier="cold"))
            fetcher = VerifiedFetcher(resolver, {})
            with self.assertRaises(VerifiedFetchError) as ctx:
                fetcher.fetch(identity, PlacementPolicy(allowed_tiers=("hot",)))
            self.assertEqual(ctx.exception.code, "FETCH_NO_PLACEMENT")


if __name__ == "__main__":
    unittest.main()
