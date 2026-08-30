from __future__ import annotations

from dataclasses import dataclass

from config import NAMESPACE


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    value_type: str
    description: str
    ownership: str
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
class ViewSpec:
    name: str
    field_keys: tuple[str, ...]
    description: str


def _specs(
    ownership: str,
    definitions: tuple[tuple[str, str, str, str], ...],
) -> tuple[FieldSpec, ...]:
    return tuple(
        FieldSpec(
            key=key,
            label=label,
            value_type=value_type,
            description=description,
            ownership=ownership,
        )
        for key, label, value_type, description in definitions
    )


SOURCE_FIELD_DEFINITIONS = (
    ("source_build_id", "Source Build ID", "integer", "Steam BuildID that owns the observed snapshot fact."),
    ("source_schema", "Source schema", "text", "Exact schema identifier declared by the source artifact."),
    ("source_path", "Source path", "text", "Canonical path relative to the read-only research root."),
    ("source_sha256", "Source SHA-256", "text", "SHA-256 evidence binding the imported source fact."),
    ("source_row", "Source row", "integer", "Source row or deterministic manifest ordinal when available."),
    ("source_evidence_level", "Source evidence level", "text", "Evidence class supporting the imported or derived fact."),
    ("record_status", "Record status", "text", "Current snapshot, gap, candidate, or preservation state."),
    ("steam_app_id", "Steam App ID", "integer", "Steam application identifier recorded by source evidence."),
    ("depot_manifest", "Depot manifest", "text", "Steam depot manifest identifier recorded for the Build."),
    ("snapshot_status", "Snapshot status", "text", "Bounded status of the imported research snapshot."),
    ("normalized_name_key", "Normalized name key", "text", "NFKC and whitespace-only provisional identity key."),
    ("identity_status", "Identity status", "text", "Source-side provisional identity grouping status."),
    ("identity_group_evidence", "Identity group evidence", "text", "Deterministic evidence used to group form snapshots."),
    ("linked_form_ids", "Linked form IDs", "json", "Build-scoped form entity IDs provisionally linked to an identity."),
    ("identity_entity_id", "Identity entity ID", "text", "Stable character identity linked from a form snapshot."),
    ("hero_id", "Hero ID", "integer", "Exact Hero identifier observed in the source registry."),
    ("id_name", "ID name", "text", "Source IdName value for a Hero form."),
    ("name_zh", "Name (zh)", "text", "Source-observed Chinese character name."),
    ("name_tw", "Name (zh-Hant)", "text", "Source-observed Traditional Chinese character name."),
    ("title", "Title", "text", "Source-observed character title."),
    ("title_tw", "Title (zh-Hant)", "text", "Source-observed Traditional Chinese title."),
    ("birth_id", "Birth ID", "integer", "Source-observed birth or origin identifier."),
    ("faction_text", "Faction source text", "text", "Faction or Menpai value preserved without premature normalization."),
    ("base_description", "Base description", "text", "Source-observed base character description when available."),
    ("description", "Description", "text", "Source-observed character description when available."),
    ("card_name", "Card name", "text", "Source-observed card name when available."),
    ("rarity", "Rarity", "text", "Source-observed rarity preserved without reinterpretation."),
    ("image_path", "Expected Image path", "text", "Expected ResourceManager Image path from the Hero source."),
    ("card_path", "Expected Card path", "text", "Expected ResourceManager Card path from the Hero source."),
    ("parent_id", "Parent ID", "integer", "Source-observed ParentId for the Hero form."),
    ("extra_hero_id", "Extra Hero ID", "integer", "Source-observed linked extra Hero identifier."),
    ("skin_group_id", "Skin group ID", "integer", "Source-observed skin group identifier."),
    ("story_id", "Story ID", "integer", "Source-observed story identifier."),
    ("route_filter", "Route filter", "json", "Source-observed route constraints when available."),
    ("property_values", "Property values", "json", "Structured source properties not yet promoted to stable fields."),
    ("skill_ids", "Skill IDs", "json", "Source-observed skill identifiers when available."),
    ("role_class", "Role class", "text", "Role asset class such as Image, Card, Assist, or Head."),
    ("resource_path", "Resource path", "text", "Exact normalized ResourceManager container path."),
    ("resource_numeric_id", "Resource numeric ID", "integer", "Numeric suffix parsed from a resource or candidate path."),
    ("unity_source_file", "Unity source file", "text", "Serialized Unity file containing the selected object."),
    ("unity_path_id", "Unity path ID", "integer", "Unity object pathID used as an exact locator."),
    ("mapping_status", "Mapping status", "text", "Exact, ambiguous, or unmapped inventory status."),
    ("extraction_status", "Extraction status", "text", "Canonical extraction, candidate decode, or not-extracted state."),
    ("hero_id_known", "Hero ID known", "boolean", "Whether the numeric asset identifier belongs to the Hero registry."),
    ("png_path", "PNG path", "text", "Manifest path of a canonical or ambiguous decoded PNG."),
    ("png_sha256", "PNG SHA-256", "text", "PNG SHA-256 projected from the validated output manifest."),
    ("png_length", "PNG length", "integer", "PNG byte length projected from the validated output manifest."),
    ("image_width", "Image width", "integer", "Observed image width in pixels."),
    ("image_height", "Image height", "integer", "Observed image height in pixels."),
    ("image_mode", "Image mode", "text", "Decoded image mode projected from the output manifest."),
    ("alpha_extrema", "Alpha extrema", "json", "Observed minimum and maximum Alpha values."),
    ("candidate_reason", "Candidate reason", "text", "Evidence explaining why a decoded output remains noncanonical."),
    ("related_expected_path", "Related expected path", "text", "Expected canonical path related to an ambiguous candidate."),
    ("gap_kind", "Gap kind", "text", "Machine-readable class of missing source evidence."),
    ("gap_expected_path", "Gap expected path", "text", "Canonical path whose exact mapping is unresolved."),
    ("gap_reason", "Gap reason", "text", "Reason the expected source asset remains unresolved."),
    ("gap_candidates", "Gap candidates", "json", "Preserved candidate locators associated with a source gap."),
    ("methodology_title", "Methodology title", "text", "Title of a preserved user-authored methodology reference."),
    ("methodology_version", "Methodology version", "text", "Version label of the preserved methodology reference."),
    ("methodology_path", "Methodology path", "text", "Canonical local path to the preserved methodology paper."),
    ("methodology_sha256", "Methodology SHA-256", "text", "Validated SHA-256 of the preserved methodology paper."),
    ("methodology_validation_path", "Methodology validation path", "text", "Path to the paper's validation manifest."),
    ("methodology_intended_use", "Methodology intended use", "text", "Bounded use of the paper as non-executable design input."),
)


GENERAL_CURATED_DEFINITIONS = (
    ("curated_identity_resolution", "Curated identity resolution", "text", "Human decision confirming, splitting, or disputing a provisional identity."),
    ("curated_identity_evidence", "Curated identity evidence", "text", "Human-readable evidence supporting the identity resolution."),
    ("curated_background_summary", "Curated background summary", "text", "Concise reviewed character background summary."),
    ("curated_role_interpretation", "Curated role interpretation", "text", "Reviewed interpretation of the character's narrative role."),
    ("curated_personality_interpretation", "Curated personality interpretation", "text", "Reviewed interpretation of personality and behavioral cues."),
    ("curated_history_interpretation", "Curated history interpretation", "text", "Reviewed interpretation of historical or route context."),
    ("curator_notes", "Curator notes", "text", "Freeform human curator notes outside importer ownership."),
    ("art_redesign_priority", "Art redesign priority", "integer", "Human-assigned redesign priority for planning work."),
    ("art_review_status", "Art review status", "text", "Human review state for art-direction work."),
)


IDENTITY_WORLD_DEFINITIONS = (
    ("art_identity_face_shape", "Face shape", "text", "Curated face-shape identity anchor."),
    ("art_identity_bone_structure", "Bone structure", "text", "Curated bone-structure identity anchor."),
    ("art_identity_age_class", "Age class", "text", "Explicitly curated age class; unknown remains safety-locked."),
    ("art_identity_body_type", "Body type", "text", "Curated body-type identity anchor."),
    ("art_world_faction_vocabulary", "Faction visual vocabulary", "text", "Curated faction-specific visual language."),
    ("art_world_regional_vocabulary", "Regional visual vocabulary", "text", "Curated region-specific visual language."),
    ("art_motif_primary", "Primary motif", "text", "Primary personal visual motif."),
    ("art_motif_secondary", "Secondary motif", "text", "Secondary personal visual motif."),
    ("art_symbol", "Personal symbol", "text", "Distinctive personal symbol or emblem."),
    ("art_weapon_role", "Weapon role", "text", "Weapon identity and its compositional role."),
    ("art_silhouette", "Silhouette", "text", "Curated silhouette identity and readability constraint."),
    ("art_palette_distribution", "Palette distribution", "json", "Curated color distribution rather than a single dominant color."),
    ("art_gesture_habit", "Gesture habit", "text", "Recurring pose or gesture that expresses character identity."),
    ("art_not_near_character_ids", "Do-not-converge character IDs", "json", "Character identities this design must remain visibly distant from."),
)


RENDERING_GROUP_DEFINITIONS = (
    ("art_line_tension", "Line tension", "number", "Curated line-tension control for the character rendering language."),
    ("art_detail_density_face", "Face detail density", "number", "Curated relative detail density for the face region."),
    ("art_detail_density_costume", "Costume detail density", "number", "Curated relative detail density for costume regions."),
    ("art_detail_density_background", "Background detail density", "number", "Curated relative detail density for the background."),
    ("art_grain_character", "Character grain", "number", "Curated material or brush grain for the character."),
    ("art_grain_background", "Background grain", "number", "Curated material or brush grain for the background."),
    ("art_default_basin_risk", "Default-basin risk", "number", "Reviewed risk of collapsing into a generic AI illustration basin."),
    ("art_group_distance_status", "Group distance status", "text", "Reviewed distinctiveness status within the current character group."),
    ("art_collision_group_id", "Visual collision group ID", "text", "Curated identifier for a visual-similarity audit group."),
)


EXPOSURE_TENSION_DEFINITIONS = (
    ("sfw_exposure_neck", "Neck exposure", "number", "Curated SFW neck exposure control for an adult-confirmed character."),
    ("sfw_exposure_shoulder", "Shoulder exposure", "number", "Curated SFW shoulder exposure control for an adult-confirmed character."),
    ("sfw_exposure_back", "Back exposure", "number", "Curated SFW back exposure control for an adult-confirmed character."),
    ("sfw_exposure_waist", "Waist exposure", "number", "Curated SFW waist exposure control for an adult-confirmed character."),
    ("sfw_exposure_leg", "Leg exposure", "number", "Curated SFW leg exposure control for an adult-confirmed character."),
    ("sfw_garment_fit", "Garment fit", "number", "Curated garment-fit control independent from exposure."),
    ("sfw_garment_sheer", "Garment sheer", "number", "Curated SFW fabric-sheer control independent from exposure."),
    ("sfw_tension_gaze", "Gaze tension", "number", "Curated gaze contribution to non-explicit dramatic tension."),
    ("sfw_tension_gesture", "Gesture tension", "number", "Curated gesture contribution to non-explicit dramatic tension."),
    ("sfw_tension_pose", "Pose tension", "number", "Curated pose contribution to non-explicit dramatic tension."),
    ("sfw_tension_proximity", "Proximity tension", "number", "Curated proximity contribution to non-explicit dramatic tension."),
    ("sfw_tension_expression", "Expression tension", "number", "Curated expression contribution to non-explicit dramatic tension."),
    ("sfw_tension_camera", "Camera tension", "number", "Curated camera contribution to non-explicit dramatic tension."),
    ("sfw_tension_power", "Power tension", "number", "Curated power-dynamic contribution to non-explicit dramatic tension."),
    ("sfw_audience_bias", "Audience bias", "number", "Curated audience-orientation bias for SFW presentation."),
    ("sfw_safety_boundary", "SFW safety boundary", "text", "Explicit safety gate; unknown or minor age classes stay locked."),
    ("sfw_locked_regions", "Locked regions", "json", "Body or garment regions excluded from automated art-direction changes."),
    ("sfw_garment_topology_notes", "Garment topology notes", "text", "Curated construction notes that preserve clothing topology."),
)


PROPOSAL_FIELD_DEFINITIONS = (
    ("proposal_identity_summary", "Proposed identity summary", "text", "Advisory identity summary that cannot mutate curated canon."),
    ("proposal_visual_collision", "Proposed visual collision", "text", "Advisory visual-collision finding pending human review."),
    ("proposal_art_direction", "Proposed art direction", "text", "Advisory art-direction draft pending human review."),
    ("proposal_similarity_score", "Proposed similarity score", "number", "Analytical similarity score retained as noncanonical evidence."),
    ("proposal_evidence_basis", "Proposal evidence basis", "text", "Model, method, version, and evidence basis for a proposal."),
)


SOURCE_FIELD_SPECS = _specs("source", SOURCE_FIELD_DEFINITIONS)
CURATED_FIELD_SPECS = _specs(
    "curated",
    GENERAL_CURATED_DEFINITIONS
    + IDENTITY_WORLD_DEFINITIONS
    + RENDERING_GROUP_DEFINITIONS
    + EXPOSURE_TENSION_DEFINITIONS,
)
PROPOSAL_FIELD_SPECS = _specs("proposal", PROPOSAL_FIELD_DEFINITIONS)

FIELD_SPECS = SOURCE_FIELD_SPECS + CURATED_FIELD_SPECS + PROPOSAL_FIELD_SPECS
SOURCE_OWNED_KEYS = frozenset(spec.key for spec in SOURCE_FIELD_SPECS)
CURATED_KEYS = frozenset(spec.key for spec in CURATED_FIELD_SPECS)
PROPOSAL_KEYS = frozenset(spec.key for spec in PROPOSAL_FIELD_SPECS)

IDENTITY_WORLD_KEYS = frozenset(key for key, *_ in IDENTITY_WORLD_DEFINITIONS)
RENDERING_GROUP_KEYS = frozenset(key for key, *_ in RENDERING_GROUP_DEFINITIONS)
EXPOSURE_TENSION_FIELD_ORDER = tuple(
    key for key, *_ in EXPOSURE_TENSION_DEFINITIONS
)
EXPOSURE_TENSION_KEYS = frozenset(EXPOSURE_TENSION_FIELD_ORDER)


VIEW_SPECS = (
    ViewSpec(
        "Build Snapshots",
        (
            "source_build_id",
            "steam_app_id",
            "depot_manifest",
            "snapshot_status",
            "source_schema",
            "source_sha256",
            "record_status",
        ),
        "Build identity, provenance, source manifest and bounded extraction status.",
    ),
    ViewSpec(
        "Character Canon",
        (
            "name_zh",
            "name_tw",
            "normalized_name_key",
            "identity_status",
            "linked_form_ids",
            "curated_identity_resolution",
            "curated_background_summary",
            "curated_role_interpretation",
            "curated_personality_interpretation",
            "curated_history_interpretation",
            "curator_notes",
        ),
        "Stable or provisional character identities with sparse human-reviewed canon.",
    ),
    ViewSpec(
        "Character Forms",
        (
            "source_build_id",
            "hero_id",
            "identity_entity_id",
            "id_name",
            "name_zh",
            "name_tw",
            "title",
            "title_tw",
            "birth_id",
            "faction_text",
            "image_path",
            "card_path",
            "parent_id",
            "extra_hero_id",
            "skin_group_id",
            "story_id",
            "property_values",
            "source_row",
        ),
        "Build-scoped Hero forms and exact reduced-registry source facts.",
    ),
    ViewSpec(
        "Visual Asset Map",
        (
            "source_build_id",
            "role_class",
            "resource_path",
            "resource_numeric_id",
            "unity_source_file",
            "unity_path_id",
            "mapping_status",
            "extraction_status",
            "hero_id_known",
            "png_path",
            "png_sha256",
            "png_length",
            "image_width",
            "image_height",
            "image_mode",
            "alpha_extrema",
        ),
        "Exact ResourceManager role paths and validated extraction projections.",
    ),
    ViewSpec(
        "Art Redesign Board",
        (
            "name_zh",
            "art_identity_age_class",
            "art_identity_face_shape",
            "art_identity_bone_structure",
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
            "art_redesign_priority",
            "art_review_status",
        ),
        "Sparse identity, motif, gesture and rendering controls for redesign work.",
    ),
    ViewSpec(
        "Visual Collision Audit",
        (
            "name_zh",
            "art_collision_group_id",
            "art_group_distance_status",
            "art_default_basin_risk",
            "art_not_near_character_ids",
            "proposal_visual_collision",
            "proposal_similarity_score",
            "proposal_evidence_basis",
            "art_review_status",
        ),
        "Human-reviewed collision groups with explicitly advisory analytical proposals.",
    ),
    ViewSpec(
        "Source Gaps",
        (
            "source_build_id",
            "hero_id",
            "role_class",
            "gap_kind",
            "gap_expected_path",
            "gap_reason",
            "gap_candidates",
            "mapping_status",
            "extraction_status",
            "png_path",
            "png_sha256",
        ),
        "Known missing exact paths and decoded candidates that remain noncanonical.",
    ),
    ViewSpec(
        "Exposure–Tension Control",
        (
            "name_zh",
            "art_identity_age_class",
            "sfw_safety_boundary",
        )
        + tuple(
            key
            for key in EXPOSURE_TENSION_FIELD_ORDER
            if key != "sfw_safety_boundary"
        ),
        "Adult-confirmed, explicitly curated SFW controls; unknown age remains locked.",
    ),
    ViewSpec(
        "Methodology Provenance",
        (
            "methodology_title",
            "methodology_version",
            "methodology_path",
            "methodology_sha256",
            "methodology_validation_path",
            "methodology_intended_use",
            "record_status",
            "source_sha256",
        ),
        "Preserved methodology versions, hashes, validation and bounded intended use.",
    ),
)
