from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from catalog import build_parser, main
from export_catalog import render_catalog, write_catalog
from schema import CatalogStore


@pytest.fixture
def store_with_records(tmp_path) -> CatalogStore:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()
    anchor = store.create_record(
        "temporal_anchor",
        "ingest anchor",
        {
            "temporal_status": "registered",
            "ctcl_instant_id": "ctcl:instant:export-test",
            "ctcl_local": "2026-08-24T20:00:00+08:00",
            "ctcl_utc": "2026-08-24T12:00:00Z",
        },
    )
    package = store.create_record(
        "package",
        "MWT test package",
        {
            "stable_key": "mwt-test",
            "title": "MWT Test Package",
            "source_relpath": "10_Theory/MWT/Test",
            "manifest_sha256": "abc",
            "verification_state": "verified",
            "publication_state": "not_published",
            "content_languages": ["zh-Hant"],
        },
    )
    component = store.create_record(
        "component",
        "paper.md",
        {
            "title": "World Theory",
            "source_relpath": "paper.md",
            "parent_package_id": package["id"],
            "sha256": "def",
            "content_identity": "def",
            "content_languages": ["zh-Hant"],
            "dependency_mode": "independent",
            "verification_state": "verified",
            "publication_state": "candidate",
        },
    )
    store.create_record(
        "package_version_event",
        "first seen package",
        {
            "source_record_id": package["id"],
            "outcome": "first_seen",
            "temporal_anchor_id": anchor["id"],
        },
    )
    store.create_record(
        "component_version_event",
        "first seen component",
        {
            "source_record_id": component["id"],
            "outcome": "first_seen",
            "temporal_anchor_id": anchor["id"],
        },
    )
    store.create_relation(
        package["id"], "category:theory", "classified_as", anchor["id"]
    )
    store.create_relation(
        component["id"], "category:theory", "classified_as", anchor["id"]
    )
    return store


def test_catalog_export_is_deterministic_and_contains_discovery_metadata(
    store_with_records: CatalogStore,
) -> None:
    first = render_catalog(store_with_records)
    second = render_catalog(store_with_records)

    assert first == second
    assert "Auto-generated from SEDB" in first
    assert "MWT Test Package" in first
    assert "World Theory" in first
    assert "ctcl:instant:export-test" in first
    assert "2026-08-24T20:00:00+08:00" in first
    assert "zh-Hant" in first
    assert "source content" not in first


def test_unchanged_export_does_not_rewrite_file(
    store_with_records: CatalogStore, tmp_path: Path
) -> None:
    output = tmp_path / "ARTIFACT_CATALOG.md"
    first = write_catalog(store_with_records, output)
    fixed_ns = 1_700_000_000_000_000_000
    os.utime(output, ns=(fixed_ns, fixed_ns))

    second = write_catalog(store_with_records, output)

    assert first.changed is True
    assert second.changed is False
    assert output.stat().st_mtime_ns == fixed_ns


def test_complete_cli_surface_parses_without_network() -> None:
    parser = build_parser()

    assert parser.parse_args(["init"]).command == "init"
    assert parser.parse_args(["ingest"]).command == "ingest"
    assert parser.parse_args(["export"]).command == "export"
    assert (
        parser.parse_args(["reconcile-time"]).command == "reconcile-time"
    )


def test_init_and_empty_search_use_local_config(
    project_dir: Path, tmp_path: Path, capsys
) -> None:
    raw = json.loads(
        (project_dir / "catalog-config.json").read_text(encoding="utf-8")
    )
    raw["catalog_root"] = str(tmp_path / "staging")
    raw["database_path"] = "catalog.sqlite"
    raw["allowed_copy_roots"] = [str(tmp_path)]
    config_path = tmp_path / "catalog-config.json"
    config_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert main(["init", "--config", str(config_path)]) == 0
    capsys.readouterr()
    assert (
        tmp_path / "staging" / "40_Translation_Workspace"
    ).is_dir()
    assert main(
        ["search", "MWT", "--config", str(config_path)]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert output == []
