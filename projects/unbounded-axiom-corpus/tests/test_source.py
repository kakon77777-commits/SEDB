import pytest

from conftest import paper
from source import SourceValidationError, load_month, validate_month


def test_load_month_normalizes_owned_values(write_registry):
    path = write_registry([paper("lm-000001", created=None)])

    selected = load_month(path, "2026-04")

    assert selected.registry_version == "0.2"
    assert selected.registry_count == 1
    assert selected.papers[0].paper_id == "lm-000001"
    assert selected.papers[0].values["year"] == "2026"
    assert "created_date" not in selected.papers[0].values


def test_valid_but_empty_month_is_an_error(write_registry):
    path = write_registry([paper("lm-000001")])

    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-09")

    assert exc.value.reason_code == "target_month_empty"


@pytest.mark.parametrize("month", ["2026-4", "2026-00", "2026-13", "April", ""])
def test_invalid_month_is_rejected(month):
    with pytest.raises(SourceValidationError) as exc:
        validate_month(month)

    assert exc.value.reason_code == "invalid_month"


def test_registry_count_must_match_items(write_registry):
    path = write_registry([paper("lm-000001")], count=2)

    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-04")

    assert exc.value.reason_code == "registry_count_mismatch"


def test_global_duplicate_id_is_rejected_even_outside_target_month(write_registry):
    path = write_registry(
        [
            paper("lm-000001", month="2026-04"),
            paper("lm-000001", month="2026-05"),
        ]
    )

    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-04")

    assert exc.value.reason_code == "duplicate_paper_id"


def test_invalid_registry_hash_is_rejected(write_registry):
    path = write_registry([paper("lm-000001", hash="not-a-sha")])

    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-04")

    assert exc.value.reason_code == "invalid_paper_hash"


def test_optional_date_provenance_is_blank_by_absence(write_registry):
    path = write_registry(
        [paper("lm-000001", created=None, date_confidence=None, date_basis=None)]
    )

    record = load_month(path, "2026-04").papers[0]

    assert set(record.values) == {
        "paper_id",
        "title",
        "source_file",
        "language",
        "year",
        "month",
        "sha256",
        "canonical_url",
    }
