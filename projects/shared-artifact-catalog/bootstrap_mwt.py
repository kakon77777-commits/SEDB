from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ingest import IngestResult, ingest_registered_packages
from paths import CatalogConfig, sha256_file
from schema import CatalogStore
from taxonomy import (
    add_classifications_bulk,
    existing_classification_pairs,
)
from temporal import CtclClient, create_temporal_anchor


UNBOUNDED_AXIOM = "https://unboundedaxiom.org/"
NEOK = "https://thisoneisneok.com/"


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
    if normalized.startswith("10_Theory/"):
        canonicality = (
            "canonical_candidate"
            if name == "MWT_v0.1_First_Cycle_Canonical_Pack"
            else "public_draft_candidate"
        )
        return PackageDescriptor(
            ("theory", "documentation"),
            "verified_integrity_candidate",
            canonicality,
            ("zh-Hant", "en"),
            (),
            (),
            (UNBOUNDED_AXIOM,),
            "MWT theory candidate retained without publication authority.",
        )
    if normalized.startswith("20_Applications/"):
        return PackageDescriptor(
            (
                "experimental_application",
                "application",
                "source_code",
                "validation_evidence",
            ),
            "verified_runtime_candidate",
            "latest_candidate",
            ("en",),
            ("en",),
            ("JavaScript",),
            (NEOK,),
            "Latest supplied DGW experimental web application candidate.",
        )
    if "/DGW_Version_History/" in normalized:
        return PackageDescriptor(
            ("archive", "research_evidence", "source_code", "validation_evidence"),
            "reported_validation",
            "superseded",
            ("en",),
            ("en",),
            ("JavaScript",),
            (),
            "Historical DGW release retained for research provenance.",
        )
    if "/Reference_Source_Packs/" in normalized:
        return PackageDescriptor(
            ("research_evidence", "source_code", "documentation"),
            "verified_reference",
            "supporting",
            ("zh-Hant", "en"),
            (),
            ("Python",),
            (),
            "MWT reference source pack with schemas, examples, and supporting code.",
        )
    if "/Executable_Spikes/" in normalized:
        return PackageDescriptor(
            ("research_evidence", "experimental_application", "source_code"),
            "verified_reference",
            "research_spike",
            ("en",),
            (),
            ("Python",),
            (),
            "Executable finite-world research spike; not a product runtime.",
        )
    if "/Legacy_Duplicate_Bundles/" in normalized:
        return PackageDescriptor(
            ("archive", "theory"),
            "verified_duplicate",
            "superseded_duplicate",
            ("zh-Hant",),
            (),
            (),
            (),
            "Legacy bundle whose Markdown content duplicates canonical-pack files.",
        )
    if "/Dependent_or_PostCycle_Extensions/" in normalized:
        programming = ("Python",) if "SWL_02" in name else ()
        categories = ["needs_review", "documentation"]
        if "MWT_11" in name:
            categories.append("theory")
        if programming:
            categories.append("source_code")
        return PackageDescriptor(
            tuple(categories),
            "needs_review",
            "post_cycle_unresolved",
            ("zh-Hant", "en"),
            (),
            programming,
            (),
            "Dependent or post-cycle extension held for sequencing review.",
        )
    if "/Theory_Drafts_and_Precursors/" in normalized:
        return PackageDescriptor(
            ("needs_review", "theory", "documentation"),
            "needs_review",
            "draft_or_precursor",
            ("zh-Hant", "en"),
            (),
            (),
            (),
            "Theory draft or precursor retained without automatic promotion.",
        )
    raise ValueError(f"unmapped MWT package root: {relative}")


def _changed_values(record: dict, desired: dict) -> dict:
    current = record["values"]
    return {
        key: value for key, value in desired.items() if current.get(key) != value
    }


def bootstrap_mwt(
    config: CatalogConfig,
    store: CatalogStore,
    temporal_client: CtclClient,
) -> IngestResult:
    classification_record = (
        config.catalog_root
        / "00_Inbox"
        / "MWT_2026-08-24"
        / "MWT_CLASSIFICATION.md"
    )
    if not classification_record.is_file():
        raise FileNotFoundError(classification_record)
    classification_sha = sha256_file(classification_record)

    ingest_result = ingest_registered_packages(config, store, temporal_client)
    packages_by_rel = {
        str(record["values"]["source_relpath"]): record
        for record in store.find("package")
    }
    existing_relations = existing_classification_pairs(store)
    metadata_updates: list[tuple[dict, dict]] = []
    classifications: list[tuple[str, str]] = []

    for configured_root in config.package_roots:
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

        components = store.find(
            "component", parent_package_id=package["id"]
        )
        for component in components:
            media_class = component["values"].get("media_class")
            component_values: dict = {}
            if media_class in {"text", "document"}:
                component_values["content_languages"] = list(
                    descriptor.content_languages
                )
            if media_class in {"source"} and descriptor.interface_languages:
                component_values["interface_languages"] = list(
                    descriptor.interface_languages
                )
            component_changes = _changed_values(
                component, component_values
            )
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
            "mwt_bootstrap",
            timezone_name=config.timezone,
        )["id"]

    store.update_current_bulk(
        [
            (
                record["id"],
                {**changes, "temporal_anchor_id": anchor_id},
                "artifact-catalog:mwt-bootstrap",
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
    parser = argparse.ArgumentParser(description="Bootstrap the MWT catalog")
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
    result = bootstrap_mwt(config, store, client)
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
