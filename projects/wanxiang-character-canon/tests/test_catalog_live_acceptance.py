from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from catalog_source import compose_full_catalog
from config import default_config
from source import load_snapshot
from store import CanonStore


LIVE_ENABLED = os.environ.get("WANXIANG_CANON_LIVE") == "1"


def _tree_signature(root: Path) -> tuple[int, int, tuple[tuple[str, int], ...]]:
    files = tuple(path for path in root.rglob("*") if path.is_file())
    return (
        len(files),
        sum(path.stat().st_size for path in files),
        tuple(
            (str(path.relative_to(root)), path.stat().st_mtime_ns)
            for path in sorted(files)
        ),
    )


@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set WANXIANG_CANON_LIVE=1 for real full-catalog store acceptance",
)
def test_real_full_catalog_atomic_expansion_and_both_scope_no_ops(tmp_path):
    base = default_config()
    config = replace(base, database_path=tmp_path / "full-catalog.sqlite")
    before = _tree_signature(config.source_root)
    wave1 = load_snapshot(config)
    full = compose_full_catalog(config, include_edges=True)
    store = CanonStore.open(config)
    store.ensure_schema()
    wave1_result = store.apply(store.plan(wave1))
    first_plan = store.plan(full)

    assert wave1_result.created_entities == 1967
    assert len(first_plan.new) == 69786
    assert len(first_plan.enrich) == 229
    assert first_plan.conflicts == ()
    assert first_plan.missing_from_source == ()

    first = store.apply(first_plan)
    refreshed = compose_full_catalog(config, include_edges=True)
    rerun = store.plan(refreshed)
    wave1_rerun = store.plan(load_snapshot(config))

    assert first.created_entities == 69786
    assert first.enriched_entities == 229
    assert store.db.scalar("SELECT COUNT(*) FROM entities") == 71753
    assert store.db.scalar(
        "SELECT COUNT(*) FROM entities WHERE kind='wanxiang_reference_edge_snapshot'"
    ) == 40075
    assert store.db.scalar(
        """
        SELECT COUNT(*) FROM entities e
        JOIN cells c ON c.entity_id=e.id
        JOIN fields f ON f.id=c.field_id
        WHERE f.key='source_table'
        """
    ) == 29939
    assert rerun.new == ()
    assert rerun.enrich == ()
    assert rerun.conflicts == ()
    assert rerun.missing_from_source == ()
    assert len(rerun.unchanged) == 71753
    assert wave1_rerun.new == ()
    assert wave1_rerun.enrich == ()
    assert wave1_rerun.conflicts == ()
    assert len(wave1_rerun.unchanged) == 1967
    assert store.integrity_check() == "ok"
    assert _tree_signature(config.source_root) == before
