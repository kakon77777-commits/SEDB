from __future__ import annotations

from dataclasses import dataclass

from config import NAMESPACE


@dataclass(frozen=True)
class CatalogFieldSpec:
    key: str
    label: str
    value_type: str
    description: str
    ownership: str = "source"
    namespace: str = NAMESPACE
    status: str = "active"

    def as_sedb_spec(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "value_type": self.value_type,
            "description": self.description,
            "namespace": self.namespace,
            "status": self.status,
        }


@dataclass(frozen=True)
class CatalogViewSpec:
    name: str
    field_keys: tuple[str, ...]
    description: str


def _field(
    key: str,
    label: str,
    value_type: str,
    description: str,
) -> CatalogFieldSpec:
    return CatalogFieldSpec(key, label, value_type, description)


CATALOG_SOURCE_FIELD_SPECS = (
    _field("catalog_schema_version", "Catalog schema version", "text", "Version of the full static-canon projection."),
    _field("catalog_manifest_path", "Catalog manifest path", "text", "Frozen source-inventory manifest used for workbook verification."),
    _field("catalog_manifest_sha256", "Catalog manifest SHA-256", "text", "Verified SHA-256 of the source-inventory manifest."),
    _field("catalog_workbook_hashes", "Catalog workbook hashes", "json", "Ordered AllExcel table-to-SHA projection."),
    _field("catalog_table_counts", "Catalog table counts", "json", "Exact data-row count for every configured workbook."),
    _field("catalog_total_rows", "Catalog total rows", "integer", "Exact total represented AllExcel data rows."),
    _field("catalog_source_fingerprint", "Catalog source fingerprint", "text", "Deterministic hash over verified rows and source evidence."),
    _field("catalog_reader_version", "Catalog reader version", "text", "Version of the deterministic OpenXML reader."),
    _field("runtime_candidate_files", "Runtime candidate files", "json", "Frozen DAT path, length and SHA evidence without a decode claim."),
    _field("source_layer", "Source layer", "text", "Explicit data-layer classification for this source fact."),
    _field("source_authority", "Source authority", "text", "Evidence boundary for documented versus runtime authority."),
    _field("source_table", "Source table", "text", "AllExcel workbook table that owns the row."),
    _field("source_record_id", "Source record ID", "json", "Typed source Id value; strings and numbers remain distinct."),
    _field("source_workbook_path", "Source workbook path", "text", "Canonical frozen workbook member path."),
    _field("source_workbook_sha256", "Source workbook SHA-256", "text", "Verified source workbook SHA-256."),
    _field("source_row_sha256", "Source row SHA-256", "text", "SHA-256 of canonical compact row JSON."),
    _field("source_row_payload", "Source row payload", "json", "Complete canonical AllExcel row payload."),
    _field("description_tw", "Description (zh-Hant)", "text", "Source-observed Traditional Chinese description."),
    _field("flag", "Source flag", "boolean", "Source-observed row activation flag."),
    _field("card_name_tw", "Card name (zh-Hant)", "text", "Source-observed Traditional Chinese card name."),
    _field("level", "Level", "integer", "Source-observed Hero or progression level."),
    _field("hp", "HP", "integer", "Source-observed HP value."),
    _field("power", "Power", "integer", "Source-observed power value."),
    _field("is_player", "Is player", "boolean", "Whether the Hero row is marked as player-controlled."),
    _field("property_ids", "Property IDs", "json", "Ordered non-sentinel Property references."),
    _field("ji_values", "Ji values", "json", "Ordered Ji identifier/value pairs."),
    _field("is_atlas", "Is atlas", "boolean", "Source-observed atlas membership flag."),
    _field("atlas_index", "Atlas index", "integer", "Source-observed atlas index."),
    _field("acquisition_description", "Acquisition description", "text", "Source-observed acquisition text."),
    _field("acquisition_description_tw", "Acquisition description (zh-Hant)", "text", "Traditional Chinese acquisition text."),
    _field("point_value", "Point value", "number", "Source-observed point or cost value."),
    _field("next_dialog_id", "Next dialog ID", "json", "Source-observed next EventDialog identifier."),
    _field("next_event_id", "Next event ID", "json", "Source-observed next Event identifier."),
    _field("condition_operations", "Condition operations", "json", "Ordered normalized Condition slots."),
    _field("event_result_operations", "Event result operations", "json", "Ordered normalized EventResult slots."),
    _field("selection_options", "Selection options", "json", "Ordered normalized EventSelection options."),
    _field("guide_steps", "Guide steps", "json", "Ordered normalized Relation guide steps."),
    _field("edge_source_entity_id", "Edge source entity ID", "text", "Entity that owns the explicit source reference."),
    _field("edge_source_table", "Edge source table", "text", "Table containing the explicit reference."),
    _field("edge_source_field", "Edge source field", "text", "Field containing the explicit reference."),
    _field("edge_slot", "Edge slot", "integer", "Repeated-field or multi-value slot ordinal."),
    _field("edge_raw_value", "Edge raw value", "json", "Raw source reference value before target resolution."),
    _field("edge_target_table", "Edge target table", "text", "Reviewed target table for the reference rule."),
    _field("edge_target_source_id", "Edge target source ID", "json", "Typed target source identifier."),
    _field("edge_target_entity_id", "Edge target entity ID", "text", "Resolved target entity when present."),
    _field("edge_resolution_status", "Edge resolution status", "text", "Resolved, missing-target, or unknown-semantics status."),
    _field("edge_rule_id", "Edge rule ID", "text", "Stable reviewed reference-rule identifier."),
    _field("edge_rule_version", "Edge rule version", "text", "Version of the complete reference-rule registry."),
    _field("edge_evidence_level", "Edge evidence level", "text", "Evidence basis supporting the source-to-target interpretation."),
    _field("edge_claim_boundary", "Edge claim boundary", "text", "Static-link boundary that explicitly excludes runtime reachability."),
    _field("analysis_name", "Analysis name", "text", "Static gameplay analysis that owns this metric."),
    _field("metric_key", "Metric key", "text", "Stable machine-readable gameplay metric key."),
    _field("metric_value", "Metric value", "json", "Typed metric value and structured details."),
    _field("claim_class", "Claim class", "text", "Observed, inferred, unknown, or falsifying-test class."),
    _field("evidence_basis", "Evidence basis", "json", "Paths, entity IDs, rules and fingerprints supporting a claim."),
    _field("falsifying_test", "Falsifying test", "text", "Future test capable of disproving the bounded claim."),
)

CATALOG_SOURCE_OWNED_KEYS = frozenset(
    field.key for field in CATALOG_SOURCE_FIELD_SPECS
)


CATALOG_VIEW_SPECS = (
    CatalogViewSpec(
        "AllExcel Table Catalog",
        ("source_table", "source_record_id", "name_zh", "title", "description", "flag", "source_row", "source_row_sha256", "source_workbook_path", "source_layer", "record_status"),
        "Compact locator and provenance view for every represented AllExcel row.",
    ),
    CatalogViewSpec(
        "Full Hero Context",
        ("hero_id", "id_name", "name_zh", "name_tw", "title", "title_tw", "card_name", "card_name_tw", "base_description", "description", "description_tw", "level", "hp", "power", "rarity", "skill_ids", "property_ids", "ji_values", "birth_id", "faction_text", "parent_id", "route_filter", "story_id", "source_row", "source_row_sha256"),
        "Complete source-observed Hero background, stats, skills and route fields.",
    ),
    CatalogViewSpec(
        "World and Map Context",
        ("source_table", "source_record_id", "name_zh", "name_tw", "description", "description_tw", "parent_id", "birth_id", "source_row", "source_row_sha256"),
        "Birth, Map and MapInfo rows with compact hierarchy evidence.",
    ),
    CatalogViewSpec(
        "Relationship Routes",
        ("source_record_id", "name_zh", "name_tw", "description", "description_tw", "guide_steps", "birth_id", "property_ids", "source_row", "source_row_sha256"),
        "Relationship route prose, ordered guide steps and source locators.",
    ),
    CatalogViewSpec(
        "Event Network",
        ("source_table", "source_record_id", "name_zh", "title", "description", "condition_operations", "event_result_operations", "selection_options", "next_dialog_id", "next_event_id", "source_row", "source_row_sha256"),
        "Static Event and logic-record summaries without runtime reachability claims.",
    ),
    CatalogViewSpec(
        "Dialogue Index",
        ("source_record_id", "name_zh", "title", "next_dialog_id", "next_event_id", "source_row", "source_row_sha256", "source_workbook_path"),
        "Compact EventDialog locator; full dialogue remains in the row payload.",
    ),
    CatalogViewSpec(
        "Combat and Progression",
        ("source_table", "source_record_id", "name_zh", "description", "level", "hp", "power", "condition_operations", "event_result_operations", "source_row", "source_row_sha256"),
        "Battle, Skill, Formula, Effect, Buff and Difficulty source evidence.",
    ),
    CatalogViewSpec(
        "Reference Resolution",
        ("edge_source_entity_id", "edge_source_table", "edge_source_field", "edge_slot", "edge_raw_value", "edge_target_table", "edge_target_source_id", "edge_target_entity_id", "edge_resolution_status", "edge_rule_id", "edge_rule_version", "edge_evidence_level", "edge_claim_boundary"),
        "Resolved, missing and unknown static reference edges.",
    ),
    CatalogViewSpec(
        "Static Gameplay Questions",
        ("analysis_name", "metric_key", "metric_value", "claim_class", "evidence_basis", "falsifying_test"),
        "Evidence-bounded gameplay metrics and claims.",
    ),
    CatalogViewSpec(
        "Catalog Provenance",
        ("source_build_id", "catalog_schema_version", "catalog_manifest_path", "catalog_manifest_sha256", "catalog_workbook_hashes", "catalog_table_counts", "catalog_total_rows", "catalog_source_fingerprint", "catalog_reader_version", "runtime_candidate_files"),
        "Full-catalog Build evidence and frozen runtime-candidate projection.",
    ),
)
