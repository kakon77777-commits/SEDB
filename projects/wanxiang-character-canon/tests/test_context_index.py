from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cli as cli_module
from config import ProjectConfig
from context_index import (
    ContextIndexError,
    build_context_index,
    build_sedb_pointer,
    validate_context_links,
    write_context_index,
)


REPORT_NAMES = (
    "character-coverage",
    "event-network",
    "choice-consequence",
    "time-pacing",
    "relationship-routes",
    "combat-progression",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _context_fixture(tmp_path):
    repository = tmp_path / "repo"
    project = repository / "projects" / "wanxiang-character-canon"
    research = tmp_path / "research"
    output = research / "analysis" / "sedb-wave2-4"
    database = project / "wanxiang-character-canon.sqlite"
    paths = (
        project / "README.md",
        project / "VERIFY.md",
        project / "evidence" / "full-catalog-acceptance.json",
        project / "evidence" / "gameplay-analysis-acceptance.json",
        repository
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-08-30-wanxiang-full-static-canon-and-gameplay-analysis-design.md",
        repository
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-08-30-wanxiang-full-static-canon-and-gameplay-analysis.md",
        research / "evidence" / "source-inventory" / "current-verification.manifest.json",
        research / "art-engineering" / "README.md",
        research / "art-engineering" / "registry" / "characters.json",
        research / "inputs" / "visual-anchors" / "positive" / "ANCHORS.md",
        research / "inputs" / "methodology-papers" / "2026-08-30" / "README.md",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    all_excel = (
        research
        / "baseline"
        / "game"
        / "wanxiang"
        / "wanxiang"
        / "ModDocs"
        / "AllExcel"
    )
    all_excel.mkdir(parents=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    database.write_bytes(b"fixture database")
    output.mkdir(parents=True)
    report_entries = []
    report_hashes = {}
    for name in REPORT_NAMES:
        json_path = output / f"{name}.json"
        markdown_path = output / f"{name}.md"
        json_path.write_text(json.dumps({"analysis_name": name}), encoding="utf-8")
        markdown_path.write_text(f"# {name}\n", encoding="utf-8")
        report_entries.append(
            {"analysis_name": name, "json": json_path.name, "markdown": markdown_path.name}
        )
        report_hashes[json_path.name] = _sha256(json_path)
        report_hashes[markdown_path.name] = _sha256(markdown_path)
    manifest = {
        "schema": "wanxiang-static-gameplay-manifest/v1",
        "build_id": 25006280,
        "catalog_fingerprint": "F" * 64,
        "catalog_source_fingerprint": "C" * 64,
        "database_sha256": "D" * 64,
        "reference_rule_version": "wanxiang-reference-rules/v1",
        "reports": report_entries,
        "sha256_by_path": report_hashes,
        "not_measured": ["Runtime reachability."],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    full_catalog = {
        "status": "FULL_STATIC_DATABASE_ACCEPTED",
        "build_id": 25006280,
        "source": {
            "manifest_sha256": "M" * 64,
            "catalog_fingerprint": "F" * 64,
            "reader_version": "wanxiang-openxml/v1",
            "reference_rule_version": "wanxiang-reference-rules/v1",
            "tables": 36,
            "source_rows": 29939,
            "event_dialog_rows": 17210,
            "runtime_candidate_files": 52,
        },
        "database": {
            "path": str(database),
            "sha256": "D" * 64,
            "entities": 71753,
            "cells": 1102664,
            "fields": 174,
            "views": 19,
            "per_kind": {
                "wanxiang_visual_candidate_snapshot": 172,
                "wanxiang_source_gap_snapshot": 8,
                "wanxiang_reference_edge_snapshot": 40075,
            },
            "edge_statuses": {
                "resolved": 31117,
                "missing_target": 8958,
                "unknown_semantics": 0,
            },
        },
        "not_measured": [
            "Runtime ownership.",
            "Gameplay-analysis reports and the final AI context index; those are later accepted tasks.",
        ],
    }
    gameplay = {
        "status": "STATIC_GAMEPLAY_REPORTS_ACCEPTED",
        "build_id": 25006280,
        "reports": {
            "output_root": str(output),
            "manifest_sha256": _sha256(output / "manifest.json"),
        },
        "headline_metrics": {
            "choice_consequence": {"missing_event_destinations": 89}
        },
        "not_measured": [
            "Player fun.",
            "Final AI context index acceptance; this is Task 9.",
        ],
    }
    evidence = {
        "full_catalog": full_catalog,
        "gameplay": gameplay,
        "repository_root": str(repository),
        "project_root": str(project),
        "verification_basis": {
            "commit": "1" * 40,
            "tree": "2" * 40,
        },
    }
    config = ProjectConfig(
        source_root=research,
        database_path=database,
        build_id=25006280,
        namespace="wanxiang_character_canon",
        expected_entity_counts={},
    )
    return config, evidence, manifest, project, output


def test_context_index_has_complete_machine_schema_and_fast_reading_order(tmp_path):
    config, evidence, manifest, _, _ = _context_fixture(tmp_path)

    index = build_context_index(config, evidence, manifest)

    required = {
        "schema",
        "build_id",
        "verification_basis",
        "fingerprints",
        "counts",
        "paths",
        "reports",
        "query_recipes",
        "unresolved",
        "statuses",
        "not_measured",
        "next_work",
        "reading_order",
        "authority_ranking",
        "link_targets",
    }
    assert required <= set(index.payload)
    assert len(index.payload["reading_order"]) == 6
    assert index.payload["verification_basis"] == {
        "commit": "1" * 40,
        "tree": "2" * 40,
    }
    assert index.payload["counts"]["source_rows"] == 29939
    assert index.payload["counts"]["entities"] == 71753
    assert index.payload["unresolved"]["missing_reference_targets"] == 8958
    assert index.payload["statuses"]["runtime"] == "NOT_MEASURED"
    assert index.payload["statuses"]["overall"] == "WANXIANG_FULL_STATIC_CANON_PASS"
    assert not any(
        "context index" in item.casefold() for item in index.payload["not_measured"]
    )
    first_120 = "\n".join(
        line for line in index.human_markdown.splitlines() if line.strip()
    ).splitlines()[:120]
    joined = "\n".join(first_120)
    assert "## 六步閱讀順序" in joined
    assert "## 權威順序" in joined
    assert "## 如何刷新" in joined


def test_single_canonical_index_pointer_and_link_validation(tmp_path):
    config, evidence, manifest, project, output = _context_fixture(tmp_path)
    index = build_context_index(config, evidence, manifest)

    written = write_context_index(index, config, project_root=project)
    pointer = build_sedb_pointer(config, project_root=project)
    checks = validate_context_links(index)

    assert written["canonical_human"].is_file()
    assert written["machine_json"].is_file()
    assert written["sedb_pointer"].read_text(encoding="utf-8") == pointer
    assert all(check.exists for check in checks)
    assert "AI_CONTEXT_INDEX.md" in pointer
    assert "context-index.json" in pointer
    assert "context_index.py' refresh" in pointer
    assert "python '" in pointer
    assert "evidence boundary" in pointer.casefold()
    assert "25006280" not in pointer
    assert "29939" not in pointer
    assert "F" * 64 not in pointer
    assert "character-coverage" not in pointer

    (output / "event-network.md").unlink()
    failed = [check for check in validate_context_links(index) if not check.exists]
    assert len(failed) == 1
    assert failed[0].path.endswith("event-network.md")


def test_context_index_cli_is_read_only_and_reason_codes_stale_links(
    tmp_path, capsys, monkeypatch
):
    config, _, _, _, _ = _context_fixture(tmp_path)
    monkeypatch.setattr(
        cli_module,
        "validate_default_context_index",
        lambda _: {
            "status": "ok",
            "build_id": 25006280,
            "link_checks": 25,
            "report_count": 6,
        },
        raising=False,
    )

    success = cli_module.main(["context-index"], base_config=config)
    payload = json.loads(capsys.readouterr().out)

    assert success == 0
    assert payload["status"] == "ok"
    assert payload["link_checks"] == 25

    def stale(_):
        raise ContextIndexError(
            "context_link_validation_failed", "one local link is stale"
        )

    monkeypatch.setattr(
        cli_module,
        "validate_default_context_index",
        stale,
        raising=False,
    )
    failed = cli_module.main(["context-index"], base_config=config)
    error = json.loads(capsys.readouterr().out)

    assert failed == 4
    assert error["reason_code"] == "context_link_validation_failed"
