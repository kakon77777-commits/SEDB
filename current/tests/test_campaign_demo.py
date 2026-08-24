from __future__ import annotations

import importlib.util
from pathlib import Path

import sedb


def load_demo_module():
    path = Path(__file__).resolve().parents[1] / "examples" / "campaign_demo.py"
    assert path.exists(), "examples/campaign_demo.py must exist"
    spec = importlib.util.spec_from_file_location("sedb_campaign_demo", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v04a_release_identity():
    assert sedb.__version__ == "0.4.0b1"
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.4.0b1"' in pyproject


def test_campaign_demo_preserves_canonical_state_and_emits_consensus(tmp_path):
    demo = load_demo_module()
    result = demo.build_campaign_demo(tmp_path / "campaign-governance.sqlite")

    assert result["field_count_before"] == result["field_count_after"]
    assert result["cell_count_before"] == result["cell_count_after"]
    assert result["campaign_status"] == "completed"
    assert "strong_agreement" in result["packet_statuses"]
    assert "incompatible" in result["packet_statuses"]
    assert result["raw_support_max"] > result["independent_support_min"]


def test_campaign_benchmark_is_bounded_and_noncanonical(tmp_path):
    demo = load_demo_module()
    result = demo.benchmark_campaign_coordination(
        tmp_path / "campaign-bench.sqlite", run_count=24, key_count=4
    )

    assert result["runs"] == 24
    assert result["work_items"] == 24
    assert result["packet_count"] == 4
    assert result["field_count_before"] == result["field_count_after"] == 0
    assert result["cell_count_before"] == result["cell_count_after"] == 0
