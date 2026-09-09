from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


SOURCE_ROOT = Path(r"D:\AI_RESIDENCE\AI_gamedesign\FromJianghu-research")
DATABASE_NAME = "fromjianghu-static-catalog.sqlite"
NAMESPACE = "fromjianghu_static_catalog"
SCHEMA_VERSION = "fromjianghu-static-catalog/v1"
CURRENT_BUILD_ID = 25099888
CELL_SOURCE = "fromjianghu:static-research"

SOURCE_HASHES = {
    "evidence/source-identity.json": "c856949018c952f8cfae820754f9c395d6916579d1480e67c19eb31068903f07",
    "evidence/build-25099888/source-identity.json": "2d555806484d22c9ebb3d2c23571290dda91efa7b582c27db4f96a8d7ec895dc",
    "evidence/build-25099888/build-delta-summary.json": "3f64f7b441cc0d27aef6cb56007290fc879e8d77d0bf803b740bfce4a3bb17ad",
    "evidence/build-25099888/state-model-summary.json": "5ee396c59340355ae163ee07337dcbdc79212f3977599502a5e535e431d8ffb9",
    "evidence/build-25099888/model-source-inventory.csv": "da282596f94578c5ebc34d8b8e29b160d65003cfcf62c3a342e4a88fd11fae5e",
    "evidence/build-25099888/trigger-function-usage.csv": "41519acc86bf0b203ee556cc2ebd7fbd289e3e5b590e2a4a08cdeea625c56cf7",
    "evidence/build-25099888/trigger-summary.csv": "674f3bdbee2d1f48830d399b2bc08a2cb7947ef3bb0c1ef8f0fc28b7a68c7b7e",
    "derived/build-25099888/decrypted_game_data/Game/Function.json": "fc6b0fb0d8207da92a869042025b09dea161e78da44fadd3f1176e07c779ab4b",
    "derived/build-25099888/decrypted_config/filelistinfoE.json": "729f464d6154f3633ae6d203a397f9d390fd5c8e16088bfb5f8e481005dcd214",
    "toolchain/reports/evidence-ledger.md": "19e12d3e3c8473c0c2d76430c3ccf092d0f89bb28cdfe93c1829dd2d463382d7",
    "evidence/build-25099888/il-anchor-summary.json": "f850f2358b71e8d9e3550272abe863bdfdcf67042d15c26315e403fc240def22",
    "evidence/build-25099888/il-anchor-old-build-24413414-summary.json": "8276d11acaa12abb6cc83a42a1147db972d70016ec719199adee07534c66775e",
}

ENTITY_COUNTS = {
    "fj_build_snapshot": 2,
    "fj_build_delta": 1,
    "fj_model_snapshot": 72,
    "fj_function_snapshot": 1209,
    "fj_trigger_snapshot": 2364,
    "fj_asset_snapshot": 3287,
    "fj_evidence_claim": 23,
    "fj_il_anchor": 21,
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    value_type: str
    description: str

    def as_sedb_spec(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "value_type": self.value_type,
            "description": self.description,
            "namespace": NAMESPACE,
            "status": "active",
        }


@dataclass(frozen=True)
class ViewSpec:
    name: str
    field_keys: tuple[str, ...]
    description: str


def _fields(definitions: tuple[tuple[str, str, str, str], ...]) -> tuple[FieldSpec, ...]:
    return tuple(FieldSpec(*definition) for definition in definitions)


COMMON_FIELDS = _fields((
    ("fj_record_key", "Record key", "text", "Stable source-side record key."),
    ("fj_classification", "Classification", "text", "Reviewed static classification for the entity."),
    ("fj_source_build_id", "Source Build ID", "integer", "Steam Build owning the record when applicable."),
    ("fj_source_schema", "Source schema", "text", "Exact schema or source format identifier."),
    ("fj_source_path", "Source path", "text", "Path relative to the read-only FromJianghu research root."),
    ("fj_source_sha256", "Source SHA-256", "text", "Pinned SHA-256 of the primary source artifact."),
    ("fj_source_record_sha256", "Record SHA-256", "text", "SHA-256 of canonical source-owned record values."),
    ("fj_evidence_level", "Evidence level", "text", "Observed, constructed, inferred, or unknown evidence class."),
    ("fj_claim_boundary", "Claim boundary", "text", "Scope that must not be promoted beyond the evidence."),
    ("fj_record_status", "Record status", "text", "Current, historical, changed, or unresolved state."),
    ("fj_runtime_status", "Runtime status", "text", "Runtime evidence state; static records use not_started."),
    ("fj_source_ordinal", "Source ordinal", "integer", "Deterministic position in the selected source artifact."),
))

BUILD_FIELDS = _fields((
    ("fj_game_version", "Game version", "text", "Managed-code game version."),
    ("fj_steam_app_id", "Steam App ID", "integer", "Steam application identifier."),
    ("fj_depot_id", "Depot ID", "integer", "Steam depot identifier."),
    ("fj_depot_manifest", "Depot manifest", "text", "Steam depot manifest identifier."),
    ("fj_depot_file_count", "Depot file count", "integer", "Files in the fingerprinted depot candidate."),
    ("fj_depot_bytes", "Depot bytes", "integer", "Bytes in the fingerprinted depot candidate."),
    ("fj_baseline_path", "Baseline path", "text", "Current immutable research-baseline path."),
    ("fj_appmanifest_sha256", "Appmanifest SHA-256", "text", "Captured Steam appmanifest SHA-256."),
))

MODEL_FIELDS = _fields((
    ("fj_model_class", "Model class", "text", "Managed state-owner class."),
    ("fj_model_name", "Model name", "text", "Runtime model name where statically recoverable."),
    ("fj_game_data_type", "Game-data type", "text", "Declared game-data owner type."),
    ("fj_user_data_type", "User-data type", "text", "Declared persisted user-data owner type."),
    ("fj_has_load_game_data", "Loads game data", "boolean", "Whether the model implements game-data loading."),
    ("fj_has_load_user_data", "Loads user data", "boolean", "Whether the model implements user-data loading."),
    ("fj_has_after_load_user_data", "After-load hook", "boolean", "Whether the model implements the after-user-load hook."),
    ("fj_has_save_game", "Save hook", "boolean", "Whether the model implements SaveGame."),
    ("fj_save_call_count", "Save call count", "integer", "Static count of save calls in the model source."),
    ("fj_has_update", "Update hook", "boolean", "Whether the model owns an Update hook."),
    ("fj_has_late_update", "LateUpdate hook", "boolean", "Whether the model owns a LateUpdate hook."),
    ("fj_random_call_count", "Random call count", "integer", "Static Unity-random call count."),
    ("fj_event_listener_count", "Event listener count", "integer", "Static event-listener registration count."),
    ("fj_event_broadcast_count", "Event broadcast count", "integer", "Static event broadcast count."),
    ("fj_dictionary_field_count", "Dictionary field count", "integer", "Static dictionary field count."),
    ("fj_hashset_field_count", "HashSet field count", "integer", "Static HashSet field count."),
    ("fj_initialization_order", "Initialization order", "integer", "One-based GlobalManager initialization position."),
))

FUNCTION_FIELDS = _fields((
    ("fj_function_id", "Function ID", "text", "Declarative function identifier."),
    ("fj_function_enum_id", "Function enum ID", "integer", "0.6.16 numeric CustomFunctionType mapping."),
    ("fj_function_name", "Function name", "text", "Source-observed localized name."),
    ("fj_return_type", "Return type", "text", "Declarative return-value type."),
    ("fj_function_catalog", "Function catalog", "text", "Source function category."),
    ("fj_hidden_in_mod", "Hidden in mod", "boolean", "Whether the function is hidden from the mod UI."),
    ("fj_obsolete", "Obsolete", "boolean", "Whether the function is marked obsolete."),
    ("fj_custom_event_evaluation", "Custom event evaluation", "boolean", "Whether TriggerModel installs a custom evaluator."),
    ("fj_custom_event_registration", "Custom event registration", "boolean", "Whether TriggerModel installs registration-time cache logic."),
    ("fj_function_parameters", "Function parameters", "json", "Ordered parameter types and registration attributes."),
    ("fj_parameter_count", "Parameter count", "integer", "Number of declarative parameters."),
    ("fj_usage_total", "Total use count", "integer", "Recursive trigger-node use count."),
    ("fj_usage_event", "Event use count", "integer", "Uses in event expressions."),
    ("fj_usage_condition", "Condition use count", "integer", "Uses in condition expressions."),
    ("fj_usage_action", "Action use count", "integer", "Uses in action expressions."),
    ("fj_usage_root", "Root use counts", "json", "Root event, condition, and action counts."),
    ("fj_usage_nested", "Nested use count", "integer", "Nested, non-root use count."),
))

TRIGGER_FIELDS = _fields((
    ("fj_trigger_id", "Trigger ID", "text", "Declarative trigger identifier."),
    ("fj_trigger_catalog", "Trigger catalog", "text", "Source trigger category."),
    ("fj_trigger_enabled", "Enabled by default", "boolean", "Default enabled state."),
    ("fj_trigger_auto_disable", "Auto disable", "boolean", "Whether execution disables the trigger."),
    ("fj_trigger_ignored", "Ignored trigger", "boolean", "Whether the trigger bypasses event registration."),
    ("fj_event_counts", "Event counts", "json", "Root and recursive event-node counts."),
    ("fj_condition_counts", "Condition counts", "json", "Root and recursive condition-node counts."),
    ("fj_action_counts", "Action counts", "json", "Root and recursive action-node counts."),
    ("fj_recursive_node_count", "Recursive node count", "integer", "All recursive function nodes in this trigger."),
    ("fj_max_function_depth", "Maximum function depth", "integer", "Maximum nested function depth."),
))

ASSET_FIELDS = _fields((
    ("fj_asset_name", "Logical asset name", "text", "Case-preserved catalog key."),
    ("fj_asset_source_path", "Logical source path", "text", "Catalog value preserved verbatim."),
    ("fj_asset_extension", "Asset extension", "text", "Lower-cased logical extension."),
    ("fj_bundle_filename", "Bundle filename", "text", "Expected case-folded Unity bundle filename."),
))

CLAIM_FIELDS = _fields((
    ("fj_claim_id", "Claim ID", "text", "Evidence-ledger claim identifier."),
    ("fj_claim_status", "Claim status", "text", "Observed, inferred, constructed, or unknown status."),
    ("fj_claim_artifact", "Claim artifact", "text", "Artifact and fingerprint cell from the evidence ledger."),
    ("fj_claim_method", "Claim method", "text", "Method or output supporting the claim."),
    ("fj_claim_text", "Claim text", "text", "Bounded claim recorded in the evidence ledger."),
    ("fj_claim_inference_falsifier", "Inference and falsifier", "text", "Confidence boundary and falsifying observation."),
    ("fj_writeback", "Write-back authority", "text", "Recorded write-back authorization state."),
))

IL_FIELDS = _fields((
    ("fj_anchor_label", "IL anchor label", "text", "Method-level provenance label."),
    ("fj_method_token", "Method token", "text", "MethodDef token in the fingerprinted assembly."),
    ("fj_method_rid", "Method RID", "integer", "MethodDef row identifier."),
    ("fj_method_rva", "Method RVA", "text", "Method RVA in the fingerprinted assembly."),
    ("fj_method_file_offset", "Method file offset", "text", "Method file offset in the fingerprinted assembly."),
    ("fj_method_code_size", "Method code size", "integer", "IL body size in bytes when recorded."),
    ("fj_il_output_sha256", "IL output SHA-256", "text", "SHA-256 of the dnSpy IL output."),
    ("fj_il_witnesses", "IL witnesses", "json", "Named opcode or call witnesses and boolean results."),
))

DELTA_FIELDS = _fields((
    ("fj_from_build_id", "From Build ID", "integer", "Historical side of a Build comparison."),
    ("fj_to_build_id", "To Build ID", "integer", "Current side of a Build comparison."),
    ("fj_raw_depot_delta", "Raw depot delta", "json", "Added, removed, and changed file counts."),
    ("fj_configuration_delta", "Configuration delta", "json", "Selected semantic inventory count changes."),
    ("fj_added_ids", "Added IDs", "json", "Added function and trigger identifiers."),
    ("fj_removed_ids", "Removed IDs", "json", "Removed function and trigger identifiers."),
))

CATALOG_FIELDS = _fields((
    ("fj_catalog_schema_version", "Catalog schema version", "text", "FromJianghu consumer schema version."),
    ("fj_catalog_fingerprint", "Catalog fingerprint", "text", "SHA-256 over canonical ordered source records."),
    ("fj_entity_counts", "Entity counts", "json", "Expected entity count by classification kind."),
))

FIELD_SPECS = (
    COMMON_FIELDS + BUILD_FIELDS + MODEL_FIELDS + FUNCTION_FIELDS +
    TRIGGER_FIELDS + ASSET_FIELDS + CLAIM_FIELDS + IL_FIELDS +
    DELTA_FIELDS + CATALOG_FIELDS
)
SOURCE_OWNED_KEYS = frozenset(spec.key for spec in FIELD_SPECS)

VIEW_SPECS = (
    ViewSpec("FromJianghu Asset Catalog", ("fj_asset_name", "fj_asset_extension", "fj_bundle_filename", "fj_source_build_id", "fj_source_sha256", "fj_record_status"), "Logical Unity asset and bundle classification."),
    ViewSpec("FromJianghu Build Evolution", ("fj_from_build_id", "fj_to_build_id", "fj_raw_depot_delta", "fj_configuration_delta", "fj_added_ids", "fj_removed_ids", "fj_claim_boundary"), "Version-scoped static changes."),
    ViewSpec("FromJianghu Build Provenance", ("fj_game_version", "fj_steam_app_id", "fj_depot_id", "fj_depot_manifest", "fj_depot_file_count", "fj_depot_bytes", "fj_baseline_path", "fj_appmanifest_sha256", "fj_runtime_status"), "Build identity and preservation boundary."),
    ViewSpec("FromJianghu Evidence Claims", ("fj_claim_id", "fj_claim_status", "fj_claim_text", "fj_claim_artifact", "fj_claim_method", "fj_claim_inference_falsifier", "fj_writeback"), "Observed, inferred, constructed, and unknown claims."),
    ViewSpec("FromJianghu Function Catalog", ("fj_function_id", "fj_function_name", "fj_function_catalog", "fj_return_type", "fj_function_enum_id", "fj_function_parameters", "fj_usage_total", "fj_usage_root", "fj_usage_nested", "fj_obsolete"), "Declarative function vocabulary and use."),
    ViewSpec("FromJianghu IL Provenance", ("fj_anchor_label", "fj_source_build_id", "fj_method_token", "fj_method_rva", "fj_method_file_offset", "fj_method_code_size", "fj_il_witnesses", "fj_source_sha256"), "MethodDef-bound dnSpy IL evidence."),
    ViewSpec("FromJianghu State Owners", ("fj_model_class", "fj_model_name", "fj_game_data_type", "fj_user_data_type", "fj_initialization_order", "fj_has_save_game", "fj_random_call_count", "fj_dictionary_field_count", "fj_hashset_field_count"), "Static model lifecycle and determinism risks."),
    ViewSpec("FromJianghu Trigger Catalog", ("fj_trigger_id", "fj_trigger_catalog", "fj_trigger_enabled", "fj_trigger_auto_disable", "fj_trigger_ignored", "fj_event_counts", "fj_condition_counts", "fj_action_counts", "fj_recursive_node_count", "fj_max_function_depth"), "Declarative trigger structure without runtime-reachability claims."),
)


@dataclass(frozen=True)
class ProjectConfig:
    source_root: Path = SOURCE_ROOT
    database_path: Path = Path(__file__).resolve().parent / DATABASE_NAME
    source_hashes: Mapping[str, str] = field(default_factory=lambda: dict(SOURCE_HASHES))
    expected_entity_counts: Mapping[str, int] = field(default_factory=lambda: dict(ENTITY_COUNTS))
    namespace: str = NAMESPACE


def default_config() -> ProjectConfig:
    return ProjectConfig()
