from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from config import ProjectConfig
from gameplay.character import analyze_character_coverage
from gameplay.combat import analyze_combat_progression
from gameplay.common import (
    Claim,
    GameplayDataError,
    StaticDataset,
    _sha256,
    load_verified_dataset,
)
from gameplay.events import (
    analyze_choice_consequence,
    analyze_event_network,
    analyze_time_pacing,
)
from gameplay.relationships import analyze_relationship_routes


REPORT_SCHEMA = "wanxiang-static-gameplay-report/v1"
MANIFEST_SCHEMA = "wanxiang-static-gameplay-manifest/v1"
BLOCKED_RESEARCH_DIRECTORIES = frozenset({"baseline", "inputs", "art-engineering"})
NOT_MEASURED = (
    "Runtime event reachability, selection order, RNG behavior, and save-state transitions.",
    "Actual event frequency, waiting pressure, balance, dominant builds, and player fun.",
    "Runtime ownership or behavioral parity of AllExcel versus packaged DAT data.",
    "Live MOD loading, compatibility, and save migration after asset or data changes.",
)

Analyzer = Callable[[StaticDataset], dict]
ANALYZERS: dict[str, Analyzer] = {
    "character-coverage": analyze_character_coverage,
    "event-network": analyze_event_network,
    "choice-consequence": analyze_choice_consequence,
    "time-pacing": analyze_time_pacing,
    "relationship-routes": analyze_relationship_routes,
    "combat-progression": analyze_combat_progression,
}


@dataclass(frozen=True)
class ReportManifest:
    output_root: Path
    report_paths: tuple[Path, ...]
    sha256_by_path: dict[str, str]
    catalog_fingerprint: str
    manifest_path: Path


def _json_text(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


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


def _validate_output_root(output_root: Path, source_root: Path | None) -> Path:
    resolved = output_root.resolve()
    if source_root is None:
        return resolved
    source = source_root.resolve()
    try:
        relative = resolved.relative_to(source)
    except ValueError:
        return resolved
    if relative.parts and relative.parts[0].casefold() in BLOCKED_RESEARCH_DIRECTORIES:
        raise GameplayDataError(
            "gameplay_output_root_forbidden",
            f"gameplay reports may not be written under {relative.parts[0]}",
        )
    return resolved


def _selected_analyzers(names: Iterable[str] | None) -> tuple[tuple[str, Analyzer], ...]:
    if names is None:
        selected = tuple(ANALYZERS)
    else:
        selected = tuple(names)
    unknown = sorted(set(selected) - set(ANALYZERS))
    if unknown:
        raise GameplayDataError(
            "unknown_gameplay_analysis",
            f"unknown gameplay analysis: {', '.join(unknown)}",
        )
    return tuple((name, ANALYZERS[name]) for name in selected)


def _report_payload(dataset: StaticDataset, analysis: dict) -> dict:
    claims = analysis.get("claims", ())
    if any(not isinstance(claim, Claim) for claim in claims):
        raise GameplayDataError(
            "invalid_gameplay_claim",
            "gameplay analyses must return Claim records",
        )
    payload = {
        "schema": REPORT_SCHEMA,
        "analysis_name": analysis["analysis_name"],
        "generated_at": dataset.accepted_at or "NOT_RECORDED",
        "build_id": dataset.build_id,
        "database": {
            "path": dataset.database_path,
            "sha256": dataset.database_sha256,
        },
        "catalog": {
            "fingerprint": dataset.catalog_fingerprint,
            "source_fingerprint": dataset.catalog_source_fingerprint,
            "research_root": dataset.source_root,
            "all_excel_root": dataset.all_excel_root,
            "source_table_counts": dict(sorted(dataset.source_table_counts.items())),
        },
        "reference_rule_version": dataset.rule_version,
        "source_tables": list(analysis.get("source_tables", ())),
        "metrics": analysis.get("metrics", {}),
        "claims": [asdict(claim) for claim in claims],
        "not_measured": list(NOT_MEASURED),
    }
    if "details" in analysis:
        payload["details"] = analysis["details"]
    return payload


def _markdown(payload: dict) -> str:
    lines = [
        f"# {payload['analysis_name']}",
        "",
        f"- BuildID: `{payload['build_id']}`",
        f"- Evidence timestamp: `{payload['generated_at']}`",
        f"- Database: `{payload['database']['path']}`",
        f"- Database SHA-256: `{payload['database']['sha256']}`",
        f"- Catalog fingerprint: `{payload['catalog']['fingerprint']}`",
        f"- Catalog source fingerprint: `{payload['catalog']['source_fingerprint']}`",
        f"- Research root: `{payload['catalog']['research_root']}`",
        f"- Immutable AllExcel root: `{payload['catalog']['all_excel_root']}`",
        f"- Reference rule version: `{payload['reference_rule_version']}`",
        "- Source tables: " + ", ".join(
            f"`{table}`" for table in payload["source_tables"]
        ),
        "",
        "## Metrics",
        "",
        "```json",
        json.dumps(payload["metrics"], ensure_ascii=False, sort_keys=True, indent=2),
        "```",
        "",
    ]
    for claim in payload["claims"]:
        lines.extend(
            [
                f"## {claim['claim_class']}",
                "",
                claim["text"],
                "",
                "Evidence: " + "; ".join(
                    f"`{item}`" for item in claim["evidence"]
                ),
            ]
        )
        if claim.get("falsifying_test"):
            lines.extend(
                ["", f"Falsifying test: {claim['falsifying_test']}"]
            )
        lines.append("")
    lines.extend(["## NotMeasured", ""])
    lines.extend(f"- {item}" for item in payload["not_measured"])
    lines.append("")
    if "details" in payload:
        lines.extend(
            [
                "## Static details",
                "",
                "```json",
                json.dumps(
                    payload["details"],
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def export_static_reports(
    dataset: StaticDataset,
    output_root: Path,
    *,
    names: Iterable[str] | None = None,
    source_root: Path | None = None,
) -> ReportManifest:
    root = _validate_output_root(output_root, source_root)
    outputs: dict[Path, str] = {}
    reports = []
    for name, analyzer in _selected_analyzers(names):
        payload = _report_payload(dataset, analyzer(dataset))
        json_path = root / f"{name}.json"
        markdown_path = root / f"{name}.md"
        outputs[json_path] = _json_text(payload)
        outputs[markdown_path] = _markdown(payload)
        reports.append(
            {
                "analysis_name": name,
                "json": json_path.name,
                "markdown": markdown_path.name,
            }
        )

    for path in sorted(outputs, key=lambda item: item.name):
        _atomic_write(path, outputs[path])
    hashes = {
        path.name: _sha256(path)
        for path in sorted(outputs, key=lambda item: item.name)
    }
    manifest_payload = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": dataset.accepted_at or "NOT_RECORDED",
        "build_id": dataset.build_id,
        "catalog_fingerprint": dataset.catalog_fingerprint,
        "catalog_source_fingerprint": dataset.catalog_source_fingerprint,
        "database_sha256": dataset.database_sha256,
        "reference_rule_version": dataset.rule_version,
        "reports": reports,
        "sha256_by_path": hashes,
        "not_measured": list(NOT_MEASURED),
    }
    manifest_path = root / "manifest.json"
    _atomic_write(manifest_path, _json_text(manifest_payload))
    return ReportManifest(
        output_root=root,
        report_paths=tuple(sorted(outputs, key=lambda item: item.name)),
        sha256_by_path=hashes,
        catalog_fingerprint=dataset.catalog_fingerprint,
        manifest_path=manifest_path,
    )


def export_gameplay_reports(
    config: ProjectConfig,
    output_root: Path,
    *,
    name: str = "all",
    acceptance_path: Path | None = None,
) -> ReportManifest:
    dataset = load_verified_dataset(config, acceptance_path=acceptance_path)
    names = None if name == "all" else (name,)
    return export_static_reports(
        dataset,
        output_root,
        names=names,
        source_root=config.source_root,
    )
