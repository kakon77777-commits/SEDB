from __future__ import annotations

from dataclasses import replace
from datetime import timezone
from pathlib import Path

from bootstrap_mwt import bootstrap_mwt
from paths import CatalogConfig, iter_safe_files, sha256_file
from schema import CatalogStore


class FakeTemporal:
    def __init__(self) -> None:
        self.calls = 0

    def register_instant(self, captured_utc, batch_id, operation_kind):
        self.calls += 1
        return {
            "id": "ctcl:instant:mwt-test",
            "reference": {
                "value": captured_utc.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            },
            "source": {"name": "test-clock"},
            "quality": {
                "precision": "ms",
                "estimated_uncertainty_ns": 1_000_000,
            },
        }


def source_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_file(path)
        for path in iter_safe_files(root, frozenset())
    }


def test_mwt_bootstrap_represents_mixed_catalog_idempotently(
    project_dir: Path, tmp_path: Path
) -> None:
    real_config = CatalogConfig.load(project_dir / "catalog-config.json")
    config = replace(real_config, database_path=tmp_path / "catalog.sqlite")
    store = CatalogStore.open(config.database_path)
    store.ensure_schema()
    temporal = FakeTemporal()
    original = Path(
        r"D:\我的研究\學術討論\論文\真終極\真本體論12\MWT"
    )
    before = source_hashes(original)

    first = bootstrap_mwt(config, store, temporal)
    package_updated_at = {
        record["id"]: record["updated_at"] for record in store.find("package")
    }
    relation_count = len(store.find("relation"))
    second = bootstrap_mwt(config, store, temporal)

    assert first.package_count == 31
    assert first.component_count == 768
    assert first.temporal_anchor_id
    assert second.changed_count == 0
    assert second.temporal_anchor_id is None
    assert len(store.find("package")) == 31
    assert len(store.find("component")) == 768
    assert len(store.find("temporal_anchor")) == 1
    assert temporal.calls == 1
    assert len(store.find("relation")) == relation_count
    assert {
        record["id"]: record["updated_at"] for record in store.find("package")
    } == package_updated_at
    assert store.find(
        "package", stable_key="mwt-v0.1-first-cycle-canonical-pack"
    )
    assert store.find(
        "package", stable_key="dgw-5a-general-boundary-complex-v7.0"
    )
    assert store.find("package", verification_state="needs_review")
    assert len(
        store.find("relation", relation_type="classified_as")
    ) >= 31
    assert all(
        "00_Inbox" not in record["values"]["source_path"]
        for record in store.find("component")
    )
    assert before == source_hashes(original)


def test_mwt_bootstrap_ignores_registered_non_mwt_families(
    project_dir: Path, tmp_path: Path
) -> None:
    catalog_root = tmp_path / "catalog"
    classification = (
        catalog_root
        / "00_Inbox"
        / "MWT_2026-08-24"
        / "MWT_CLASSIFICATION.md"
    )
    classification.parent.mkdir(parents=True)
    classification.write_text("# MWT test classification\n", encoding="utf-8")

    mwt_root = catalog_root / "10_Theory" / "MWT" / "Candidate"
    mwt_root.mkdir(parents=True)
    (mwt_root / "paper.md").write_text("理論", encoding="utf-8")

    other_root = (
        catalog_root
        / "30_Research"
        / "Self_Constraint_Cognitive_Runtime"
        / "Executable_Experiments"
        / "Other_Package"
    )
    other_root.mkdir(parents=True)
    (other_root / "experiment.py").write_text("VALUE = 1\n", encoding="utf-8")

    real_config = CatalogConfig.load(project_dir / "catalog-config.json")
    config = replace(
        real_config,
        catalog_root=catalog_root,
        database_path=tmp_path / "catalog.sqlite",
        allowed_copy_roots=(catalog_root,),
        package_roots=(
            "10_Theory/MWT/Candidate",
            (
                "30_Research/Self_Constraint_Cognitive_Runtime/"
                "Executable_Experiments/Other_Package"
            ),
        ),
    )
    store = CatalogStore.open(config.database_path)
    store.ensure_schema()

    result = bootstrap_mwt(config, store, FakeTemporal())
    packages = {
        record["values"]["source_relpath"]: record
        for record in store.find("package")
    }

    assert result.package_count == 1
    assert packages["10_Theory/MWT/Candidate"]["values"][
        "verification_state"
    ] == "verified_integrity_candidate"
    assert (
        "30_Research/Self_Constraint_Cognitive_Runtime/"
        "Executable_Experiments/Other_Package"
    ) not in packages
