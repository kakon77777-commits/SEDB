from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from config import ProjectConfig
from source import load_month
from store import CorpusStore


REGISTRY = Path(
    r"D:\Ai\work together\unbounded-axiom\registry\papers.json"
)
UNBOUNDED_ROOT = REGISTRY.parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_status(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "status", "--short", "--branch"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


@pytest.mark.skipif(
    os.environ.get("SEDB_RUN_LIVE_ACCEPTANCE") != "1",
    reason=(
        "set SEDB_RUN_LIVE_ACCEPTANCE=1 for the read-only "
        "real-registry acceptance"
    ),
)
def test_real_april_import_and_no_op(tmp_path):
    before_hash = sha256(REGISTRY)
    before_status = git_status(UNBOUNDED_ROOT)
    selected = load_month(REGISTRY, "2026-04")
    assert len(selected.papers) == 87

    store = CorpusStore.open(
        ProjectConfig(REGISTRY, tmp_path / "acceptance.sqlite")
    )
    store.ensure_schema()
    first_plan = store.plan(selected)
    assert len(first_plan.new) == 87
    expected_cells = sum(len(paper.values) for paper in selected.papers)

    first = store.apply(first_plan)
    second_plan = store.plan(selected)
    second = store.apply(second_plan)

    assert first.created_entities == 87
    assert first.created_cells == expected_cells
    assert second_plan.new == ()
    assert len(second_plan.unchanged) == 87
    assert second.created_entities == 0
    assert second.created_cells == 0
    assert store.integrity_check() == "ok"
    assert sha256(REGISTRY) == before_hash
    assert git_status(UNBOUNDED_ROOT) == before_status
