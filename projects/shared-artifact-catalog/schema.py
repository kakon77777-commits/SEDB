from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


NAMESPACE = "artifact_catalog"


def _field(
    key: str, label: str, value_type: str = "text", description: str = ""
) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "value_type": value_type,
        "description": description,
        "namespace": NAMESPACE,
    }


FIELD_SPECS = [
    _field("stable_key", "Stable key"),
    _field("title", "Title"),
    _field("description", "Description"),
    _field("source_path", "Source path"),
    _field("source_relpath", "Source relative path"),
    _field("parent_package_id", "Parent package id"),
    _field("version", "Version"),
    _field("canonicality_state", "Canonicality state"),
    _field("availability_state", "Availability state"),
    _field("sha256", "SHA-256"),
    _field("manifest_sha256", "Manifest SHA-256"),
    _field("size_bytes", "Size bytes", "integer"),
    _field("extension", "Extension"),
    _field("media_class", "Media class"),
    _field("content_identity", "Content identity"),
    _field("content_languages", "Content languages", "json"),
    _field("interface_languages", "Interface languages", "json"),
    _field("programming_languages", "Programming languages", "json"),
    _field("dependency_mode", "Dependency mode"),
    _field("required_component_ids", "Required component ids", "json"),
    _field("verification_state", "Verification state"),
    _field("publication_state", "Publication state"),
    _field("suggested_routes", "Suggested routes", "json"),
    _field("keywords", "Keywords", "json"),
    _field("summary", "Summary"),
    _field("filesystem_modified_at_local", "Filesystem modified at local"),
    _field("relation_type", "Relation type"),
    _field("source_record_id", "Source record id"),
    _field("target_record_id", "Target record id"),
    _field("category_state", "Category state"),
    _field("parent_category_id", "Parent category id"),
    _field("alias_target_id", "Alias target id"),
    _field("definition", "Definition"),
    _field("examples", "Examples", "json"),
    _field("insufficiency_reason", "Insufficiency reason"),
    _field("proposer_claim", "Proposer claim"),
    _field("host_task_id", "Host task id"),
    _field("decision", "Decision"),
    _field("decision_reason", "Decision reason"),
    _field("registrar", "Registrar"),
    _field("temporal_anchor_id", "Temporal anchor id"),
    _field("ctcl_instant_id", "CTCL instant id"),
    _field("ctcl_utc", "CTCL UTC"),
    _field("ctcl_local", "CTCL local"),
    _field("ctcl_source", "CTCL source"),
    _field("ctcl_precision", "CTCL precision"),
    _field("ctcl_uncertainty_ns", "CTCL uncertainty ns", "integer"),
    _field("local_observed_at", "Local observed at"),
    _field("temporal_status", "Temporal status"),
    _field("operation_kind", "Operation kind"),
    _field("batch_id", "Batch id"),
    _field("copy_mode", "Copy mode"),
    _field("destination_path", "Destination path"),
    _field("responsibility_ref", "Responsibility ref"),
    _field("requester_claim", "Requester claim"),
    _field("purpose", "Purpose"),
    _field("outcome", "Outcome"),
    _field("verification_result", "Verification result"),
    _field("failure_reason", "Failure reason"),
    _field("source_component_id", "Source component id"),
    _field("source_sha256", "Source SHA-256"),
    _field("source_language", "Source language"),
    _field("target_language", "Target language"),
    _field("translation_scope", "Translation scope"),
    _field("job_path", "Job path"),
    _field("lifecycle_state", "Lifecycle state"),
    _field("output_component_ids", "Output component ids", "json"),
    _field("technical_review", "Technical review", "json"),
    _field("semantic_review", "Semantic review", "json"),
]


CATEGORY_SEEDS = {
    "theory": {
        "label": "Theory",
        "definition": "Formal or conceptual theoretical material.",
    },
    "research_data": {
        "label": "Research data",
        "definition": "Data produced, collected, or used for research.",
    },
    "research_evidence": {
        "label": "Research evidence",
        "definition": "Measurements, findings, reports, or evidence artifacts.",
    },
    "experimental_application": {
        "label": "Experimental application",
        "definition": "Runnable application intended for bounded experimentation.",
    },
    "application": {
        "label": "Application",
        "definition": "Runnable application or product-oriented software.",
    },
    "website_shell": {
        "label": "Website shell",
        "definition": "Presentation, routing, or website delivery layer.",
    },
    "source_code": {
        "label": "Source code",
        "definition": "Program source used to implement or test an artifact.",
    },
    "documentation": {
        "label": "Documentation",
        "definition": "Explanatory, operational, or interface documentation.",
    },
    "validation_evidence": {
        "label": "Validation evidence",
        "definition": "Test, benchmark, manifest, or verification evidence.",
    },
    "archive": {
        "label": "Archive",
        "definition": "Historical or superseded material retained for provenance.",
    },
    "needs_review": {
        "label": "Needs review",
        "definition": "Material whose classification, status, or routing is unresolved.",
    },
}


VIEW_SPECS = {
    "Theory": (
        "title",
        "summary",
        "content_languages",
        "verification_state",
        "publication_state",
        "ctcl_local",
    ),
    "Research Data and Evidence": (
        "title",
        "summary",
        "verification_state",
        "source_relpath",
        "ctcl_local",
    ),
    "Applications": (
        "title",
        "version",
        "programming_languages",
        "verification_state",
        "publication_state",
    ),
    "Website Components": (
        "title",
        "interface_languages",
        "programming_languages",
        "suggested_routes",
    ),
    "Mixed Packages": (
        "title",
        "summary",
        "manifest_sha256",
        "verification_state",
    ),
    "Needs Review": (
        "title",
        "summary",
        "verification_state",
        "failure_reason",
    ),
    "Translation Candidates": (
        "source_component_id",
        "source_language",
        "target_language",
        "translation_scope",
        "lifecycle_state",
    ),
    "Classification Proposals": (
        "stable_key",
        "definition",
        "insufficiency_reason",
        "proposer_claim",
        "decision",
    ),
    "Copy History": (
        "source_record_id",
        "destination_path",
        "copy_mode",
        "outcome",
        "ctcl_local",
    ),
}


MUTABLE_KINDS = frozenset(
    {"package", "component", "category", "translation_job"}
)
EVENT_KINDS = frozenset(
    {
        "copy_event",
        "registration_decision",
        "temporal_reconciliation",
        "relation",
        "classification_proposal",
        "translation_event",
        "component_version_event",
        "package_version_event",
    }
)


@dataclass
class CatalogStore:
    db: Database
    fields: FieldService
    entities: EntityService
    views: ViewService

    @classmethod
    def open(cls, path: str | Path) -> "CatalogStore":
        db = Database(path)
        return cls(
            db=db,
            fields=FieldService(db),
            entities=EntityService(db),
            views=ViewService(db),
        )

    def ensure_schema(self) -> None:
        existing = {
            row["key"] for row in self.fields.list_fields(limit=10_000)
        }
        missing = [spec for spec in FIELD_SPECS if spec["key"] not in existing]
        if missing:
            self.fields.bulk_create_fields(missing)

        for key, spec in CATEGORY_SEEDS.items():
            entity_id = f"category:{key}"
            if not self._entity_exists(entity_id):
                self.create_record(
                    "category",
                    spec["label"],
                    {
                        "stable_key": key,
                        "title": spec["label"],
                        "definition": spec["definition"],
                        "category_state": "active",
                    },
                    entity_id=entity_id,
                    source="system:artifact-catalog-seed",
                )

        existing_view_names = {
            row["name"] for row in self.views.list_views()
        }
        for name, keys in VIEW_SPECS.items():
            if name not in existing_view_names:
                self.views.create_view(name, keys)

    def _entity_exists(self, entity_id: str) -> bool:
        with self.db.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM entities WHERE id=?", (entity_id,)
                ).fetchone()
                is not None
            )

    def _validate_field_keys(self, values: dict[str, Any]) -> None:
        for key in values:
            self.fields.get_field(key)

    def create_record(
        self,
        kind: str,
        label: str,
        values: dict[str, Any] | None = None,
        *,
        entity_id: str | None = None,
        source: str = "artifact-catalog",
    ) -> dict[str, Any]:
        record_id = entity_id or f"{kind}:{uuid4().hex}"
        if self._entity_exists(record_id):
            raise ValueError(f"record already exists: {record_id}")
        payload = values or {}
        self._validate_field_keys(payload)
        self.entities.create_entity(
            label=label, kind=kind, entity_id=record_id
        )
        for key, value in payload.items():
            self.entities.set_cell(record_id, key, value, source=source)
        return self.get_record(record_id)

    def get_record(self, entity_id: str) -> dict[str, Any]:
        return self.entities.get_entity(entity_id, include_cells=True)

    def find(self, kind: str, **cell_filters: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for stub in self.entities.list_entities(limit=10_000):
            if stub["kind"] != kind:
                continue
            record = self.get_record(stub["id"])
            values = record["values"]
            if all(values.get(key) == value for key, value in cell_filters.items()):
                results.append(record)
        return results

    def update_current(
        self,
        entity_id: str,
        values: dict[str, Any],
        source: str = "artifact-catalog",
    ) -> dict[str, Any]:
        record = self.get_record(entity_id)
        if record["kind"] not in MUTABLE_KINDS:
            raise ValueError(
                f"immutable event record cannot be updated: {record['kind']}"
            )
        self._validate_field_keys(values)
        for key, value in values.items():
            self.entities.set_cell(entity_id, key, value, source=source)
        return self.get_record(entity_id)

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        anchor_id: str,
        *,
        source: str = "artifact-catalog",
    ) -> dict[str, Any]:
        self.get_record(source_id)
        self.get_record(target_id)
        self.get_record(anchor_id)
        return self.create_record(
            "relation",
            f"{source_id} {relation_type} {target_id}",
            {
                "source_record_id": source_id,
                "target_record_id": target_id,
                "relation_type": relation_type,
                "temporal_anchor_id": anchor_id,
            },
            source=source,
        )

    def integrity_check(self) -> str:
        with self.db.connect() as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
