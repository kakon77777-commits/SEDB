from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from config import ENTITY_COUNTS, default_config
from store import CanonStore
from source import load_snapshot


LIVE_ENABLED = os.environ.get("WANXIANG_CANON_LIVE") == "1"


def _tree_signature(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set WANXIANG_CANON_LIVE=1 for the real read-only source acceptance",
)
def test_real_build_25006280_atomic_bootstrap_and_no_op(tmp_path):
    base = default_config()
    config = replace(base, database_path=tmp_path / "wanxiang-live.sqlite")
    tree_before = _tree_signature(config.source_root)

    selection = load_snapshot(config)
    source_hashes_before = selection.source_hashes
    assert selection.build_id == 25006280
    assert selection.counts == ENTITY_COUNTS
    assert sum(selection.counts.values()) == 1967

    store = CanonStore.open(config)
    initialized = store.ensure_schema()
    first = store.apply(store.plan(selection))
    refreshed = load_snapshot(config)
    rerun = store.plan(refreshed)

    assert initialized.integrity == "ok"
    assert first.created_entities == 1967
    assert first.created_cells > first.created_entities
    assert rerun.new == ()
    assert rerun.conflicts == ()
    assert rerun.missing_from_source == ()
    assert len(rerun.unchanged) == 1967
    assert rerun.blocked is False
    assert refreshed.source_hashes == source_hashes_before
    assert store.stats()["by_kind"] == ENTITY_COUNTS
    assert store.integrity_check() == "ok"
    assert _tree_signature(config.source_root) == tree_before
