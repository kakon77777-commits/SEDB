from __future__ import annotations

import pytest

from fixtures import (
    ART_CHECKPOINT,
    METHODOLOGY_CHECKPOINT,
    build_snapshot_fixture,
)
from source import SourceValidationError, load_snapshot


ROLE_TARGETS = "art-engineering/inventory/build-25006280/role-targets.json"
UNITY_INDEX = "art-engineering/inventory/build-25006280/unity-object-index.json"
OUTPUT_MANIFEST = "art-engineering/evidence/extraction-output-manifest.json"
EXPOSURE_VALIDATION = (
    "inputs/methodology-papers/2026-08-30/"
    "exposure-tension-decoupling-v0.1/documents/VALIDATION_MANIFEST.json"
)


def test_load_snapshot_builds_sorted_schema_faithful_entities(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)

    selection = load_snapshot(fixture.config)

    assert selection.build_id == 25006280
    assert selection.counts == {
        "wanxiang_build_snapshot": 1,
        "wanxiang_character_identity": 1,
        "wanxiang_character_form_snapshot": 2,
        "wanxiang_visual_asset_snapshot": 3,
        "wanxiang_visual_candidate_snapshot": 1,
        "wanxiang_source_gap_snapshot": 1,
        "wanxiang_methodology_reference": 2,
    }
    assert [entity.entity_id for entity in selection.entities] == sorted(
        entity.entity_id for entity in selection.entities
    )
    assert len(selection.entities) == 11


def test_all_exact_paths_are_assets_and_ambiguity_stays_candidate(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)

    selection = load_snapshot(fixture.config)

    assets = [
        entity
        for entity in selection.entities
        if entity.kind == "wanxiang_visual_asset_snapshot"
    ]
    candidates = [
        entity
        for entity in selection.entities
        if entity.kind == "wanxiang_visual_candidate_snapshot"
    ]
    assert {entity.values["resource_path"] for entity in assets} == {
        "roles/image/1001",
        "roles/card/1001",
        "roles/assist/9999",
    }
    assert candidates[0].values["png_path"].startswith("ambiguous/")
    assert candidates[0].values["related_expected_path"] == "Roles/Image/1002"
    assert all(
        entity.values["resource_path"].lower() != "roles/image/1002"
        for entity in assets
    )


def test_unsupported_schema_is_reason_coded(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)
    fixture.mutate_json(
        ROLE_TARGETS,
        lambda value: value.update(schema="wanxiang-role-targets/v999"),
        refresh_checkpoint=ART_CHECKPOINT,
    )

    with pytest.raises(SourceValidationError) as error:
        load_snapshot(fixture.config)

    assert error.value.reason_code == "unsupported_schema"


def test_source_hash_change_is_reason_coded(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)
    path = fixture.path(ROLE_TARGETS)
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(SourceValidationError) as error:
        load_snapshot(fixture.config)

    assert error.value.reason_code == "source_hash_mismatch"


def test_role_target_count_mismatch_is_reason_coded(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)

    def remove_hero(value):
        value["heroes"].pop()
        value["stats"]["heroRows"] = 1

    fixture.mutate_json(
        ROLE_TARGETS,
        remove_hero,
        refresh_checkpoint=ART_CHECKPOINT,
    )

    with pytest.raises(SourceValidationError) as error:
        load_snapshot(fixture.config)

    assert error.value.reason_code == "role_target_count_mismatch"


def test_duplicate_entity_id_is_reason_coded(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)

    def duplicate_resource_path(value):
        value["imageObjects"][1]["containerPaths"] = ["ROLES/IMAGE/1001"]

    fixture.mutate_json(
        UNITY_INDEX,
        duplicate_resource_path,
        refresh_checkpoint=ART_CHECKPOINT,
    )

    with pytest.raises(SourceValidationError) as error:
        load_snapshot(fixture.config)

    assert error.value.reason_code == "duplicate_entity_id"


@pytest.mark.parametrize(
    ("key", "reason_code"),
    [
        ("fileCount", "output_manifest_count_mismatch"),
        ("totalBytes", "output_manifest_byte_mismatch"),
    ],
)
def test_output_manifest_mismatches_are_reason_coded(tmp_path, key, reason_code):
    fixture = build_snapshot_fixture(tmp_path)
    fixture.mutate_json(
        OUTPUT_MANIFEST,
        lambda value: value.update({key: value[key] + 1}),
        refresh_checkpoint=ART_CHECKPOINT,
    )

    with pytest.raises(SourceValidationError) as error:
        load_snapshot(fixture.config)

    assert error.value.reason_code == reason_code


def test_paper_validation_hash_mismatch_is_reason_coded(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)
    fixture.mutate_json(
        EXPOSURE_VALIDATION,
        lambda value: value.update(sha256="0" * 64),
        refresh_checkpoint=METHODOLOGY_CHECKPOINT,
    )

    with pytest.raises(SourceValidationError) as error:
        load_snapshot(fixture.config)

    assert error.value.reason_code == "paper_validation_hash_mismatch"


def test_ambiguous_png_cannot_be_promoted_to_exact_manifest_path(tmp_path):
    fixture = build_snapshot_fixture(tmp_path)

    def promote_candidate(value):
        value["files"][2]["path"] = "Roles/Image/1002.png"

    fixture.mutate_json(
        OUTPUT_MANIFEST,
        promote_candidate,
        refresh_checkpoint=ART_CHECKPOINT,
    )

    with pytest.raises(SourceValidationError) as error:
        load_snapshot(fixture.config)

    assert error.value.reason_code == "ambiguous_promoted_to_exact"
