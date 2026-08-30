from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from config import ProjectConfig, default_config


CONTEXT_SCHEMA = "wanxiang-ai-context-index/v1"
PROJECT_NAME = "wanxiang-character-canon"
REPORT_NAMES = (
    "character-coverage",
    "event-network",
    "choice-consequence",
    "time-pacing",
    "relationship-routes",
    "combat-progression",
)


class ContextIndexError(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ContextIndex:
    payload: dict[str, Any]
    human_markdown: str


@dataclass(frozen=True)
class LinkCheck:
    path: str
    exists: bool
    reason: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_json(path: Path, *, reason_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContextIndexError(
            reason_code,
            f"cannot read context evidence {path}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise ContextIndexError(reason_code, f"context evidence is not an object: {path}")
    return payload


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ContextIndexError(
            "context_evidence_invalid",
            f"context evidence requires object {key}",
        )
    return value


def _require_match(label: str, *values: Any) -> Any:
    if not values or any(value != values[0] for value in values[1:]):
        raise ContextIndexError(
            "context_evidence_mismatch",
            f"context evidence disagrees on {label}: {values}",
        )
    return values[0]


def _markdown_path(path: str) -> str:
    normalized = Path(path).as_posix()
    return f"<{normalized}>" if " " in normalized else normalized


def _human_markdown(payload: Mapping[str, Any]) -> str:
    paths = payload["paths"]
    counts = payload["counts"]
    fingerprints = payload["fingerprints"]
    unresolved = payload["unresolved"]
    lines = [
        "# 萬象群俠傳 AI 快速上下文索引",
        "",
        f"目前狀態：`{payload['statuses']['overall']}`；BuildID `{payload['build_id']}`。",
        "本索引是靜態資料與分析的唯一完整人工入口，目標是在約 90 秒內恢復工作上下文。",
        "",
        "## 六步閱讀順序",
        "",
    ]
    for ordinal, item in enumerate(payload["reading_order"], 1):
        lines.append(
            f"{ordinal}. [{item['label']}]({_markdown_path(item['path'])}) — {item['purpose']}"
        )
    lines.extend(
        [
            "",
            "## 權威順序",
            "",
        ]
    )
    for item in payload["authority_ranking"]:
        lines.append(f"{item['rank']}. **{item['layer']}** — {item['boundary']}")
    lines.extend(
        [
            "",
            "## 如何刷新",
            "",
            "不要沿用本頁的舊數字來推定新版本。先重新驗證來源 manifest、資料庫與報告，再重建索引：",
            "",
            "```powershell",
            "cd 'D:\\Ai\\work together\\SEDB'",
            "$env:PYTHONPATH = 'current\\src;projects\\wanxiang-character-canon'",
            "python projects\\wanxiang-character-canon\\context_index.py refresh",
            "python projects\\wanxiang-character-canon\\cli.py context-index",
            "```",
            "",
            "若 BuildID、來源 hash、DB hash、報告 hash 或連結不一致，狀態必須降回 stale/blocked，不可手動改字樣冒充驗收。",
            "",
            "## 已驗收快照",
            "",
            "| 項目 | 值 |",
            "| --- | ---: |",
            f"| AllExcel 表 / 列 | {counts['source_tables']} / {counts['source_rows']} |",
            f"| EventDialog 列 | {counts['event_dialog_rows']} |",
            f"| Entities / Cells | {counts['entities']} / {counts['cells']} |",
            f"| Fields / Views | {counts['fields']} / {counts['views']} |",
            f"| Reference edges | {counts['reference_edges']} |",
            f"| Gameplay reports | {counts['gameplay_reports_json']} JSON + {counts['gameplay_reports_markdown']} Markdown |",
            "",
            f"- DB：[{paths['database']}]({_markdown_path(paths['database'])})",
            f"- Catalog fingerprint：`{fingerprints['catalog']}`",
            f"- Catalog source fingerprint：`{fingerprints['catalog_source']}`",
            f"- Database SHA-256：`{fingerprints['database']}`",
            f"- Source manifest SHA-256：`{fingerprints['source_manifest']}`",
            f"- Report manifest SHA-256：`{fingerprints['gameplay_manifest']}`",
            f"- Reference rules：`{fingerprints['reference_rule_version']}`",
            "",
            "## 六份靜態玩法分析",
            "",
        ]
    )
    for report in payload["reports"]:
        lines.append(
            f"- **{report['analysis_name']}**："
            f"[Markdown]({_markdown_path(report['markdown'])}) / "
            f"[JSON]({_markdown_path(report['json'])})"
        )
    lines.extend(
        [
            "",
            "所有報告都把 `OBSERVED / INFERRED / UNKNOWN / FALSIFYING_TEST` 分開；靜態 root、terminal、missing target 或文字命中均不等於 runtime 可達性、頻率、平衡或好玩。",
            "",
            "## 未解與缺口",
            "",
            f"- 靜態引用 missing target：{unresolved['missing_reference_targets']}。",
            f"- 靜態引用 unknown semantics：{unresolved['unknown_reference_semantics']}。",
            f"- 視覺候選未自動定案：{unresolved['visual_candidates']}。",
            f"- Wave 1 source gaps：{unresolved['source_gaps']}。",
            f"- EventSelection 指向缺失 Event 的選項：{unresolved['missing_selection_destinations']}。",
            "",
            "## 常用查詢",
            "",
        ]
    )
    for recipe in payload["query_recipes"]:
        lines.extend(
            [
                f"### {recipe['purpose']}",
                "",
                "```powershell",
                recipe["command"],
                "```",
                "",
            ]
        )
    lines.extend(["## 下一步路由", ""])
    for route in payload["next_work"]:
        lines.append(
            f"- **{route['track']}**：{route['next_action']} 入口："
            f"[{route['entry_label']}]({_markdown_path(route['entry_path'])})"
        )
    lines.extend(["", "## NotMeasured", ""])
    lines.extend(f"- {item}" for item in payload["not_measured"])
    lines.extend(
        [
            "",
            "## 驗證基礎",
            "",
            f"- Commit：`{payload['verification_basis']['commit']}`",
            f"- Tree：`{payload['verification_basis']['tree']}`",
            f"- SEDB 驗證說明：[{paths['verification']}]({_markdown_path(paths['verification'])})",
            f"- 機器索引：[{paths['machine_index']}]({_markdown_path(paths['machine_index'])})",
            "",
        ]
    )
    return "\n".join(lines)


def build_context_index(
    config: ProjectConfig,
    evidence: Mapping[str, Any],
    report_manifest: Mapping[str, Any],
) -> ContextIndex:
    full = _require_mapping(evidence, "full_catalog")
    gameplay = _require_mapping(evidence, "gameplay")
    basis = _require_mapping(evidence, "verification_basis")
    source = _require_mapping(full, "source")
    database = _require_mapping(full, "database")
    report_evidence = _require_mapping(gameplay, "reports")
    edge_statuses = _require_mapping(database, "edge_statuses")
    per_kind = _require_mapping(database, "per_kind")
    headline = _require_mapping(gameplay, "headline_metrics")

    build_id = _require_match(
        "BuildID",
        config.build_id,
        full.get("build_id"),
        gameplay.get("build_id"),
        report_manifest.get("build_id"),
    )
    catalog_fingerprint = _require_match(
        "catalog fingerprint",
        source.get("catalog_fingerprint"),
        report_manifest.get("catalog_fingerprint"),
    )
    database_sha256 = _require_match(
        "database SHA-256",
        database.get("sha256"),
        report_manifest.get("database_sha256"),
    )
    rule_version = _require_match(
        "reference rule version",
        source.get("reference_rule_version"),
        report_manifest.get("reference_rule_version"),
    )
    commit = str(basis.get("commit", ""))
    tree = str(basis.get("tree", ""))
    if len(commit) != 40 or len(tree) != 40:
        raise ContextIndexError(
            "verification_basis_invalid",
            "verification basis requires 40-character commit and tree IDs",
        )

    repository = Path(str(evidence.get("repository_root", ""))).resolve()
    project = Path(str(evidence.get("project_root", ""))).resolve()
    research = config.source_root.resolve()
    output = Path(str(report_evidence.get("output_root", ""))).resolve()
    canonical_human = research / "AI_CONTEXT_INDEX.md"
    machine_index = output / "context-index.json"
    sedb_pointer = project / "AI_CONTEXT_INDEX.md"
    report_manifest_path = output / "manifest.json"
    if not report_manifest_path.is_file():
        raise ContextIndexError(
            "report_manifest_missing",
            f"gameplay report manifest is missing: {report_manifest_path}",
        )
    if _sha256(report_manifest_path) != str(
        report_evidence.get("manifest_sha256", "")
    ).upper():
        raise ContextIndexError(
            "report_manifest_hash_mismatch",
            "gameplay report manifest hash does not match accepted evidence",
        )

    manifest_reports = report_manifest.get("reports")
    manifest_hashes = report_manifest.get("sha256_by_path")
    if not isinstance(manifest_reports, list) or not isinstance(manifest_hashes, Mapping):
        raise ContextIndexError(
            "report_manifest_invalid",
            "gameplay report manifest requires reports and sha256_by_path",
        )
    reports = []
    observed_names = []
    for item in manifest_reports:
        if not isinstance(item, Mapping):
            raise ContextIndexError("report_manifest_invalid", "invalid report entry")
        name = str(item.get("analysis_name", ""))
        json_path = output / str(item.get("json", ""))
        markdown_path = output / str(item.get("markdown", ""))
        observed_names.append(name)
        for path in (json_path, markdown_path):
            expected = str(manifest_hashes.get(path.name, "")).upper()
            if not path.is_file() or _sha256(path) != expected:
                raise ContextIndexError(
                    "gameplay_report_hash_mismatch",
                    f"gameplay report is missing or stale: {path}",
                )
        reports.append(
            {
                "analysis_name": name,
                "json": str(json_path),
                "markdown": str(markdown_path),
                "json_sha256": str(manifest_hashes[json_path.name]).upper(),
                "markdown_sha256": str(manifest_hashes[markdown_path.name]).upper(),
            }
        )
    if tuple(observed_names) != REPORT_NAMES:
        raise ContextIndexError(
            "gameplay_report_set_mismatch",
            f"expected reports {REPORT_NAMES}, got {tuple(observed_names)}",
        )

    paths = {
        "canonical_human": str(canonical_human),
        "machine_index": str(machine_index),
        "sedb_pointer": str(sedb_pointer),
        "sedb_project": str(project),
        "database": str(config.database_path.resolve()),
        "readme": str(project / "README.md"),
        "verification": str(project / "VERIFY.md"),
        "full_catalog_evidence": str(
            project / "evidence" / "full-catalog-acceptance.json"
        ),
        "gameplay_evidence": str(
            project / "evidence" / "gameplay-analysis-acceptance.json"
        ),
        "design_spec": str(
            repository
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-08-30-wanxiang-full-static-canon-and-gameplay-analysis-design.md"
        ),
        "implementation_plan": str(
            repository
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-08-30-wanxiang-full-static-canon-and-gameplay-analysis.md"
        ),
        "source_manifest": str(
            research
            / "evidence"
            / "source-inventory"
            / "current-verification.manifest.json"
        ),
        "all_excel_root": str(
            research
            / "baseline"
            / "game"
            / "wanxiang"
            / "wanxiang"
            / "ModDocs"
            / "AllExcel"
        ),
        "report_manifest": str(report_manifest_path),
        "art_engineering": str(research / "art-engineering" / "README.md"),
        "character_registry": str(
            research / "art-engineering" / "registry" / "characters.json"
        ),
        "visual_anchors": str(
            research / "inputs" / "visual-anchors" / "positive" / "ANCHORS.md"
        ),
        "methodology_papers": str(
            research
            / "inputs"
            / "methodology-papers"
            / "2026-08-30"
            / "README.md"
        ),
    }
    cli_prefix = "python projects\\wanxiang-character-canon\\cli.py"
    query_recipes = [
        {"purpose": "資料庫與 kind 統計", "command": f"{cli_prefix} stats"},
        {"purpose": "人物／名稱查詢", "command": f"{cli_prefix} search 萬輕舟"},
        {"purpose": "表格定位", "command": f"{cli_prefix} table Event --id VALUE"},
        {"purpose": "完整對話列", "command": f"{cli_prefix} dialog DIALOG_ID"},
        {"purpose": "關係路線與引用", "command": f"{cli_prefix} route RELATION_ID"},
        {"purpose": "重新驗證靜態報告", "command": f"{cli_prefix} gameplay-report all"},
    ]
    choice_metrics = headline.get("choice_consequence", {})
    if not isinstance(choice_metrics, Mapping):
        choice_metrics = {}
    historical_stale_markers = (
        "gameplay-analysis reports and the final ai context index",
        "final ai context index acceptance",
    )
    not_measured = [
        item
        for item in dict.fromkeys(
            [
                *full.get("not_measured", []),
                *gameplay.get("not_measured", []),
                *report_manifest.get("not_measured", []),
                "Foreground game runtime, live saves, RNG order, balance, and player-fun acceptance.",
                "DAT runtime ownership/parity and live MOD loading or save migration.",
                "Push, publication, deployment, or release.",
            ]
        )
        if not any(marker in str(item).casefold() for marker in historical_stale_markers)
    ]
    reading_order = [
        {"label": "本頁", "path": str(canonical_human), "purpose": "90 秒恢復全局與邊界"},
        {"label": "驗證說明", "path": paths["verification"], "purpose": "確認最新接受狀態與 NotMeasured"},
        {"label": "機器索引", "path": str(machine_index), "purpose": "取得精確路徑、hash、計數與路由"},
        {"label": "玩法報告 manifest", "path": str(report_manifest_path), "purpose": "核對六份報告及逐檔 SHA"},
        {"label": "SEDB 專案說明", "path": paths["readme"], "purpose": "取得 CLI 與資料庫操作方式"},
        {"label": "美術工程入口", "path": paths["art_engineering"], "purpose": "接續人物圖解構、錨點與未來重構"},
    ]
    authority_ranking = [
        {"rank": 1, "layer": "Frozen shipped evidence", "boundary": "manifest-gated ModDocs/AllExcel 與來源 hash，是本階段最高靜態權威。"},
        {"rank": 2, "layer": "Accepted SEDB", "boundary": "由凍結來源單向重建；DB hash、完整性、列數與圖規則均需吻合。"},
        {"rank": 3, "layer": "Static analysis reports", "boundary": "由已驗收 DB 派生，可回答分布與顯式引用，不能回答 runtime 可達性或好玩。"},
        {"rank": 4, "layer": "Art extraction and anchors", "boundary": "可定位原圖與風格方向；不自動寫回遊戲、不自動成為策展定論。"},
        {"rank": 5, "layer": "ModTools / Workshop overlays", "boundary": "混合或外部來源，必須分層；不得默認併入官方 base canon。"},
        {"rank": 6, "layer": "Future runtime observation", "boundary": "目前 NotMeasured；只能在另行核准、隔離、可回復的測試副本中建立。"},
    ]
    next_work = [
        {"track": "遊戲設計", "next_action": "以六份靜態報告選出高 CP 值假說，再建立隔離 runtime 觀察矩陣。", "entry_label": "玩法報告 manifest", "entry_path": str(report_manifest_path)},
        {"track": "MOD 工程", "next_action": "研究官方 ModTools、資料覆蓋規則、封裝與最小可逆測試 MOD。", "entry_label": "AllExcel source", "entry_path": paths["all_excel_root"]},
        {"track": "人物美術", "next_action": "以角色 registry、原圖與正向錨點做角色區辨度重構。", "entry_label": "美術工程", "entry_path": paths["art_engineering"]},
        {"track": "版本刷新", "next_action": "新 Build 先重做 manifest/plan，不沿用舊計數或 hash。", "entry_label": "來源 manifest", "entry_path": paths["source_manifest"]},
    ]
    link_targets = sorted(
        {
            *paths.values(),
            *(report["json"] for report in reports),
            *(report["markdown"] for report in reports),
            *(item["entry_path"] for item in next_work),
        },
        key=str.casefold,
    )
    payload = {
        "schema": CONTEXT_SCHEMA,
        "build_id": build_id,
        "verification_basis": {"commit": commit, "tree": tree},
        "fingerprints": {
            "source_manifest": source.get("manifest_sha256"),
            "catalog": catalog_fingerprint,
            "catalog_source": report_manifest.get("catalog_source_fingerprint"),
            "database": database_sha256,
            "gameplay_manifest": report_evidence.get("manifest_sha256"),
            "reference_rule_version": rule_version,
        },
        "counts": {
            "source_tables": source.get("tables"),
            "source_rows": source.get("source_rows"),
            "event_dialog_rows": source.get("event_dialog_rows"),
            "runtime_candidate_files": source.get("runtime_candidate_files"),
            "entities": database.get("entities"),
            "cells": database.get("cells"),
            "fields": database.get("fields"),
            "views": database.get("views"),
            "reference_edges": per_kind.get("wanxiang_reference_edge_snapshot"),
            "gameplay_reports_json": len(reports),
            "gameplay_reports_markdown": len(reports),
        },
        "paths": paths,
        "reports": reports,
        "query_recipes": query_recipes,
        "unresolved": {
            "missing_reference_targets": edge_statuses.get("missing_target"),
            "unknown_reference_semantics": edge_statuses.get("unknown_semantics"),
            "visual_candidates": per_kind.get("wanxiang_visual_candidate_snapshot"),
            "source_gaps": per_kind.get("wanxiang_source_gap_snapshot"),
            "missing_selection_destinations": choice_metrics.get(
                "missing_event_destinations"
            ),
        },
        "statuses": {
            "overall": "WANXIANG_FULL_STATIC_CANON_PASS",
            "database": full.get("status"),
            "gameplay_reports": gameplay.get("status"),
            "runtime": "NOT_MEASURED",
            "mod_package": "NOT_BUILT",
            "publication": "NOT_AUTHORIZED",
        },
        "not_measured": not_measured,
        "next_work": next_work,
        "reading_order": reading_order,
        "authority_ranking": authority_ranking,
        "link_targets": link_targets,
    }
    return ContextIndex(payload=payload, human_markdown=_human_markdown(payload))


def build_sedb_pointer(
    config: ProjectConfig,
    *,
    project_root: Path | None = None,
) -> str:
    project = project_root or Path(__file__).resolve().parent
    canonical = config.source_root.resolve() / "AI_CONTEXT_INDEX.md"
    machine = (
        config.source_root.resolve()
        / "analysis"
        / "sedb-wave2-4"
        / "context-index.json"
    )
    return "\n".join(
        [
            "# Wanxiang AI context discovery pointer",
            "",
            "Purpose: direct compacted contexts and other AIs to the single canonical Wanxiang research index.",
            "",
            f"- Canonical human index: `{canonical}`",
            f"- Machine index: `{machine}`",
            "",
            "Refresh command:",
            "",
            "```powershell",
            "cd 'D:\\Ai\\work together\\SEDB'",
            "$env:PYTHONPATH = 'current\\src;projects\\wanxiang-character-canon'",
            f"python '{project / 'context_index.py'}' refresh",
            "python projects\\wanxiang-character-canon\\cli.py context-index",
            "```",
            "",
            "Evidence boundary: this pointer deliberately contains no changing counts, fingerprints, or report summaries. Read and validate the canonical and machine indexes instead.",
            "",
        ]
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_context_index(
    index: ContextIndex,
    config: ProjectConfig,
    *,
    project_root: Path | None = None,
) -> dict[str, Path]:
    project = (project_root or Path(__file__).resolve().parent).resolve()
    canonical = config.source_root.resolve() / "AI_CONTEXT_INDEX.md"
    machine = (
        config.source_root.resolve()
        / "analysis"
        / "sedb-wave2-4"
        / "context-index.json"
    )
    pointer = project / "AI_CONTEXT_INDEX.md"
    expected = index.payload.get("paths", {})
    if expected.get("canonical_human") != str(canonical) or expected.get(
        "machine_index"
    ) != str(machine) or expected.get("sedb_pointer") != str(pointer):
        raise ContextIndexError(
            "context_output_path_mismatch",
            "context payload output paths do not match the authorized locations",
        )
    _atomic_write(canonical, index.human_markdown)
    _atomic_write(
        machine,
        json.dumps(
            index.payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )
    _atomic_write(pointer, build_sedb_pointer(config, project_root=project))
    return {
        "canonical_human": canonical,
        "machine_json": machine,
        "sedb_pointer": pointer,
    }


def validate_context_links(index: ContextIndex) -> tuple[LinkCheck, ...]:
    checks = []
    seen = set()
    for raw_path in index.payload.get("link_targets", []):
        path = str(raw_path)
        key = os.path.normcase(str(Path(path).resolve()))
        if key in seen:
            continue
        seen.add(key)
        exists = Path(path).exists()
        checks.append(
            LinkCheck(
                path=path,
                exists=exists,
                reason="ok" if exists else "missing_local_link_target",
            )
        )
    return tuple(checks)


def _verification_basis(repository: Path, project: Path) -> dict[str, str]:
    evidence_path = project / "evidence" / "gameplay-analysis-acceptance.json"
    try:
        commit = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%H",
                "--",
                str(evidence_path.relative_to(repository)),
            ],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", f"{commit}^{{tree}}"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise ContextIndexError(
            "verification_basis_unavailable",
            f"cannot resolve gameplay evidence commit/tree: {exc}",
        ) from exc
    return {"commit": commit, "tree": tree}


def load_default_context_inputs(
    config: ProjectConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project = Path(__file__).resolve().parent
    repository = project.parents[1]
    full = _read_json(
        project / "evidence" / "full-catalog-acceptance.json",
        reason_code="full_catalog_evidence_unreadable",
    )
    gameplay = _read_json(
        project / "evidence" / "gameplay-analysis-acceptance.json",
        reason_code="gameplay_evidence_unreadable",
    )
    manifest = _read_json(
        config.source_root / "analysis" / "sedb-wave2-4" / "manifest.json",
        reason_code="gameplay_manifest_unreadable",
    )
    evidence = {
        "full_catalog": full,
        "gameplay": gameplay,
        "repository_root": str(repository),
        "project_root": str(project),
        "verification_basis": _verification_basis(repository, project),
    }
    return evidence, manifest


def refresh_default_context_index(config: ProjectConfig) -> dict[str, Any]:
    evidence, manifest = load_default_context_inputs(config)
    index = build_context_index(config, evidence, manifest)
    written = write_context_index(index, config)
    checks = validate_context_links(index)
    failures = [check for check in checks if not check.exists]
    if failures:
        raise ContextIndexError(
            "context_link_validation_failed",
            f"generated context has {len(failures)} missing link targets",
        )
    return {
        "status": "created",
        "build_id": index.payload["build_id"],
        "verification_basis": index.payload["verification_basis"],
        "written": {key: str(path) for key, path in written.items()},
        "link_checks": len(checks),
    }


def validate_default_context_index(config: ProjectConfig) -> dict[str, Any]:
    evidence, manifest = load_default_context_inputs(config)
    expected = build_context_index(config, evidence, manifest)
    machine_path = Path(expected.payload["paths"]["machine_index"])
    canonical_path = Path(expected.payload["paths"]["canonical_human"])
    pointer_path = Path(expected.payload["paths"]["sedb_pointer"])
    actual_payload = _read_json(
        machine_path,
        reason_code="context_machine_index_unreadable",
    )
    try:
        actual_human = canonical_path.read_text(encoding="utf-8")
        actual_pointer = pointer_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContextIndexError(
            "context_human_index_unreadable",
            f"cannot read context human index or pointer: {exc}",
        ) from exc
    if actual_payload != expected.payload:
        raise ContextIndexError(
            "context_machine_index_stale",
            "machine context index does not match current accepted evidence",
        )
    if actual_human != expected.human_markdown:
        raise ContextIndexError(
            "context_human_index_stale",
            "canonical human context index does not match current accepted evidence",
        )
    expected_pointer = build_sedb_pointer(config)
    if actual_pointer != expected_pointer:
        raise ContextIndexError(
            "context_pointer_stale",
            "SEDB context discovery pointer is stale",
        )
    checks = validate_context_links(expected)
    failures = [check for check in checks if not check.exists]
    if failures:
        raise ContextIndexError(
            "context_link_validation_failed",
            f"context index has {len(failures)} missing link targets",
        )
    return {
        "status": "ok",
        "build_id": expected.payload["build_id"],
        "verification_basis": expected.payload["verification_basis"],
        "link_checks": len(checks),
        "report_count": len(expected.payload["reports"]),
        "canonical_human": str(canonical_path),
        "machine_index": str(machine_path),
    }


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8()
    parser = argparse.ArgumentParser(prog="wanxiang-context-index")
    parser.add_argument("command", choices=("refresh", "validate"))
    args = parser.parse_args(argv)
    try:
        payload = (
            refresh_default_context_index(default_config())
            if args.command == "refresh"
            else validate_default_context_index(default_config())
        )
        exit_code = 0
    except ContextIndexError as exc:
        payload = {
            "status": "error",
            "reason_code": exc.reason_code,
            "message": str(exc),
        }
        exit_code = 4
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
