from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from catalog_fixtures import build_catalog_fixture
from fixtures import build_snapshot_fixture
from sedb.db import Database
from sedb.entities import EntityService


PROJECT_DIR = Path(__file__).resolve().parents[1]
SEDB_ROOT = PROJECT_DIR.parents[1]
DRIVER = """
import json
import os
from pathlib import Path
from catalog_config import CatalogContract
from cli import main
from config import ProjectConfig

config = ProjectConfig(
    source_root=Path(os.environ["WX_TEST_SOURCE_ROOT"]),
    database_path=Path(os.environ["WX_TEST_DB"]),
    expected_entity_counts=json.loads(os.environ["WX_TEST_COUNTS"]),
)
contract = CatalogContract(
    source_root=Path(os.environ["WX_CATALOG_SOURCE_ROOT"]),
    manifest_path=Path(os.environ["WX_CATALOG_MANIFEST"]),
    manifest_sha256=os.environ["WX_CATALOG_MANIFEST_SHA"],
    table_counts=json.loads(os.environ["WX_CATALOG_COUNTS"]),
    runtime_candidate_root=Path(os.environ["WX_CATALOG_RUNTIME_ROOT"]),
    runtime_candidate_count=int(os.environ["WX_CATALOG_RUNTIME_COUNT"]),
)
raise SystemExit(main(base_config=config, base_catalog_contract=contract))
"""


def prepared_cli_fixture(tmp_path, *, include_relation=False):
    wave1 = build_snapshot_fixture(
        tmp_path / "wave1-source",
        catalog_compatible=True,
    )
    catalog = build_catalog_fixture(
        tmp_path / "catalog-source",
        include_relation=include_relation,
    )
    return wave1, catalog, tmp_path / "catalog.sqlite"


def run_catalog_cli(wave1, catalog, database: Path, *args: str):
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(
                [
                    str(SEDB_ROOT / "current" / "src"),
                    str(PROJECT_DIR),
                    str(PROJECT_DIR / "tests"),
                ]
            ),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "WX_TEST_SOURCE_ROOT": str(wave1.root),
            "WX_TEST_DB": str(database),
            "WX_TEST_COUNTS": json.dumps(
                dict(wave1.config.expected_entity_counts),
                ensure_ascii=False,
            ),
            "WX_CATALOG_SOURCE_ROOT": str(catalog.contract.source_root),
            "WX_CATALOG_MANIFEST": str(catalog.contract.manifest_path),
            "WX_CATALOG_MANIFEST_SHA": catalog.contract.manifest_sha256,
            "WX_CATALOG_COUNTS": json.dumps(
                dict(catalog.contract.table_counts),
                ensure_ascii=False,
            ),
            "WX_CATALOG_RUNTIME_ROOT": str(
                catalog.contract.runtime_candidate_root
            ),
            "WX_CATALOG_RUNTIME_COUNT": str(
                catalog.contract.runtime_candidate_count
            ),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", DRIVER, *args],
        cwd=SEDB_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result, json.loads(result.stdout)


def test_catalog_plan_is_read_only_and_reports_bounded_counts(tmp_path):
    wave1, catalog, database = prepared_cli_fixture(tmp_path)

    result, payload = run_catalog_cli(
        wave1,
        catalog,
        database,
        "catalog-plan",
        "--build",
        "25006280",
    )

    assert result.returncode == 0
    assert payload["status"] == "ready"
    assert payload["pre_edge_entities"] == 16
    assert payload["edge_count"] == 7
    assert payload["full_entities"] == 23
    assert payload["new"] == 23
    assert payload["enrich"] == 0
    assert len(payload["new_entity_id_sample"]) <= 20
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0


def test_catalog_bootstrap_creates_once_then_both_scopes_are_no_op(tmp_path):
    wave1, catalog, database = prepared_cli_fixture(tmp_path)

    first, created = run_catalog_cli(
        wave1, catalog, database, "catalog-bootstrap", "--build", "25006280"
    )
    second, no_op = run_catalog_cli(
        wave1, catalog, database, "catalog-bootstrap", "--build", "25006280"
    )
    wave1_plan, old_scope = run_catalog_cli(
        wave1, catalog, database, "plan", "--build", "25006280"
    )

    assert first.returncode == 0
    assert created["status"] == "created"
    assert created["created_entities"] == 23
    assert second.returncode == 0
    assert no_op["status"] == "no_op"
    assert no_op["created_entities"] == 0
    assert no_op["enriched_entities"] == 0
    assert wave1_plan.returncode == 0
    assert old_scope["status"] == "ready"
    assert old_scope["new"] == 0
    assert old_scope["unchanged"] == 11


def test_catalog_queries_are_compact_and_full_show_is_explicit(tmp_path):
    wave1, catalog, database = prepared_cli_fixture(
        tmp_path,
        include_relation=True,
    )
    bootstrap, _ = run_catalog_cli(
        wave1, catalog, database, "catalog-bootstrap", "--build", "25006280"
    )
    assert bootstrap.returncode == 0

    table_result, table = run_catalog_cli(
        wave1, catalog, database, "table", "EventDialog", "--limit", "10"
    )
    one_result, one = run_catalog_cli(
        wave1, catalog, database, "table", "EventDialog", "--id", "10"
    )
    dialog_result, dialog = run_catalog_cli(
        wave1, catalog, database, "dialog", "10"
    )
    dialog_entity_id = one["results"][0]["id"]
    edge_result, edges = run_catalog_cli(
        wave1,
        catalog,
        database,
        "edges",
        dialog_entity_id,
        "--direction",
        "out",
    )
    route_result, route = run_catalog_cli(
        wave1, catalog, database, "route", "1"
    )

    assert table_result.returncode == one_result.returncode == 0
    assert table["count"] == 2
    assert one["count"] == 1
    assert all(
        "source_row_payload" not in record["values"]
        for record in table["results"]
    )
    assert dialog_result.returncode == 0
    assert dialog["entity"]["values"]["source_row_payload"]["Desc"] == "完整对话甲"
    assert edge_result.returncode == 0
    assert edges["count"] == 1
    assert edges["results"][0]["values"]["edge_source_field"] == "NextDialogId"
    assert route_result.returncode == 0
    assert route["entity"]["values"]["guide_steps"]["guide_steps"][0]["slot"] == 0
    assert route["edges"]["count"] == 4


def test_catalog_source_failure_exits_two_without_database_entities(tmp_path):
    wave1, catalog, database = prepared_cli_fixture(tmp_path)
    catalog.contract.manifest_path.write_bytes(
        catalog.contract.manifest_path.read_bytes() + b"\n"
    )

    result, payload = run_catalog_cli(
        wave1, catalog, database, "catalog-plan", "--build", "25006280"
    )

    assert result.returncode == 2
    assert payload["status"] == "error"
    assert payload["reason_code"] == "source_manifest_hash_mismatch"
    if database.exists():
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0


def test_catalog_conflict_exits_three_without_new_entities(tmp_path):
    wave1, catalog, database = prepared_cli_fixture(tmp_path)
    first, _ = run_catalog_cli(
        wave1, catalog, database, "catalog-bootstrap", "--build", "25006280"
    )
    assert first.returncode == 0
    db = Database(database)
    before = db.scalar("SELECT COUNT(*) FROM entities")
    EntityService(db).set_cell(
        "wx-build-25006280",
        "catalog_total_rows",
        999,
        source="tampered:test",
    )

    result, payload = run_catalog_cli(
        wave1, catalog, database, "catalog-bootstrap", "--build", "25006280"
    )

    assert result.returncode == 3
    assert payload["status"] == "blocked"
    assert payload["reason_code"] == "source_conflict"
    assert db.scalar("SELECT COUNT(*) FROM entities") == before


def test_catalog_bootstrap_backs_up_existing_wave1_before_expansion(tmp_path):
    wave1, catalog, database = prepared_cli_fixture(tmp_path)
    seeded, seed_payload = run_catalog_cli(
        wave1, catalog, database, "bootstrap", "--build", "25006280"
    )
    assert seeded.returncode == 0
    assert seed_payload["created_entities"] == 11

    result, payload = run_catalog_cli(
        wave1, catalog, database, "catalog-bootstrap", "--build", "25006280"
    )

    backup = database.parent / "local-backups" / "wave1-25006280.sqlite"
    assert result.returncode == 0
    assert backup.is_file()
    assert payload["backup"]["path"] == str(backup)
    assert len(payload["backup"]["sha256"]) == 64
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 11
