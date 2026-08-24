from __future__ import annotations

import importlib.util
from pathlib import Path


def load_demo_module():
    path = Path(__file__).resolve().parents[1] / 'examples' / 'utility_demo.py'
    assert path.exists(), 'examples/utility_demo.py must exist'
    spec = importlib.util.spec_from_file_location('sedb_utility_demo', path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_utility_demo_covers_governance_recommendations(tmp_path):
    demo = load_demo_module()
    result = demo.build_utility_demo(tmp_path / 'utility.sqlite')
    recs = result['recommendations']
    assert recs['fresh_empty'] == 'insufficient_evidence'
    assert recs['old_unused'] == 'converge_candidate'
    assert recs['protected_unused'] == 'keep'
    assert recs['task_supported'] == 'keep'
    assert recs['semantic_review'] == 'review'
    assert recs['reactivation_signal'] == 'reactivate_candidate'
    assert result['applied_old_unused_status'] == 'converged'
    assert result['lifecycle_assessment_links'] >= 1


def test_utility_registry_benchmark_is_bounded(tmp_path):
    demo = load_demo_module()
    result = demo.benchmark_utility_registry(tmp_path / 'utility-bench.sqlite', field_count=120)
    assert result['fields'] == 120
    assert result['assessments'] == 120
    assert sum(result['recommendations'].values()) == 120
    assert result['limit_fields'] == 120
