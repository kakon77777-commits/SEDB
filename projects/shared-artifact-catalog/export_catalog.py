from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from schema import CatalogStore
from temporal import get_effective_temporal_anchor


@dataclass(frozen=True)
class ExportResult:
    path: Path
    changed: bool
    sha256: str
    package_count: int
    component_count: int


def _text(value) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")


def _list(value) -> str:
    if not value:
        return "—"
    return ", ".join(_text(item) for item in value)


def _metadata_lines(
    record: dict,
    *,
    digest_key: str,
    category_labels: dict[str, list[str]],
    anchors: dict[str, dict],
) -> list[str]:
    values = record["values"]
    anchor = anchors.get(record["id"], {})
    return [
        f"- ID: `{record['id']}`",
        f"- Categories: {_list(category_labels.get(record['id'], []))}",
        f"- Content languages: {_list(values.get('content_languages', []))}",
        f"- Interface languages: {_list(values.get('interface_languages', []))}",
        f"- Programming languages: {_list(values.get('programming_languages', []))}",
        f"- Verification: `{_text(values.get('verification_state', 'unverified'))}`",
        f"- Publication: `{_text(values.get('publication_state', 'not_published'))}`",
        f"- Dependency mode: `{_text(values.get('dependency_mode', 'independent'))}`",
        f"- Digest: `{_text(values.get(digest_key, ''))}`",
        f"- Source: `{_text(values.get('source_relpath', ''))}`",
        f"- Catalog update time: `{_text(anchor.get('ctcl_local', 'unanchored'))}`",
        f"- CTCL instant: `{_text(anchor.get('ctcl_instant_id', anchor.get('temporal_status', 'unanchored')))}`",
    ]


def render_catalog(store: CatalogStore) -> str:
    packages = sorted(
        store.find("package"),
        key=lambda item: (item["label"].casefold(), item["id"]),
    )
    components = sorted(
        store.find("component"),
        key=lambda item: (
            _text(item["values"].get("source_relpath")).casefold(),
            item["id"],
        ),
    )
    categories = {
        item["id"]: item["label"] for item in store.find("category")
    }
    category_labels: dict[str, list[str]] = {}
    for relation in store.find("relation", relation_type="classified_as"):
        values = relation["values"]
        label = categories.get(str(values.get("target_record_id")))
        if label:
            category_labels.setdefault(
                str(values.get("source_record_id")), []
            ).append(label)
    for labels in category_labels.values():
        labels[:] = sorted(set(labels), key=str.casefold)

    latest_event: dict[str, dict] = {}
    version_events = [
        *store.find("package_version_event"),
        *store.find("component_version_event"),
    ]
    for event in version_events:
        source_id = str(event["values"].get("source_record_id", ""))
        current = latest_event.get(source_id)
        if current is None or (event["created_at"], event["id"]) > (
            current["created_at"],
            current["id"],
        ):
            latest_event[source_id] = event
    anchor_ids = {
        str(event["values"].get("temporal_anchor_id"))
        for event in latest_event.values()
        if event["values"].get("temporal_anchor_id")
    }
    effective_anchors = {
        anchor_id: get_effective_temporal_anchor(store, anchor_id)
        for anchor_id in anchor_ids
    }
    anchors = {
        source_id: effective_anchors.get(
            str(event["values"].get("temporal_anchor_id")), {}
        )
        for source_id, event in latest_event.items()
    }
    by_package: dict[str, list[dict]] = {}
    for component in components:
        parent = _text(component["values"].get("parent_package_id"))
        by_package.setdefault(parent, []).append(component)

    lines = [
        "# Shared Artifact Catalog",
        "",
        "Auto-generated from SEDB. Do not hand-edit this file; update the catalog and regenerate it.",
        "",
        f"Packages: {len(packages)} · Components: {len(components)}",
        "",
    ]
    for package in packages:
        title = _text(package["values"].get("title") or package["label"])
        lines.extend([f"## {title}", ""])
        summary = _text(package["values"].get("summary"))
        if summary:
            lines.extend([summary, ""])
        lines.extend(
            _metadata_lines(
                package,
                digest_key="manifest_sha256",
                category_labels=category_labels,
                anchors=anchors,
            )
        )
        children = by_package.get(package["id"], [])
        if children:
            lines.extend(["", "### Components", ""])
        for component in children:
            component_title = _text(
                component["values"].get("title") or component["label"]
            )
            lines.extend([f"#### {component_title}", ""])
            lines.extend(
                _metadata_lines(
                    component,
                    digest_key="sha256",
                    category_labels=category_labels,
                    anchors=anchors,
                )
            )
            lines.append("")
        lines.append("")

    orphans = by_package.get("", [])
    if orphans:
        lines.extend(["## Unpackaged components", ""])
        for component in orphans:
            lines.extend([f"### {_text(component['label'])}", ""])
            lines.extend(
                _metadata_lines(
                    component,
                    digest_key="sha256",
                    category_labels=category_labels,
                    anchors=anchors,
                )
            )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_catalog(store: CatalogStore, path: str | Path) -> ExportResult:
    output_path = Path(path)
    rendered = render_catalog(store)
    encoded = rendered.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if output_path.is_file() and output_path.read_bytes() == encoded:
        return ExportResult(
            output_path,
            False,
            digest,
            len(store.find("package")),
            len(store.find("component")),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, output_path)
    return ExportResult(
        output_path,
        True,
        digest,
        len(store.find("package")),
        len(store.find("component")),
    )
