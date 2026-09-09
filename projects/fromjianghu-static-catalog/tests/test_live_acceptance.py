from __future__ import annotations

import os

import pytest

from config import ProjectConfig, default_config
from source import load_catalog
from store import CatalogStore


pytestmark = pytest.mark.skipif(
    os.environ.get("SEDB_RUN_FROMJIANGHU_ACCEPTANCE") != "1",
    reason="set SEDB_RUN_FROMJIANGHU_ACCEPTANCE=1 for the pinned live-source acceptance",
)


def test_pinned_live_source_builds_and_replays_exact_catalog(tmp_path):
    defaults = default_config()
    config = ProjectConfig(
        source_root=defaults.source_root,
        database_path=tmp_path / "fromjianghu-live-acceptance.sqlite",
        source_hashes=defaults.source_hashes,
        expected_entity_counts=defaults.expected_entity_counts,
    )

    snapshot = load_catalog(config)
    store = CatalogStore.open(config)
    schema = store.ensure_schema()
    first = store.apply(store.plan(snapshot))
    replay = store.plan(snapshot)

    assert snapshot.fingerprint == "a01b8a8cc52dc4b376fc557f1795073928c488cd8eb1a80dcd59bf2c38234027"
    assert len(snapshot.records) == 6979
    assert schema.fields_created == 92
    assert schema.views_created == 8
    assert first.created_entities == 6979
    assert first.created_cells == 142562
    assert replay.new == ()
    assert len(replay.unchanged) == 6979
    assert replay.blocked is False
    assert store.stats()["integrity"] == "ok"
