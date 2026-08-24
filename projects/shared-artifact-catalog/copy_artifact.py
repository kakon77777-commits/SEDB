from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from paths import (
    CatalogConfig,
    PathPolicyError,
    is_reparse_point,
    manifest_digest,
    resolve_under,
    sha256_file,
)
from schema import CatalogStore
from temporal import CtclClient, create_temporal_anchor


CopyMode = Literal["package", "component", "dependency_closure"]


class CopyRefused(ValueError):
    """Raised when a copy violates source, destination, or dependency policy."""


@dataclass(frozen=True)
class CopyResult:
    outcome: str
    source_sha256: str
    destination_sha256: str
    destination: Path
    event_id: str
    temporal_anchor_id: str


def _is_under(path: Path, root: Path) -> bool:
    try:
        resolve_under(path, (root,))
        return True
    except PathPolicyError:
        return False


def _assert_no_reparse_ancestors(path: Path, roots: tuple[Path, ...]) -> None:
    resolved_roots = tuple(root.resolve(strict=False) for root in roots)
    current = path if path.exists() else path.parent
    while True:
        if current.exists() and is_reparse_point(current):
            raise CopyRefused(f"reparse point refused: {current}")
        if current in resolved_roots or current.parent == current:
            return
        current = current.parent


def _package_digest(path: Path, config: CatalogConfig) -> str:
    if path.is_file():
        return sha256_file(path)
    if path.is_dir():
        return manifest_digest(path, config.excluded_names)
    raise CopyRefused(f"package source is missing: {path}")


def _fresh_source(record: dict, config: CatalogConfig) -> tuple[Path, str]:
    values = record["values"]
    if values.get("availability_state") == "missing":
        raise CopyRefused("source record is marked missing")
    source = Path(str(values.get("source_path", ""))).resolve(strict=False)
    if not source.exists():
        raise CopyRefused(f"source path is missing: {source}")
    if is_reparse_point(source):
        raise CopyRefused(f"reparse point refused: {source}")
    if record["kind"] == "component":
        if not source.is_file():
            raise CopyRefused("component source is not a file")
        actual = sha256_file(source)
        expected = str(values.get("sha256", ""))
        if actual != expected:
            raise CopyRefused("source hash drift; rescan before copying")
        return source, actual
    if record["kind"] == "package":
        actual = _package_digest(source, config)
        expected = str(values.get("manifest_sha256", ""))
        if actual != expected:
            raise CopyRefused("source hash drift; rescan before copying")
        return source, actual
    raise CopyRefused(f"record kind is not copyable: {record['kind']}")


def _closure_records(store: CatalogStore, primary: dict) -> list[dict]:
    ordered: list[dict] = []
    seen: set[str] = set()
    active: set[str] = set()

    def visit(record: dict) -> None:
        record_id = record["id"]
        if record_id in seen:
            return
        if record_id in active:
            raise CopyRefused("component dependency cycle")
        if record["kind"] != "component":
            raise CopyRefused("dependency target is not a component")
        active.add(record_id)
        for dependency_id in record["values"].get(
            "required_component_ids", []
        ):
            visit(store.get_record(str(dependency_id)))
        active.remove(record_id)
        seen.add(record_id)
        ordered.append(record)

    visit(primary)
    return ordered


def _closure_digest(items: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(items):
        digest.update(f"{relative}\t{file_hash}\n".encode("utf-8"))
    return digest.hexdigest()


def _event(
    store: CatalogStore,
    *,
    record_id: str,
    source_path: str,
    source_digest: str,
    destination: Path,
    mode: str,
    purpose: str,
    responsibility_ref: str,
    requester_claim: str,
    host_task_id: str,
    outcome: str,
    verification_result: str,
    failure_reason: str,
    anchor_id: str,
) -> dict:
    return store.create_record(
        "copy_event",
        f"{outcome} {record_id}",
        {
            "source_record_id": record_id,
            "source_path": source_path,
            "source_sha256": source_digest,
            "destination_path": str(destination),
            "copy_mode": mode,
            "purpose": purpose,
            "responsibility_ref": responsibility_ref,
            "requester_claim": requester_claim,
            "host_task_id": host_task_id or "unresolved",
            "outcome": outcome,
            "verification_result": verification_result,
            "failure_reason": failure_reason,
            "temporal_anchor_id": anchor_id,
        },
        source="artifact-catalog:copy",
    )


def copy_artifact(
    *,
    store: CatalogStore,
    config: CatalogConfig,
    record_id: str,
    destination: str | Path,
    mode: CopyMode,
    include_required: bool,
    purpose: str,
    responsibility_ref: str,
    requester_claim: str,
    host_task_id: str | None,
    temporal_client: CtclClient,
) -> CopyResult:
    record = store.get_record(record_id)
    destination_path = Path(destination).resolve(strict=False)
    anchor = create_temporal_anchor(
        store,
        temporal_client,
        "copy",
        timezone_name=config.timezone,
    )
    anchor_id = anchor["id"]
    source_path = str(record["values"].get("source_path", ""))
    source_digest = str(
        record["values"].get("sha256")
        or record["values"].get("manifest_sha256")
        or ""
    )

    try:
        try:
            destination_path = resolve_under(
                destination_path, config.allowed_copy_roots
            )
        except PathPolicyError as exc:
            raise CopyRefused(str(exc)) from exc
        if _is_under(destination_path, config.catalog_root):
            raise CopyRefused("ordinary copy cannot target the staging root")
        _assert_no_reparse_ancestors(
            destination_path, config.allowed_copy_roots
        )
        source, source_digest = _fresh_source(record, config)

        if mode == "component":
            if record["kind"] != "component":
                raise CopyRefused("component mode requires a component record")
            if record["values"].get("dependency_mode") == "bundle_required":
                raise CopyRefused("bundle_required component cannot be copied alone")
            if destination_path.exists():
                if (
                    destination_path.is_file()
                    and sha256_file(destination_path) == source_digest
                ):
                    event = _event(
                        store,
                        record_id=record_id,
                        source_path=str(source),
                        source_digest=source_digest,
                        destination=destination_path,
                        mode=mode,
                        purpose=purpose,
                        responsibility_ref=responsibility_ref,
                        requester_claim=requester_claim,
                        host_task_id=host_task_id or "unresolved",
                        outcome="already_present",
                        verification_result="sha256_match",
                        failure_reason="",
                        anchor_id=anchor_id,
                    )
                    return CopyResult(
                        "already_present",
                        source_digest,
                        source_digest,
                        destination_path,
                        event["id"],
                        anchor_id,
                    )
                raise CopyRefused("destination collision with differing bytes")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination_path)
            destination_digest = sha256_file(destination_path)

        elif mode == "package":
            if record["kind"] != "package":
                raise CopyRefused("package mode requires a package record")
            if destination_path.exists():
                if (
                    (source.is_file() and destination_path.is_file())
                    or (source.is_dir() and destination_path.is_dir())
                ) and _package_digest(destination_path, config) == source_digest:
                    event = _event(
                        store,
                        record_id=record_id,
                        source_path=str(source),
                        source_digest=source_digest,
                        destination=destination_path,
                        mode=mode,
                        purpose=purpose,
                        responsibility_ref=responsibility_ref,
                        requester_claim=requester_claim,
                        host_task_id=host_task_id or "unresolved",
                        outcome="already_present",
                        verification_result="manifest_match",
                        failure_reason="",
                        anchor_id=anchor_id,
                    )
                    return CopyResult(
                        "already_present",
                        source_digest,
                        source_digest,
                        destination_path,
                        event["id"],
                        anchor_id,
                    )
                raise CopyRefused("destination collision with differing bytes")
            if source.is_file():
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination_path)
            else:
                shutil.copytree(
                    source,
                    destination_path,
                    symlinks=False,
                    copy_function=shutil.copy2,
                )
            destination_digest = _package_digest(destination_path, config)

        elif mode == "dependency_closure":
            if record["kind"] != "component":
                raise CopyRefused(
                    "dependency closure requires a component record"
                )
            if not include_required:
                raise CopyRefused(
                    "dependency closure requires include_required"
                )
            if destination_path.exists():
                raise CopyRefused("destination collision for dependency closure")
            closure = _closure_records(store, record)
            prepared: list[tuple[dict, Path, str, str]] = []
            source_items: list[tuple[str, str]] = []
            for component in closure:
                component_source, component_hash = _fresh_source(
                    component, config
                )
                relative = str(component["values"]["source_relpath"])
                target = resolve_under(
                    destination_path / Path(relative),
                    (destination_path,),
                )
                prepared.append(
                    (component, component_source, component_hash, relative)
                )
                source_items.append((relative, component_hash))
                if target.exists():
                    raise CopyRefused(
                        "destination collision in dependency closure"
                    )
            source_digest = _closure_digest(source_items)
            destination_path.mkdir(parents=True)
            destination_items: list[tuple[str, str]] = []
            for component, component_source, component_hash, relative in prepared:
                target = destination_path / Path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(component_source, target)
                destination_items.append((relative, sha256_file(target)))
            destination_digest = _closure_digest(destination_items)
        else:
            raise CopyRefused(f"unsupported copy mode: {mode}")

        if destination_digest != source_digest:
            raise CopyRefused("post-copy hash verification failed")
        event = _event(
            store,
            record_id=record_id,
            source_path=str(source),
            source_digest=source_digest,
            destination=destination_path,
            mode=mode,
            purpose=purpose,
            responsibility_ref=responsibility_ref,
            requester_claim=requester_claim,
            host_task_id=host_task_id or "unresolved",
            outcome="copied",
            verification_result="sha256_match",
            failure_reason="",
            anchor_id=anchor_id,
        )
        return CopyResult(
            "copied",
            source_digest,
            destination_digest,
            destination_path,
            event["id"],
            anchor_id,
        )
    except CopyRefused as exc:
        _event(
            store,
            record_id=record_id,
            source_path=source_path,
            source_digest=source_digest,
            destination=destination_path,
            mode=mode,
            purpose=purpose,
            responsibility_ref=responsibility_ref,
            requester_claim=requester_claim,
            host_task_id=host_task_id or "unresolved",
            outcome="refused",
            verification_result="not_copied",
            failure_reason=str(exc),
            anchor_id=anchor_id,
        )
        raise
    except (OSError, shutil.Error) as exc:
        _event(
            store,
            record_id=record_id,
            source_path=source_path,
            source_digest=source_digest,
            destination=destination_path,
            mode=mode,
            purpose=purpose,
            responsibility_ref=responsibility_ref,
            requester_claim=requester_claim,
            host_task_id=host_task_id or "unresolved",
            outcome="failed",
            verification_result="copy_failed",
            failure_reason=str(exc),
            anchor_id=anchor_id,
        )
        raise CopyRefused(f"copy failed: {exc}") from exc
