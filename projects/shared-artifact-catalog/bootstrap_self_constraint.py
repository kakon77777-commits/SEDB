from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ingest import IngestResult, ingest_package_paths
from paths import CatalogConfig, sha256_file
from schema import CatalogStore
from taxonomy import (
    add_classifications_bulk,
    existing_classification_pairs,
)
from temporal import CtclClient, create_temporal_anchor


UNBOUNDED_AXIOM = "https://unboundedaxiom.org/"
NEOK = "https://thisoneisneok.com/"
FAMILY = "Self_Constraint_Cognitive_Runtime"


@dataclass(frozen=True)
class PackageDescriptor:
    categories: tuple[str, ...]
    verification_state: str
    canonicality_state: str
    content_languages: tuple[str, ...]
    interface_languages: tuple[str, ...]
    programming_languages: tuple[str, ...]
    suggested_routes: tuple[str, ...]
    summary: str


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", name.lower()).strip("-")


def _descriptor(relative: str) -> PackageDescriptor:
    normalized = relative.replace("\\", "/")
    name = Path(relative).name
    parts = normalized.split("/")
    if len(parts) < 2 or parts[1] != FAMILY:
        raise ValueError(f"unmapped self-constraint package root: {relative}")

    if normalized.startswith("10_Theory/"):
        languages = ("zh-Hant",) if "/zh-Hant/" in normalized else ("en",)
        return PackageDescriptor(
            ("theory", "documentation"),
            "verified_integrity_candidate",
            "canonical_extracted_set",
            languages,
            (),
            (),
            (UNBOUNDED_AXIOM,),
            "Focused self-constraint or cognitive-runtime theory set retained without publication authority.",
        )

    if normalized.startswith("20_Applications/"):
        verification = (
            "independently_verified_runtime_candidate"
            if name.startswith("Addressable_Cognitive_Runtime")
            else "independently_verified_offline_candidate"
        )
        return PackageDescriptor(
            (
                "experimental_application",
                "application",
                "source_code",
                "validation_evidence",
                "documentation",
            ),
            verification,
            "latest_candidate",
            ("zh-Hant", "en"),
            ("en", "zh-Hant"),
            ("Python",),
            (NEOK,),
            "Latest supplied experimental runtime candidate; no deployment or live-provider authority is implied.",
        )

    if "/ACR_Version_History/" in normalized:
        return PackageDescriptor(
            (
                "archive",
                "research_evidence",
                "source_code",
                "validation_evidence",
                "documentation",
            ),
            "reported_validation",
            "superseded",
            ("zh-Hant", "en"),
            ("en",),
            ("Python",),
            (),
            "Historical cumulative ACR release retained for research provenance.",
        )

    if "/Harness_Version_History/" in normalized:
        return PackageDescriptor(
            (
                "archive",
                "research_evidence",
                "source_code",
                "validation_evidence",
                "documentation",
            ),
            "reported_validation",
            "superseded",
            ("en", "zh-Hant"),
            ("en", "zh-Hant"),
            ("Python",),
            (),
            "Historical Self-Constraint Harness release retained for research provenance.",
        )

    if "/Executable_Experiments/" in normalized:
        is_scl = name.startswith("SCL_")
        independently_verified = is_scl or "v0.2" in name
        return PackageDescriptor(
            (
                "research_evidence",
                "experimental_application",
                "source_code",
                "validation_evidence",
                "documentation",
            )
            + (("theory",) if is_scl else ()),
            (
                "independently_verified_test_suite"
                if independently_verified
                else "supplied_research_package"
            ),
            "current_research" if independently_verified else "superseded",
            ("en",),
            ("en",),
            ("Python", "JavaScript") if is_scl else ("Python",),
            (),
            "Executable bounded research experiment; not foundation-model or universal-effect evidence.",
        )

    if "/Reference_Source_Packs/" in normalized:
        return PackageDescriptor(
            (
                "research_evidence",
                "theory",
                "documentation",
                "validation_evidence",
            ),
            "verified_duplicate_source_pack",
            "supporting",
            ("zh-Hant", "en"),
            (),
            (),
            (),
            "Supporting theory source pack whose principal papers match the extracted canonical set.",
        )

    if "/Legacy_Standalone_Duplicates" in normalized:
        return PackageDescriptor(
            ("archive", "theory", "documentation"),
            "verified_duplicate",
            "superseded_duplicate",
            ("zh-Hant",),
            (),
            (),
            (),
            "Standalone supplied papers retained as byte-verified duplicate source originals.",
        )

    if normalized.startswith("90_Needs_Review/"):
        return PackageDescriptor(
            ("needs_review", "theory", "documentation"),
            "text_reviewed_visual_qa_unavailable",
            "legacy_theory_papers",
            ("en",),
            (),
            (),
            (),
            "Unique legacy theory papers held for substantive review and DOCX visual QA.",
        )

    raise ValueError(f"unmapped self-constraint package root: {relative}")


def _changed_values(record: dict, desired: dict) -> dict:
    current = record["values"]
    return {
        key: value for key, value in desired.items() if current.get(key) != value
    }


def bootstrap_self_constraint(
    config: CatalogConfig,
    store: CatalogStore,
    temporal_client: CtclClient,
) -> IngestResult:
    classification_record = (
        config.catalog_root
        / "00_Inbox"
        / "Self_Constraint_Experimental_Harness_2026-08-25"
        / "SELF_CONSTRAINT_CLASSIFICATION.md"
    )
    if not classification_record.is_file():
        raise FileNotFoundError(classification_record)
    classification_sha = sha256_file(classification_record)

    family_roots = tuple(
        item
        for item in config.package_roots
        if len(Path(item).as_posix().split("/")) >= 2
        and Path(item).as_posix().split("/")[1] == FAMILY
    )
    ingest_result = ingest_package_paths(
        (config.catalog_root / item for item in family_roots),
        config,
        store,
        temporal_client,
    )
    packages_by_rel = {
        str(record["values"]["source_relpath"]): record
        for record in store.find("package")
    }
    existing_relations = existing_classification_pairs(store)
    metadata_updates: list[tuple[dict, dict]] = []
    classifications: list[tuple[str, str]] = []

    for configured_root in family_roots:
        relative = Path(configured_root).as_posix()
        package = packages_by_rel.get(relative)
        if package is None:
            raise KeyError(f"ingested package not found: {relative}")
        descriptor = _descriptor(relative)
        package_values = {
            "stable_key": _slug(Path(configured_root).name),
            "title": Path(configured_root).name.replace("_", " "),
            "summary": descriptor.summary,
            "description": f"Initial classification record SHA-256 {classification_sha}",
            "verification_state": descriptor.verification_state,
            "canonicality_state": descriptor.canonicality_state,
            "publication_state": "not_published",
            "content_languages": list(descriptor.content_languages),
            "interface_languages": list(descriptor.interface_languages),
            "programming_languages": list(descriptor.programming_languages),
            "suggested_routes": list(descriptor.suggested_routes),
        }
        changes = _changed_values(package, package_values)
        if changes:
            metadata_updates.append((package, changes))

        components = store.find("component", parent_package_id=package["id"])
        for component in components:
            media_class = component["values"].get("media_class")
            component_values: dict = {}
            if media_class in {"text", "document"}:
                component_values["content_languages"] = list(
                    descriptor.content_languages
                )
            if media_class == "source" and descriptor.interface_languages:
                component_values["interface_languages"] = list(
                    descriptor.interface_languages
                )
            component_changes = _changed_values(component, component_values)
            if component_changes:
                metadata_updates.append((component, component_changes))

        targets = [package, *components]
        for target in targets:
            for category_key in descriptor.categories:
                category_id = f"category:{category_key}"
                if (target["id"], category_id) not in existing_relations:
                    classifications.append((target["id"], category_id))
                    existing_relations.add((target["id"], category_id))

    if not metadata_updates and not classifications:
        return ingest_result

    anchor_id = ingest_result.temporal_anchor_id
    if anchor_id is None:
        anchor_id = create_temporal_anchor(
            store,
            temporal_client,
            "self_constraint_bootstrap",
            timezone_name=config.timezone,
        )["id"]

    store.update_current_bulk(
        [
            (
                record["id"],
                {**changes, "temporal_anchor_id": anchor_id},
                "artifact-catalog:self-constraint-bootstrap",
            )
            for record, changes in metadata_updates
        ]
    )
    created_classifications = add_classifications_bulk(
        store,
        classifications,
        "catalog-registrar",
        anchor_id,
    )
    return IngestResult(
        changed_count=(
            ingest_result.changed_count
            + len(metadata_updates)
            + created_classifications
        ),
        package_count=ingest_result.package_count,
        component_count=ingest_result.component_count,
        temporal_anchor_id=anchor_id,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap the self-constraint catalog family"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("catalog-config.json"),
    )
    args = parser.parse_args(argv)
    config = CatalogConfig.load(args.config)
    store = CatalogStore.open(config.database_path)
    store.ensure_schema()
    client = CtclClient(config.ctcl_base_url, config.ctcl_timeout_seconds)
    result = bootstrap_self_constraint(config, store, client)
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
