from __future__ import annotations

import csv
import hashlib

import pytest

from config import ProjectConfig
from source import SourceValidationError, load_catalog


def config(data):
    return ProjectConfig(
        source_root=data["root"],
        database_path=data["db"],
        source_hashes=data["hashes"],
        expected_entity_counts=data["expected_counts"],
    )


def test_load_catalog_classifies_all_fixture_records(source_fixture):
    snapshot = load_catalog(config(source_fixture))

    assert snapshot.entity_counts == source_fixture["expected_counts"]
    assert len(snapshot.records) == 10
    assert len(snapshot.fingerprint) == 64
    model = next(record for record in snapshot.records if record.kind == "fj_model_snapshot")
    assert model.entity_id == "fj-model-25099888-5ccbf01fcde70c9850a4"
    assert model.values["fj_classification"] == "state_owner"
    assert model.values["fj_random_call_count"] == 2
    assert model.values["fj_hashset_field_count"] == 1
    assert load_catalog(config(source_fixture)).fingerprint == snapshot.fingerprint


def test_source_hash_drift_blocks_before_parsing(source_fixture):
    path = source_fixture["root"] / "evidence/build-25099888/trigger-summary.csv"
    path.write_text(path.read_text(encoding="utf-8") + "drift", encoding="utf-8")

    with pytest.raises(SourceValidationError) as exc:
        load_catalog(config(source_fixture))

    assert exc.value.reason_code == "source_hash_mismatch"
    assert exc.value.details[0]["path"] == "evidence/build-25099888/trigger-summary.csv"


def test_duplicate_trigger_id_is_rejected_after_hash_revalidation(source_fixture):
    path = source_fixture["root"] / "evidence/build-25099888/trigger-summary.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fieldnames).writerow(rows[0])
    source_fixture["hashes"][path.relative_to(source_fixture["root"]).as_posix()] = (
        hashlib.sha256(path.read_bytes()).hexdigest()
    )
    source_fixture["expected_counts"]["fj_trigger_snapshot"] = 2

    with pytest.raises(SourceValidationError) as exc:
        load_catalog(config(source_fixture))

    assert exc.value.reason_code == "duplicate_source_id"
