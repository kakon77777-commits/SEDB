from __future__ import annotations

from catalog_schema import (
    CATALOG_SOURCE_FIELD_SPECS,
    CATALOG_SOURCE_OWNED_KEYS,
    CATALOG_VIEW_SPECS,
)
from schema import (
    CURATED_KEYS,
    FIELD_SPECS,
    PROPOSAL_KEYS,
    SOURCE_OWNED_KEYS,
    VIEW_SPECS,
    WAVE1_SOURCE_OWNED_KEYS,
)


WAVE1_VIEW_FIELDS = {
    "Build Snapshots": (
        "source_build_id", "steam_app_id", "depot_manifest", "snapshot_status",
        "source_schema", "source_sha256", "record_status",
    ),
    "Character Canon": (
        "name_zh", "name_tw", "normalized_name_key", "identity_status",
        "linked_form_ids", "curated_identity_resolution",
        "curated_background_summary", "curated_role_interpretation",
        "curated_personality_interpretation", "curated_history_interpretation",
        "curator_notes",
    ),
    "Character Forms": (
        "source_build_id", "hero_id", "identity_entity_id", "id_name",
        "name_zh", "name_tw", "title", "title_tw", "birth_id",
        "faction_text", "image_path", "card_path", "parent_id",
        "extra_hero_id", "skin_group_id", "story_id", "property_values",
        "source_row",
    ),
    "Visual Asset Map": (
        "source_build_id", "role_class", "resource_path", "resource_numeric_id",
        "unity_source_file", "unity_path_id", "mapping_status",
        "extraction_status", "hero_id_known", "png_path", "png_sha256",
        "png_length", "image_width", "image_height", "image_mode",
        "alpha_extrema",
    ),
    "Art Redesign Board": (
        "name_zh", "art_identity_age_class", "art_identity_face_shape",
        "art_identity_bone_structure", "art_identity_body_type",
        "art_world_faction_vocabulary", "art_world_regional_vocabulary",
        "art_motif_primary", "art_motif_secondary", "art_symbol",
        "art_weapon_role", "art_silhouette", "art_palette_distribution",
        "art_gesture_habit", "art_not_near_character_ids", "art_line_tension",
        "art_detail_density_face", "art_detail_density_costume",
        "art_detail_density_background", "art_grain_character",
        "art_grain_background", "art_redesign_priority", "art_review_status",
    ),
    "Visual Collision Audit": (
        "name_zh", "art_collision_group_id", "art_group_distance_status",
        "art_default_basin_risk", "art_not_near_character_ids",
        "proposal_visual_collision", "proposal_similarity_score",
        "proposal_evidence_basis", "art_review_status",
    ),
    "Source Gaps": (
        "source_build_id", "hero_id", "role_class", "gap_kind",
        "gap_expected_path", "gap_reason", "gap_candidates", "mapping_status",
        "extraction_status", "png_path", "png_sha256",
    ),
    "Exposure–Tension Control": (
        "name_zh", "art_identity_age_class", "sfw_safety_boundary",
        "sfw_exposure_neck", "sfw_exposure_shoulder", "sfw_exposure_back",
        "sfw_exposure_waist", "sfw_exposure_leg", "sfw_garment_fit",
        "sfw_garment_sheer", "sfw_tension_gaze", "sfw_tension_gesture",
        "sfw_tension_pose", "sfw_tension_proximity", "sfw_tension_expression",
        "sfw_tension_camera", "sfw_tension_power", "sfw_audience_bias",
        "sfw_locked_regions", "sfw_garment_topology_notes",
    ),
    "Methodology Provenance": (
        "methodology_title", "methodology_version", "methodology_path",
        "methodology_sha256", "methodology_validation_path",
        "methodology_intended_use", "record_status", "source_sha256",
    ),
}


CATALOG_VIEW_NAMES = [
    "AllExcel Table Catalog",
    "Full Hero Context",
    "World and Map Context",
    "Relationship Routes",
    "Event Network",
    "Dialogue Index",
    "Combat and Progression",
    "Reference Resolution",
    "Static Gameplay Questions",
    "Catalog Provenance",
]


def test_catalog_source_keys_are_owned_and_layered():
    required = {
        "catalog_source_fingerprint",
        "runtime_candidate_files",
        "source_layer",
        "source_authority",
        "source_table",
        "source_record_id",
        "source_workbook_path",
        "source_workbook_sha256",
        "source_row_sha256",
        "source_row_payload",
        "edge_source_entity_id",
        "edge_target_table",
        "edge_resolution_status",
    }

    assert required <= CATALOG_SOURCE_OWNED_KEYS
    assert CATALOG_SOURCE_OWNED_KEYS.isdisjoint(CURATED_KEYS | PROPOSAL_KEYS)
    assert WAVE1_SOURCE_OWNED_KEYS < SOURCE_OWNED_KEYS
    assert SOURCE_OWNED_KEYS == WAVE1_SOURCE_OWNED_KEYS | CATALOG_SOURCE_OWNED_KEYS
    assert len(FIELD_SPECS) == len({field.key for field in FIELD_SPECS})
    assert all(field.namespace == "wanxiang_character_canon" for field in CATALOG_SOURCE_FIELD_SPECS)
    assert all(field.status == "active" for field in CATALOG_SOURCE_FIELD_SPECS)
    assert all(field.description.strip() for field in CATALOG_SOURCE_FIELD_SPECS)


def test_wave1_views_are_unchanged_and_catalog_views_are_appended():
    actual_wave1 = {
        view.name: view.field_keys
        for view in VIEW_SPECS[:9]
    }

    assert actual_wave1 == WAVE1_VIEW_FIELDS
    assert [view.name for view in VIEW_SPECS[9:]] == CATALOG_VIEW_NAMES
    assert tuple(VIEW_SPECS[9:]) == CATALOG_VIEW_SPECS


def test_catalog_views_reference_known_fields_and_keep_payload_compact():
    known = {field.key for field in FIELD_SPECS}

    assert all(set(view.field_keys) <= known for view in CATALOG_VIEW_SPECS)
    assert all("source_row_payload" not in view.field_keys for view in CATALOG_VIEW_SPECS)
    dialogue = next(
        view for view in CATALOG_VIEW_SPECS if view.name == "Dialogue Index"
    )
    assert dialogue.field_keys[:8] == (
        "source_record_id",
        "name_zh",
        "title",
        "next_dialog_id",
        "next_event_id",
        "source_row",
        "source_row_sha256",
        "source_workbook_path",
    )
