from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from isql_distributed_universe_mvp import (
    SyntheticUniverseConfig,
    acceptance_passes,
    run_synthetic_acceptance,
)


class D15DistributedUniverseAcceptanceTests(unittest.TestCase):
    def test_small_synthetic_universe_closes_end_to_end_chain(self):
        config = SyntheticUniverseConfig(
            object_count=64,
            topic_count=8,
            active_entities=4,
            artifact_size=1024,
            chunk_size=128,
            range_offset=64,
            range_length=32,
            seed="d15-test-small",
        )
        with tempfile.TemporaryDirectory() as td:
            report = run_synthetic_acceptance(Path(td), config)

        self.assertTrue(acceptance_passes(report))
        self.assertEqual(report.universe_objects, 64)
        self.assertEqual(report.active_entities, 4)
        self.assertEqual(report.materialization_artifacts, 4)
        self.assertEqual(report.requested_payload_bytes, 128)
        self.assertEqual(report.semantic_profile_entries, 64)
        self.assertEqual(report.semantic_probe_count, 8)
        self.assertAlmostEqual(report.semantic_probe_ratio, 8 / 64)
        self.assertAlmostEqual(report.active_domain_ratio, 4 / 64)
        self.assertGreaterEqual(report.replica_failover_count, 1)
        self.assertLess(report.physical_range_bytes, report.total_universe_bytes)
        self.assertTrue(report.historical_world_head_valid_after_dsr_advance)
        self.assertFalse(report.historical_world_head_current_after_dsr_advance)
        self.assertTrue(report.new_world_head_current)
        self.assertTrue(report.stale_materialization_rejected_for_new_world_head)
        self.assertEqual(len(report.report_sha256), 64)

    def test_resource_ratios_shrink_as_universe_grows_with_fixed_active_domain(self):
        small = SyntheticUniverseConfig(
            object_count=32,
            topic_count=4,
            active_entities=2,
            artifact_size=512,
            chunk_size=64,
            range_offset=16,
            range_length=16,
            seed="d15-ratio-small",
        )
        large = SyntheticUniverseConfig(
            object_count=96,
            topic_count=12,
            active_entities=2,
            artifact_size=512,
            chunk_size=64,
            range_offset=16,
            range_length=16,
            seed="d15-ratio-large",
        )
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            r1 = run_synthetic_acceptance(Path(td1), small)
            r2 = run_synthetic_acceptance(Path(td2), large)

        self.assertTrue(acceptance_passes(r1))
        self.assertTrue(acceptance_passes(r2))
        self.assertLess(r2.active_domain_ratio, r1.active_domain_ratio)
        self.assertLess(r2.physical_fetch_ratio, r1.physical_fetch_ratio)
        self.assertEqual(r1.active_entities, r2.active_entities)

    def test_config_rejects_impossible_active_population_or_range(self):
        with self.assertRaises(ValueError):
            SyntheticUniverseConfig(object_count=8, topic_count=8, active_entities=2)
        with self.assertRaises(ValueError):
            SyntheticUniverseConfig(artifact_size=16, range_offset=8, range_length=9)


if __name__ == "__main__":
    unittest.main()
