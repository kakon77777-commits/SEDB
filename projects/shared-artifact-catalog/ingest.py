from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from paths import (
    CatalogConfig,
    PathPolicyError,
    is_reparse_point,
    iter_safe_files,
    manifest_digest,
    resolve_under,
    sha256_file,
)
from schema import CatalogStore
from temporal import CtclClient, create_temporal_anchor


TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")


PROGRAMMING_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".lean": "Lean",
    ".css": "CSS",
    ".html": "HTML",
}


@dataclass(frozen=True)
class ComponentSnapshot:
    relpath: str
    source_path: Path
    size_bytes: int
    sha256: str
    filesystem_modified_at_local: str
    extension: str
    media_class: str
    programming_languages: tuple[str, ...]


@dataclass(frozen=True)
class PackageSnapshot:
    source_path: Path
    source_relpath: str
    manifest_sha256: str
    components: tuple[ComponentSnapshot, ...]
    is_single_file: bool


@dataclass(frozen=True)
class IngestResult:
    changed_count: int
    package_count: int
    component_count: int
    temporal_anchor_id: str | None


@dataclass
class ComponentPlan:
    action: str
    component_id: str
    snapshot: ComponentSnapshot | None
    current: dict | None


@dataclass
class PackagePlan:
    action: str
    package_id: str
    snapshot: PackageSnapshot
    current: dict | None
    components: list[ComponentPlan]


def _mtime_local(path: Path) -> str:
    return datetime.fromtimestamp(
        path.stat().st_mtime, timezone.utc
    ).astimezone(TAIPEI).isoformat()


def _media_class(extension: str) -> str:
    if extension in {".md", ".txt", ".rst"}:
        return "text"
    if extension in {".json", ".jsonl", ".csv", ".tsv"}:
        return "data"
    if extension in PROGRAMMING_LANGUAGES:
        return "source"
    if extension in {".zip", ".tar", ".gz", ".7z"}:
        return "archive"
    if extension in {".png", ".jpg", ".jpeg", ".gif", ".svg"}:
        return "image"
    if extension in {".pdf", ".docx"}:
        return "document"
    return "binary"


def _component_snapshot(path: Path, relpath: str) -> ComponentSnapshot:
    extension = path.suffix.lower()
    language = PROGRAMMING_LANGUAGES.get(extension)
    return ComponentSnapshot(
        relpath=relpath,
        source_path=path.resolve(strict=True),
        size_bytes=path.stat().st_size,
        sha256=sha256_file(path),
        filesystem_modified_at_local=_mtime_local(path),
        extension=extension,
        media_class=_media_class(extension),
        programming_languages=(language,) if language else (),
    )


def scan_package(path: str | Path, config: CatalogConfig) -> PackageSnapshot:
    package_path = resolve_under(path, (config.catalog_root,))
    if not package_path.exists():
        raise FileNotFoundError(package_path)
    if is_reparse_point(package_path):
        raise PathPolicyError(f"reparse point refused: {package_path}")
    source_relpath = package_path.relative_to(
        config.catalog_root.resolve(strict=False)
    ).as_posix()

    if package_path.is_file():
        component = _component_snapshot(package_path, package_path.name)
        return PackageSnapshot(
            source_path=package_path,
            source_relpath=source_relpath,
            manifest_sha256=component.sha256,
            components=(component,),
            is_single_file=True,
        )
    if not package_path.is_dir():
        raise PathPolicyError(f"unsupported package root: {package_path}")

    components = tuple(
        _component_snapshot(
            file_path, file_path.relative_to(package_path).as_posix()
        )
        for file_path in iter_safe_files(
            package_path, config.excluded_names
        )
    )
    return PackageSnapshot(
        source_path=package_path,
        source_relpath=source_relpath,
        manifest_sha256=manifest_digest(
            package_path, config.excluded_names
        ),
        components=components,
        is_single_file=False,
    )


def _active(records: list[dict]) -> list[dict]:
    return [
        record
        for record in records
        if record["values"].get("availability_state") != "missing"
    ]


def _resolve_package(
    store: CatalogStore, snapshot: PackageSnapshot
) -> tuple[dict | None, str]:
    exact = store.find("package", source_relpath=snapshot.source_relpath)
    if len(exact) == 1:
        current = exact[0]
        values = current["values"]
        if values.get("availability_state") == "missing":
            return current, "reappeared"
        if values.get("manifest_sha256") != snapshot.manifest_sha256:
            return current, "content_changed"
        return current, "unchanged"
    same_manifest = _active(
        store.find(
            "package", manifest_sha256=snapshot.manifest_sha256
        )
    )
    if len(same_manifest) == 1:
        return same_manifest[0], "moved"
    return None, "first_seen"


def _resolve_component(
    store: CatalogStore,
    package_id: str,
    snapshot: ComponentSnapshot,
) -> tuple[dict | None, str]:
    exact = store.find(
        "component",
        parent_package_id=package_id,
        source_relpath=snapshot.relpath,
    )
    if len(exact) == 1:
        current = exact[0]
        values = current["values"]
        if values.get("availability_state") == "missing":
            return current, "reappeared"
        if values.get("sha256") != snapshot.sha256:
            return current, "content_changed"
        if values.get("source_path") != str(snapshot.source_path):
            return current, "path_rebound"
        return current, "unchanged"
    same_content = _active(
        store.find(
            "component",
            parent_package_id=package_id,
            sha256=snapshot.sha256,
        )
    )
    if len(same_content) == 1:
        return same_content[0], "renamed"
    return None, "first_seen"


def _build_plans(
    snapshots: Iterable[PackageSnapshot], store: CatalogStore
) -> list[PackagePlan]:
    plans: list[PackagePlan] = []
    for snapshot in snapshots:
        package, package_action = _resolve_package(store, snapshot)
        package_id = package["id"] if package else f"package:{uuid4().hex}"
        component_plans: list[ComponentPlan] = []
        seen_ids: set[str] = set()
        for component_snapshot in snapshot.components:
            component, action = _resolve_component(
                store, package_id, component_snapshot
            )
            component_id = (
                component["id"]
                if component
                else f"component:{uuid4().hex}"
            )
            seen_ids.add(component_id)
            component_plans.append(
                ComponentPlan(
                    action=action,
                    component_id=component_id,
                    snapshot=component_snapshot,
                    current=component,
                )
            )

        if package:
            for component in _active(
                store.find("component", parent_package_id=package_id)
            ):
                if component["id"] not in seen_ids:
                    component_plans.append(
                        ComponentPlan(
                            action="missing",
                            component_id=component["id"],
                            snapshot=None,
                            current=component,
                        )
                    )
        plans.append(
            PackagePlan(
                action=package_action,
                package_id=package_id,
                snapshot=snapshot,
                current=package,
                components=component_plans,
            )
        )
    return plans


def _version(current: dict | None, *, increment: bool) -> int:
    if current is None:
        return 1
    value = int(current["values"].get("version", 1))
    return value + 1 if increment else value


def _package_values(plan: PackagePlan) -> dict:
    snapshot = plan.snapshot
    return {
        "stable_key": snapshot.source_relpath.lower().replace("/", "-"),
        "title": snapshot.source_path.name,
        "source_path": str(snapshot.source_path),
        "source_relpath": snapshot.source_relpath,
        "manifest_sha256": snapshot.manifest_sha256,
        "version": _version(
            plan.current,
            increment=plan.action in {"content_changed", "reappeared"},
        ),
        "availability_state": "available",
        "canonicality_state": plan.current["values"].get(
            "canonicality_state", "unknown"
        )
        if plan.current
        else "unknown",
        "verification_state": plan.current["values"].get(
            "verification_state", "unverified"
        )
        if plan.current
        else "unverified",
        "publication_state": plan.current["values"].get(
            "publication_state", "not_published"
        )
        if plan.current
        else "not_published",
    }


def _component_values(
    package_id: str,
    snapshot: ComponentSnapshot,
    current: dict | None,
    action: str,
) -> dict:
    return {
        "title": snapshot.source_path.name,
        "source_path": str(snapshot.source_path),
        "source_relpath": snapshot.relpath,
        "parent_package_id": package_id,
        "sha256": snapshot.sha256,
        "content_identity": snapshot.sha256,
        "size_bytes": snapshot.size_bytes,
        "extension": snapshot.extension,
        "media_class": snapshot.media_class,
        "filesystem_modified_at_local": snapshot.filesystem_modified_at_local,
        "programming_languages": list(snapshot.programming_languages),
        "content_languages": current["values"].get(
            "content_languages", []
        )
        if current
        else [],
        "interface_languages": current["values"].get(
            "interface_languages", []
        )
        if current
        else [],
        "dependency_mode": current["values"].get(
            "dependency_mode", "independent"
        )
        if current
        else "independent",
        "required_component_ids": current["values"].get(
            "required_component_ids", []
        )
        if current
        else [],
        "version": _version(
            current,
            increment=action in {"content_changed", "reappeared"},
        ),
        "availability_state": "available",
        "verification_state": current["values"].get(
            "verification_state", "unverified"
        )
        if current
        else "unverified",
        "publication_state": current["values"].get(
            "publication_state", "not_published"
        )
        if current
        else "not_published",
    }


def _event_values(
    record_id: str,
    action: str,
    anchor_id: str,
    *,
    current: dict | None = None,
    snapshot: PackageSnapshot | ComponentSnapshot | None = None,
) -> dict:
    values = {
        "source_record_id": record_id,
        "outcome": action,
        "temporal_anchor_id": anchor_id,
    }
    if current:
        if "sha256" in current["values"]:
            values["source_sha256"] = current["values"]["sha256"]
        elif "manifest_sha256" in current["values"]:
            values["source_sha256"] = current["values"][
                "manifest_sha256"
            ]
        values["source_path"] = current["values"].get("source_path", "")
    if snapshot:
        values["destination_path"] = str(snapshot.source_path)
        if isinstance(snapshot, ComponentSnapshot):
            values["sha256"] = snapshot.sha256
        else:
            values["manifest_sha256"] = snapshot.manifest_sha256
    return values


def _apply_package_plan(
    store: CatalogStore, plan: PackagePlan, anchor_id: str
) -> int:
    changed = 0
    package_values = _package_values(plan)
    if plan.current is None:
        store.create_record(
            "package",
            plan.snapshot.source_path.name,
            package_values,
            entity_id=plan.package_id,
            source="artifact-catalog:ingest",
        )
    elif plan.action != "unchanged":
        store.create_record(
            "package_version_event",
            f"{plan.action} {plan.package_id}",
            _event_values(
                plan.package_id,
                plan.action,
                anchor_id,
                current=plan.current,
                snapshot=plan.snapshot,
            ),
            source="artifact-catalog:ingest",
        )
        store.update_current(
            plan.package_id, package_values, "artifact-catalog:ingest"
        )
        changed += 1
    if plan.current is None:
        store.create_record(
            "package_version_event",
            f"first_seen {plan.package_id}",
            _event_values(
                plan.package_id,
                "first_seen",
                anchor_id,
                snapshot=plan.snapshot,
            ),
            source="artifact-catalog:ingest",
        )
        changed += 1

    for component_plan in plan.components:
        action = component_plan.action
        snapshot = component_plan.snapshot
        if action == "unchanged":
            continue
        if action == "path_rebound" and snapshot is not None:
            store.update_current(
                component_plan.component_id,
                {
                    "source_path": str(snapshot.source_path),
                    "filesystem_modified_at_local": snapshot.filesystem_modified_at_local,
                },
                "artifact-catalog:ingest",
            )
            continue
        if action == "missing":
            store.create_record(
                "component_version_event",
                f"missing {component_plan.component_id}",
                _event_values(
                    component_plan.component_id,
                    "missing",
                    anchor_id,
                    current=component_plan.current,
                ),
                source="artifact-catalog:ingest",
            )
            store.update_current(
                component_plan.component_id,
                {"availability_state": "missing"},
                "artifact-catalog:ingest",
            )
            changed += 1
            continue
        if snapshot is None:
            raise RuntimeError("component snapshot missing for active action")
        values = _component_values(
            plan.package_id,
            snapshot,
            component_plan.current,
            action,
        )
        if component_plan.current is None:
            store.create_record(
                "component",
                snapshot.source_path.name,
                values,
                entity_id=component_plan.component_id,
                source="artifact-catalog:ingest",
            )
        else:
            store.update_current(
                component_plan.component_id,
                values,
                "artifact-catalog:ingest",
            )
        store.create_record(
            "component_version_event",
            f"{action} {component_plan.component_id}",
            _event_values(
                component_plan.component_id,
                action,
                anchor_id,
                current=component_plan.current,
                snapshot=snapshot,
            ),
            source="artifact-catalog:ingest",
        )
        changed += 1
    return changed


def ingest_package_paths(
    paths: Iterable[str | Path],
    config: CatalogConfig,
    store: CatalogStore,
    temporal_client: CtclClient,
) -> IngestResult:
    snapshots = tuple(scan_package(path, config) for path in paths)
    plans = _build_plans(snapshots, store)
    change_count = sum(
        (0 if plan.action == "unchanged" else 1)
        + sum(
            0
            if component.action in {"unchanged", "path_rebound"}
            else 1
            for component in plan.components
        )
        for plan in plans
    )
    if change_count == 0:
        return IngestResult(
            changed_count=0,
            package_count=len(snapshots),
            component_count=sum(len(item.components) for item in snapshots),
            temporal_anchor_id=None,
        )

    anchor = create_temporal_anchor(
        store,
        temporal_client,
        "ingest",
        timezone_name=config.timezone,
    )
    applied = sum(
        _apply_package_plan(store, plan, anchor["id"]) for plan in plans
    )
    return IngestResult(
        changed_count=applied,
        package_count=len(snapshots),
        component_count=sum(len(item.components) for item in snapshots),
        temporal_anchor_id=anchor["id"],
    )


def ingest_registered_packages(
    config: CatalogConfig,
    store: CatalogStore,
    temporal_client: CtclClient,
) -> IngestResult:
    roots = tuple(config.catalog_root / item for item in config.package_roots)
    return ingest_package_paths(roots, config, store, temporal_client)
