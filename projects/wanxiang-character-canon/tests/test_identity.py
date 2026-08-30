from identity import (
    asset_entity_id,
    build_entity_id,
    candidate_entity_id,
    character_identity_id,
    form_entity_id,
    gap_entity_id,
    methodology_entity_id,
    normalize_name_key,
)


def test_name_normalization_is_nfkc_and_whitespace_only():
    assert normalize_name_key("  萬\u3000輕舟  ") == "萬 輕舟"
    assert normalize_name_key("万轻舟") == "万轻舟"
    assert normalize_name_key("萬輕舟") != normalize_name_key("万轻舟")


def test_build_form_and_identity_ids_are_stable_and_namespaced():
    assert build_entity_id(25006280) == "wx-build-25006280"
    assert form_entity_id(25006280, 1001) == "wx-build-25006280-hero-1001"
    assert character_identity_id("万轻舟").startswith("wx-char-")
    assert character_identity_id("万轻舟") == character_identity_id(" 万轻舟 ")


def test_path_based_ids_normalize_case_separators_and_outer_slashes():
    assert asset_entity_id(25006280, "Roles\\Image\\1001") == asset_entity_id(
        25006280, "/roles/image/1001/"
    )
    assert candidate_entity_id(
        25006280, "Role-Extraction\\Ambiguous\\0001.png"
    ) == candidate_entity_id(
        25006280, "/role-extraction/ambiguous/0001.PNG/"
    )


def test_gap_and_methodology_ids_are_deterministic():
    assert gap_entity_id(25006280, " Image ", 7) == gap_entity_id(
        25006280, "image", 7
    )
    assert methodology_entity_id("Heluo Character Art", "v0.1") == (
        methodology_entity_id(" heluo   character art ", "V0.1")
    )
