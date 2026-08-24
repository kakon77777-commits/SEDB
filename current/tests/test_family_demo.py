from __future__ import annotations

import importlib.util
from pathlib import Path


def load_demo_module():
    path = Path(__file__).resolve().parents[1] / "examples" / "family_demo.py"
    assert path.exists(), "examples/family_demo.py must exist"
    spec = importlib.util.spec_from_file_location("sedb_family_demo", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_family_demo_preserves_canonical_data_while_recording_reviews(tmp_path):
    demo = load_demo_module()
    result = demo.build_family_demo(tmp_path / "family.sqlite")

    assert result["families_by_type"] == {"duplicate": 1, "related": 1}
    assert set(result["review_decisions"]) >= {
        "duplicate_family", "related_family", "split", "reject"
    }
    assert result["field_count_before_reviews"] == result["field_count_after_reviews"]
    assert result["cell_count_before_reviews"] == result["cell_count_after_reviews"]
    assert result["split_created_family"] is False


def test_family_registry_benchmark_is_bounded_and_finds_planted_families(tmp_path):
    demo = load_demo_module()
    result = demo.benchmark_family_registry(
        tmp_path / "family-bench.sqlite", field_count=240, max_neighbors=6
    )

    assert result["fields"] == 240
    assert result["naive_all_pairs"] == 240 * 239 // 2
    assert result["bounded_pair_upper_bound"] == 240 * 6
    assert result["planted_families_found"] == 2
    assert result["proposals"] >= 2
