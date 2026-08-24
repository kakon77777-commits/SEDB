from __future__ import annotations

import importlib.util
from pathlib import Path

import sedb


def load_demo_module():
    path = Path(__file__).resolve().parents[1] / "examples" / "agent_demo.py"
    assert path.exists(), "examples/agent_demo.py must exist"
    spec = importlib.util.spec_from_file_location("sedb_agent_demo", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_current_release_identity():
    assert sedb.__version__ == "0.4.0b1"
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.4.0b1"' in pyproject


def test_agent_governance_demo_preserves_canonical_state_and_records_controls(tmp_path):
    demo = load_demo_module()
    result = demo.build_agent_demo(tmp_path / "agent-governance.sqlite")

    assert result["field_count_before_runs"] == result["field_count_after_runs"]
    assert result["cell_count_before_runs"] == result["cell_count_after_runs"]
    assert result["proposals_created"] >= 3
    assert result["denied_mutation_receipts"] == 1
    assert result["budget_run_status"] == "budget_exhausted"
    assert result["budget_run_proposals_created"] == 0
    assert result["deterministic_run_status"] == "completed"
    assert result["external_run_status"] == "completed"


def test_agent_observation_benchmark_is_bounded_and_noncanonical(tmp_path):
    demo = load_demo_module()
    result = demo.benchmark_agent_observation(
        tmp_path / "agent-bench.sqlite", record_count=120, field_width=8
    )

    assert result["records"] == 120
    assert result["field_width"] == 8
    assert result["proposals_created"] == 8
    assert result["field_count_before"] == result["field_count_after"] == 0
    assert result["cell_count_before"] == result["cell_count_after"] == 0
    assert result["run_status"] == "completed"
    assert result["steps"] <= 10
