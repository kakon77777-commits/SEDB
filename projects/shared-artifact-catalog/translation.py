from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from paths import (
    CatalogConfig,
    PathPolicyError,
    is_reparse_point,
    iter_safe_files,
    resolve_under,
    sha256_file,
)
from schema import CatalogStore
from temporal import CtclClient, create_temporal_anchor


LANGUAGE_TAG = re.compile(
    r"^[a-z]{2,3}(?:-(?:[A-Z][a-z]{3}|[A-Z]{2}|[0-9]{3}|[A-Za-z0-9]{5,8}))*$"
)
SPECIAL_LANGUAGE_TAGS = frozenset({"mul", "und", "zxx"})
TRANSLATION_SCOPES = frozenset(
    {
        "full_text",
        "abstract",
        "interface",
        "documentation",
        "metadata",
        "selected_sections",
    }
)
TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".html",
        ".css",
        ".js",
        ".mjs",
        ".ts",
        ".tsx",
        ".py",
    }
)


class TranslationRefused(ValueError):
    """Raised when translation source, language, or output is unsafe."""


@dataclass(frozen=True)
class TranslationJob:
    id: str
    path: Path
    lifecycle_state: str
    output_component_ids: tuple[str, ...] = ()


def _validate_language(tag: str) -> str:
    value = tag.strip()
    if value not in SPECIAL_LANGUAGE_TAGS and not LANGUAGE_TAG.fullmatch(value):
        raise TranslationRefused(f"invalid BCP 47 language tag: {tag}")
    return value


def _validate_scope(scope: str) -> str:
    value = scope.strip()
    if value not in TRANSLATION_SCOPES:
        raise TranslationRefused(f"unsupported translation scope: {scope}")
    return value


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _fresh_source(store: CatalogStore, component_id: str) -> tuple[dict, Path, str]:
    component = store.get_record(component_id)
    if component["kind"] != "component":
        raise TranslationRefused("translation source must be a component")
    values = component["values"]
    source = Path(str(values.get("source_path", ""))).resolve(strict=False)
    if not source.is_file():
        raise TranslationRefused("translation source file is missing")
    if is_reparse_point(source):
        raise TranslationRefused(f"reparse point refused: {source}")
    actual = sha256_file(source)
    if actual != values.get("sha256"):
        raise TranslationRefused("source hash drift; rescan before translation")
    return component, source, actual


def _translation_root(config: CatalogConfig) -> Path:
    return (
        config.catalog_root.resolve(strict=False) / config.translation_zone
    )


def _event(
    store: CatalogStore,
    job_id: str,
    state: str,
    anchor_id: str,
    translator_claim: str,
    host_task_id: str,
    *,
    output_ids: list[str] | None = None,
    technical_review: dict | None = None,
) -> dict:
    return store.create_record(
        "translation_event",
        f"{state} {job_id}",
        {
            "source_record_id": job_id,
            "lifecycle_state": state,
            "temporal_anchor_id": anchor_id,
            "proposer_claim": translator_claim,
            "host_task_id": host_task_id or "unresolved",
            "output_component_ids": output_ids or [],
            "technical_review": technical_review or {},
        },
        source="artifact-catalog:translation",
    )


def _job_view(record: dict) -> TranslationJob:
    return TranslationJob(
        id=record["id"],
        path=Path(record["values"]["job_path"]),
        lifecycle_state=str(record["values"]["lifecycle_state"]),
        output_component_ids=tuple(
            str(item)
            for item in record["values"].get("output_component_ids", [])
        ),
    )


def start_translation(
    *,
    store: CatalogStore,
    config: CatalogConfig,
    source_component_id: str,
    target_language: str,
    translation_scope: str,
    translator_claim: str,
    host_task_id: str | None,
    temporal_client: CtclClient,
) -> TranslationJob:
    target = _validate_language(target_language)
    scope = _validate_scope(translation_scope)
    component, source, source_hash = _fresh_source(
        store, source_component_id
    )
    values = component["values"]
    source_languages = values.get("content_languages", [])
    source_language = str(source_languages[0]) if source_languages else "und"
    package_id = str(values.get("parent_package_id", "unpackaged"))
    job_id = f"translation-job:{uuid4().hex}"
    root = _translation_root(config)
    job_path = resolve_under(
        root
        / _safe_segment(package_id)
        / target
        / _safe_segment(job_id),
        (root,),
    )
    if job_path.exists():
        raise TranslationRefused(f"translation job path already exists: {job_path}")

    anchor = create_temporal_anchor(
        store,
        temporal_client,
        "translation_start",
        timezone_name=config.timezone,
    )
    snapshot_dir = job_path / "source_snapshot"
    work_dir = job_path / "work"
    snapshot_dir.mkdir(parents=True)
    work_dir.mkdir()
    snapshot_path = snapshot_dir / source.name
    shutil.copy2(source, snapshot_path)
    if sha256_file(snapshot_path) != source_hash:
        raise TranslationRefused("source snapshot hash verification failed")
    source_ref = {
        "job_id": job_id,
        "source_component_id": source_component_id,
        "source_path": str(source),
        "source_sha256": source_hash,
        "source_language": source_language,
        "target_language": target,
        "translation_scope": scope,
        "temporal_anchor_id": anchor["id"],
    }
    (job_path / "SOURCE_REF.json").write_text(
        json.dumps(
            source_ref,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (job_path / "TRANSLATION_NOTES.md").write_text(
        "# Translation Notes\n\n"
        "This output is a candidate derivative, not an approved translation.\n",
        encoding="utf-8",
    )
    job = store.create_record(
        "translation_job",
        f"Translate {component['label']} to {target}",
        {
            "source_component_id": source_component_id,
            "source_sha256": source_hash,
            "source_language": source_language,
            "target_language": target,
            "translation_scope": scope,
            "job_path": str(job_path),
            "lifecycle_state": "in_progress",
            "output_component_ids": [],
            "proposer_claim": translator_claim,
            "host_task_id": host_task_id or "unresolved",
            "temporal_anchor_id": anchor["id"],
        },
        entity_id=job_id,
        source="artifact-catalog:translation",
    )
    _event(
        store,
        job_id,
        "requested",
        anchor["id"],
        translator_claim,
        host_task_id or "unresolved",
    )
    _event(
        store,
        job_id,
        "in_progress",
        anchor["id"],
        translator_claim,
        host_task_id or "unresolved",
    )
    return _job_view(job)


def _source_is_stale(store: CatalogStore, job: dict) -> bool:
    values = job["values"]
    try:
        component = store.get_record(values["source_component_id"])
        source = Path(component["values"]["source_path"])
        return (
            not source.is_file()
            or sha256_file(source) != values["source_sha256"]
            or component["values"].get("sha256") != values["source_sha256"]
        )
    except (KeyError, OSError):
        return True


def mark_stale_translations(
    store: CatalogStore,
    config: CatalogConfig,
    temporal_client: CtclClient,
) -> list[str]:
    candidates = [
        job
        for job in store.find("translation_job")
        if job["values"].get("lifecycle_state")
        in {"in_progress", "candidate", "reviewed"}
        and _source_is_stale(store, job)
    ]
    if not candidates:
        return []
    anchor = create_temporal_anchor(
        store,
        temporal_client,
        "translation_stale",
        timezone_name=config.timezone,
    )
    stale_ids: list[str] = []
    for job in candidates:
        values = job["values"]
        _event(
            store,
            job["id"],
            "stale",
            anchor["id"],
            str(values.get("proposer_claim", "")),
            str(values.get("host_task_id", "unresolved")),
        )
        store.update_current(
            job["id"],
            {
                "lifecycle_state": "stale",
                "temporal_anchor_id": anchor["id"],
            },
            "artifact-catalog:translation",
        )
        stale_ids.append(job["id"])
    return stale_ids


def _validate_outputs(work_dir: Path) -> tuple[list[Path], dict]:
    if not work_dir.is_dir() or is_reparse_point(work_dir):
        raise TranslationRefused("translation work directory is missing or unsafe")
    outputs = list(iter_safe_files(work_dir, frozenset()))
    if not outputs:
        raise TranslationRefused("translation output is empty")
    text_files = 0
    for output in outputs:
        if output.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        text_files += 1
        try:
            text = output.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise TranslationRefused(
                f"translation output is not valid UTF-8: {output.name}"
            ) from exc
        if "\ufffd" in text:
            raise TranslationRefused(
                f"translation output contains Unicode replacement character: {output.name}"
            )
        if not text.strip():
            raise TranslationRefused(
                f"translation output is empty: {output.name}"
            )
    return outputs, {
        "output_files": len(outputs),
        "utf8_text_files": text_files,
        "unicode_replacement_characters": 0,
    }


def complete_translation(
    *,
    store: CatalogStore,
    config: CatalogConfig,
    job_id: str,
    translator_claim: str,
    host_task_id: str | None,
    temporal_client: CtclClient,
) -> TranslationJob:
    job = store.get_record(job_id)
    if job["kind"] != "translation_job":
        raise TranslationRefused("job id is not a translation job")
    if job["values"].get("lifecycle_state") == "stale":
        raise TranslationRefused("source hash drift; translation job is stale")
    if job["values"].get("lifecycle_state") != "in_progress":
        raise TranslationRefused("translation job is not in progress")
    if _source_is_stale(store, job):
        mark_stale_translations(store, config, temporal_client)
        raise TranslationRefused("source hash drift; translation job is stale")

    translation_root = _translation_root(config)
    job_path = resolve_under(job["values"]["job_path"], (translation_root,))
    work_dir = resolve_under(job_path / "work", (job_path,))
    outputs, technical_review = _validate_outputs(work_dir)
    anchor = create_temporal_anchor(
        store,
        temporal_client,
        "translation_complete",
        timezone_name=config.timezone,
    )
    source_component = store.get_record(
        job["values"]["source_component_id"]
    )
    output_ids: list[str] = []
    for output in outputs:
        output_hash = sha256_file(output)
        output_record = store.create_record(
            "component",
            output.name,
            {
                "title": output.name,
                "source_path": str(output),
                "source_relpath": output.relative_to(work_dir).as_posix(),
                "parent_package_id": source_component["values"].get(
                    "parent_package_id", ""
                ),
                "sha256": output_hash,
                "content_identity": output_hash,
                "size_bytes": output.stat().st_size,
                "extension": output.suffix.lower(),
                "content_languages": [job["values"]["target_language"]],
                "availability_state": "available",
                "verification_state": "technically_verified",
                "publication_state": "candidate",
                "version": 1,
            },
            source="artifact-catalog:translation",
        )
        output_ids.append(output_record["id"])
        store.create_relation(
            output_record["id"],
            source_component["id"],
            "translation_of",
            anchor["id"],
            source="artifact-catalog:translation",
        )

    _event(
        store,
        job_id,
        "candidate",
        anchor["id"],
        translator_claim,
        host_task_id or "unresolved",
        output_ids=output_ids,
        technical_review=technical_review,
    )
    updated = store.update_current(
        job_id,
        {
            "lifecycle_state": "candidate",
            "output_component_ids": output_ids,
            "technical_review": technical_review,
            "proposer_claim": translator_claim,
            "host_task_id": host_task_id or "unresolved",
            "temporal_anchor_id": anchor["id"],
        },
        "artifact-catalog:translation",
    )
    return _job_view(updated)
