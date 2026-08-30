from __future__ import annotations

from fixtures import build_snapshot_fixture
from schema import (
    CURATED_KEYS,
    EXPOSURE_TENSION_KEYS,
    FIELD_SPECS,
    PROPOSAL_KEYS,
    SOURCE_OWNED_KEYS,
    VIEW_SPECS,
)
from source import load_snapshot


def test_field_keys_are_unique_layered_and_sedb_ready():
    keys = [field.key for field in FIELD_SPECS]

    assert len(keys) == len(set(keys))
    assert SOURCE_OWNED_KEYS.isdisjoint(CURATED_KEYS)
    assert SOURCE_OWNED_KEYS.isdisjoint(PROPOSAL_KEYS)
    assert CURATED_KEYS.isdisjoint(PROPOSAL_KEYS)
    assert set(keys) == SOURCE_OWNED_KEYS | CURATED_KEYS | PROPOSAL_KEYS
    assert all(field.namespace == "wanxiang_character_canon" for field in FIELD_SPECS)
    assert all(field.status == "active" for field in FIELD_SPECS)
    assert all(field.value_type in {"text", "integer", "number", "boolean", "json"} for field in FIELD_SPECS)
    assert all(field.label.strip() and field.description.strip() for field in FIELD_SPECS)


def test_source_adapter_emits_only_declared_source_owned_fields(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)
    selection = load_snapshot(fixture.config)
    emitted = {
        key
        for entity in selection.entities
        for key in entity.values
    }

    assert emitted <= SOURCE_OWNED_KEYS
    assert emitted.isdisjoint(CURATED_KEYS | PROPOSAL_KEYS)


def test_art_methodology_fields_are_curated_not_source_owned():
    required = {
        "art_identity_face_shape",
        "art_identity_bone_structure",
        "art_identity_age_class",
        "art_identity_body_type",
        "art_world_faction_vocabulary",
        "art_world_regional_vocabulary",
        "art_motif_primary",
        "art_motif_secondary",
        "art_symbol",
        "art_weapon_role",
        "art_silhouette",
        "art_palette_distribution",
        "art_gesture_habit",
        "art_not_near_character_ids",
        "art_line_tension",
        "art_detail_density_face",
        "art_detail_density_costume",
        "art_detail_density_background",
        "art_grain_character",
        "art_grain_background",
        "art_default_basin_risk",
        "art_group_distance_status",
        "art_collision_group_id",
    }

    assert required <= CURATED_KEYS
    assert required.isdisjoint(SOURCE_OWNED_KEYS)
    assert EXPOSURE_TENSION_KEYS <= CURATED_KEYS
    assert EXPOSURE_TENSION_KEYS.isdisjoint(SOURCE_OWNED_KEYS | PROPOSAL_KEYS)


def test_required_views_have_exact_order_and_known_fields():
    names = [view.name for view in VIEW_SPECS]

    assert names[:9] == [
        "Build Snapshots",
        "Character Canon",
        "Character Forms",
        "Visual Asset Map",
        "Art Redesign Board",
        "Visual Collision Audit",
        "Source Gaps",
        "Exposure–Tension Control",
        "Methodology Provenance",
    ]
    known = {field.key for field in FIELD_SPECS}
    assert all(view.description.strip() for view in VIEW_SPECS)
    assert all(view.field_keys and set(view.field_keys) <= known for view in VIEW_SPECS)


def test_exposure_tension_view_begins_with_safety_gate_and_is_complete():
    view = next(view for view in VIEW_SPECS if view.name == "Exposure–Tension Control")

    assert view.field_keys[:3] == (
        "name_zh",
        "art_identity_age_class",
        "sfw_safety_boundary",
    )
    assert EXPOSURE_TENSION_KEYS <= set(view.field_keys)
