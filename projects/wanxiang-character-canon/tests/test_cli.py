from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fixtures import ART_CHECKPOINT, build_snapshot_fixture
from schema import FIELD_SPECS, VIEW_SPECS
from sedb.db import Database
from sedb.entities import EntityService
from source import load_snapshot


PROJECT_DIR = Path(__file__).resolve().parents[1]
SEDB_ROOT = PROJECT_DIR.parents[1]
DRIVER = """
import json
import os
from pathlib import Path
from cli import main
from config import ProjectConfig

config = ProjectConfig(
    source_root=Path(os.environ["WX_TEST_SOURCE_ROOT"]),
    database_path=Path(os.environ["WX_TEST_DB"]),
    expected_entity_counts=json.loads(os.environ["WX_TEST_COUNTS"]),
)
raise SystemExit(main(base_config=config))
"""


def run_cli(fixture, database: Path, *args: str):
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(
                [str(SEDB_ROOT / "current" / "src"), str(PROJECT_DIR)]
            ),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "WX_TEST_SOURCE_ROOT": str(fixture.root),
            "WX_TEST_DB": str(database),
            "WX_TEST_COUNTS": json.dumps(
                dict(fixture.config.expected_entity_counts),
                ensure_ascii=False,
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
    payload = json.loads(result.stdout)
    return result, payload


def test_init_reports_exact_field_view_counts_and_integrity(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"

    result, payload = run_cli(
        fixture,
        database,
        "--source-root",
        str(fixture.root),
        "--db",
        str(database),
        "init",
    )

    assert result.returncode == 0
    assert payload["status"] == "initialized"
    assert payload["fields_created"] == len(FIELD_SPECS)
    assert payload["views_created"] == len(VIEW_SPECS)
    assert payload["integrity"] == "ok"


def test_plan_is_read_only_for_entities(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"

    result, payload = run_cli(
        fixture,
        database,
        "plan",
        "--build",
        "25006280",
    )

    assert result.returncode == 0
    assert payload["status"] == "ready"
    assert payload["new"] == 11
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0


def test_bootstrap_creates_once_then_returns_no_op(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"

    first, created = run_cli(
        fixture,
        database,
        "bootstrap",
        "--build",
        "25006280",
    )
    second, no_op = run_cli(
        fixture,
        database,
        "bootstrap",
        "--build",
        "25006280",
    )

    assert first.returncode == 0
    assert created["status"] == "created"
    assert created["created_entities"] == 11
    assert created["created_cells"] > 11
    assert second.returncode == 0
    assert no_op["status"] == "no_op"
    assert no_op["created_entities"] == 0


def test_blocked_bootstrap_exits_three_without_new_entities(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"
    first, _ = run_cli(fixture, database, "bootstrap", "--build", "25006280")
    assert first.returncode == 0
    selection = load_snapshot(fixture.config)
    build = next(
        entity
        for entity in selection.entities
        if entity.kind == "wanxiang_build_snapshot"
    )
    db = Database(database)
    EntityService(db).set_cell(
        build.entity_id,
        "snapshot_status",
        "TAMPERED",
        source="test:tamper",
    )
    before = db.scalar("SELECT COUNT(*) FROM entities")

    blocked, payload = run_cli(
        fixture,
        database,
        "bootstrap",
        "--build",
        "25006280",
    )

    assert blocked.returncode == 3
    assert payload["status"] == "blocked"
    assert payload["reason_code"] == "source_conflict"
    assert db.scalar("SELECT COUNT(*) FROM entities") == before


def test_invalid_source_exits_two_with_reason_code(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"
    fixture.mutate_json(
        "art-engineering/inventory/build-25006280/role-targets.json",
        lambda value: value.update(schema="invalid/v1"),
        refresh_checkpoint=ART_CHECKPOINT,
    )

    result, payload = run_cli(
        fixture,
        database,
        "plan",
        "--build",
        "25006280",
    )

    assert result.returncode == 2
    assert payload["status"] == "error"
    assert payload["reason_code"] == "unsupported_schema"


def test_search_expands_stored_identity_form_and_asset_links(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"
    bootstrap, _ = run_cli(fixture, database, "bootstrap", "--build", "25006280")
    assert bootstrap.returncode == 0

    result, payload = run_cli(fixture, database, "search", "万轻舟")

    assert result.returncode == 0
    assert payload["status"] == "ok"
    kinds = {record["kind"] for record in payload["results"]}
    assert "wanxiang_character_identity" in kinds
    assert "wanxiang_character_form_snapshot" in kinds
    assert "wanxiang_visual_asset_snapshot" in kinds


def test_show_returns_sparse_cells_and_stored_links(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"
    bootstrap, _ = run_cli(fixture, database, "bootstrap", "--build", "25006280")
    assert bootstrap.returncode == 0
    selection = load_snapshot(fixture.config)
    identity = next(
        entity
        for entity in selection.entities
        if entity.kind == "wanxiang_character_identity"
    )

    result, payload = run_cli(fixture, database, "show", identity.entity_id)

    assert result.returncode == 0
    assert payload["status"] == "ok"
    assert payload["entity"]["id"] == identity.entity_id
    assert payload["entity"]["values"]["normalized_name_key"] == "万轻舟"
    assert payload["entity"]["cells"]["normalized_name_key"]["source"].startswith(
        "wanxiang:"
    )
    assert len(payload["links"]["forms"]) == 2
    assert payload["links"]["assets"]


def test_unresolved_lists_gap_and_ambiguous_candidate(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    database = tmp_path / "canon.sqlite"
    bootstrap, _ = run_cli(fixture, database, "bootstrap", "--build", "25006280")
    assert bootstrap.returncode == 0

    result, payload = run_cli(fixture, database, "unresolved")

    assert result.returncode == 0
    assert payload["status"] == "ok"
    assert {record["kind"] for record in payload["results"]} == {
        "wanxiang_source_gap_snapshot",
        "wanxiang_visual_candidate_snapshot",
    }
