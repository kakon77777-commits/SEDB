from __future__ import annotations

import importlib.util
from pathlib import Path

import sedb


def load_demo_module():
    path = Path(__file__).resolve().parents[1] / "examples" / "autonomy_demo.py"
    assert path.exists(), "examples/autonomy_demo.py must exist"
    spec = importlib.util.spec_from_file_location("sedb_autonomy_demo", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v04b_release_identity():
    assert sedb.__version__ == "0.4.0b1"
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.4.0b1"' in pyproject


def test_autonomy_demo_proves_commit_escalation_capability_failure_and_rollback(tmp_path):
    demo = load_demo_module()
    result = demo.run_demo(tmp_path / "autonomy-demo.sqlite")

    assert result["canonical_fields_before"] == 0
    assert result["canonical_fields_after_commit"] == 1
    assert result["conflict_decision"] == "ESCALATE"
    assert result["novel_decision"] == "EXECUTE"
    assert result["novel_commit_failure"] == "CAPABILITY_MISSING"
    assert result["rollback_count"] == 1
    assert result["commit_count"] == 1
    assert result["rolled_back_field_status"] == "deprecated"
    assert Path(result["db_path"]).exists()
