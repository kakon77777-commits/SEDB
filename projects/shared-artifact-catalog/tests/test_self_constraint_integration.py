from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import timezone
from pathlib import Path

from paths import CatalogConfig
from schema import CatalogStore


UNBOUNDED_AXIOM = "https://unboundedaxiom.org/"
NEOK = "https://thisoneisneok.com/"


class FakeTemporal:
    def __init__(self) -> None:
        self.calls = 0

    def register_instant(self, captured_utc, batch_id, operation_kind):
        self.calls += 1
        return {
            "id": "ctcl:instant:self-constraint-test",
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


def _write_package(catalog_root: Path, relative: str, filename: str) -> None:
    package = catalog_root / relative
    package.mkdir(parents=True)
    (package / filename).write_text("fixture\n", encoding="utf-8")


def _category_ids(store: CatalogStore, record_id: str) -> set[str]:
    return {
        relation["values"]["target_record_id"]
        for relation in store.find(
            "relation",
            relation_type="classified_as",
            source_record_id=record_id,
        )
    }


def test_self_constraint_bootstrap_routes_languages_and_status_idempotently(
    project_dir: Path, tmp_path: Path
) -> None:
    module = importlib.import_module("bootstrap_self_constraint")
    catalog_root = tmp_path / "catalog"
    classification = (
        catalog_root
        / "00_Inbox"
        / "Self_Constraint_Experimental_Harness_2026-08-25"
        / "SELF_CONSTRAINT_CLASSIFICATION.md"
    )
    classification.parent.mkdir(parents=True)
    classification.write_text(
        "# Self-constraint test classification\n", encoding="utf-8"
    )

    roots = {
        "theory": (
            "10_Theory/Self_Constraint_Cognitive_Runtime/"
            "UnboundedAxiom_Candidates_Not_Published/zh-Hant/"
            "ACR_Phase12_Unified_Theory_Source_Set_v0.2"
        ),
        "application": (
            "20_Applications/Self_Constraint_Cognitive_Runtime/"
            "NeoK_Experimental_Candidates_Not_Published/"
            "ACR_Phase12_PAGL_Milestone2_DRS_Access_View_"
            "v0.2_2026-08-25"
        ),
        "history": (
            "30_Research/Self_Constraint_Cognitive_Runtime/"
            "ACR_Version_History/"
            "Addressable_Cognitive_Runtime_MVP_v0.1_Phase11_"
            "Context_Compression_2026-08-24"
        ),
        "experiment": (
            "30_Research/Self_Constraint_Cognitive_Runtime/"
            "Executable_Experiments/"
            "Neural_Self_Constraint_Experiment_v0.2_2026-08-20"
        ),
        "reference": (
            "30_Research/Self_Constraint_Cognitive_Runtime/"
            "Reference_Source_Packs/"
            "ACR_Phase12_Unified_Autonomy_Governance_Integration_"
            "Pack_v0.2_2026-08-25"
        ),
        "duplicate": (
            "30_Research/Self_Constraint_Cognitive_Runtime/"
            "Legacy_Standalone_Duplicates"
        ),
        "review": (
            "90_Needs_Review/Self_Constraint_Cognitive_Runtime/"
            "Theory_Claims_and_Docx_QA/en/SCL_Legacy_Theory_Papers"
        ),
    }
    filenames = {
        "theory": "paper.md",
        "application": "runtime.py",
        "history": "history.py",
        "experiment": "experiment.py",
        "reference": "whitepaper.md",
        "duplicate": "duplicate.md",
        "review": "legacy.docx",
    }
    for key, relative in roots.items():
        _write_package(catalog_root, relative, filenames[key])
    unrelated_mwt = "10_Theory/MWT/Unrelated_Candidate"
    _write_package(catalog_root, unrelated_mwt, "mwt.md")

    real_config = CatalogConfig.load(project_dir / "catalog-config.json")
    config = replace(
        real_config,
        catalog_root=catalog_root,
        database_path=tmp_path / "catalog.sqlite",
        allowed_copy_roots=(catalog_root,),
        package_roots=(*roots.values(), unrelated_mwt),
    )
    store = CatalogStore.open(config.database_path)
    store.ensure_schema()
    temporal = FakeTemporal()

    first = module.bootstrap_self_constraint(config, store, temporal)
    relation_count = len(store.find("relation"))
    package_updated_at = {
        record["id"]: record["updated_at"] for record in store.find("package")
    }
    second = module.bootstrap_self_constraint(config, store, temporal)

    packages = {
        record["values"]["source_relpath"]: record
        for record in store.find("package")
    }
    theory = packages[roots["theory"]]
    application = packages[roots["application"]]
    history = packages[roots["history"]]
    experiment = packages[roots["experiment"]]
    reference = packages[roots["reference"]]
    duplicate = packages[roots["duplicate"]]
    review = packages[roots["review"]]

    assert first.package_count == 7
    assert first.component_count == 7
    assert first.temporal_anchor_id
    assert second.changed_count == 0
    assert second.temporal_anchor_id is None
    assert temporal.calls == 1
    assert len(store.find("temporal_anchor")) == 1
    assert len(store.find("relation")) == relation_count
    assert {
        record["id"]: record["updated_at"] for record in store.find("package")
    } == package_updated_at

    assert theory["values"]["content_languages"] == ["zh-Hant"]
    assert theory["values"]["suggested_routes"] == [UNBOUNDED_AXIOM]
    assert theory["values"][
        "canonicality_state"
    ] == "open_revision_source_set"
    assert _category_ids(store, theory["id"]) >= {
        "category:theory",
        "category:documentation",
    }

    assert application["values"]["programming_languages"] == ["Python"]
    assert application["values"]["suggested_routes"] == [NEOK]
    assert application["values"][
        "verification_state"
    ] == "independently_verified_milestone_candidate"
    assert application["values"][
        "canonicality_state"
    ] == "latest_incomplete_milestone"
    assert _category_ids(store, application["id"]) >= {
        "category:experimental_application",
        "category:application",
        "category:source_code",
        "category:validation_evidence",
    }

    assert history["values"]["canonicality_state"] == "superseded"
    assert history["values"][
        "verification_state"
    ] == "independently_verified_historical_runtime"
    assert experiment["values"][
        "verification_state"
    ] == "independently_verified_test_suite"
    assert _category_ids(store, reference["id"]) >= {
        "category:research_evidence",
        "category:theory",
        "category:documentation",
    }
    assert reference["values"][
        "verification_state"
    ] == "verified_preimplementation_integration_pack"
    assert reference["values"][
        "canonicality_state"
    ] == "open_revision_anchor"
    assert duplicate["values"]["verification_state"] == "verified_duplicate"
    assert review["values"][
        "verification_state"
    ] == "text_reviewed_visual_qa_unavailable"
    assert review["values"]["suggested_routes"] == []
    assert unrelated_mwt not in packages
    assert _category_ids(store, review["id"]) >= {
        "category:needs_review",
        "category:theory",
        "category:documentation",
    }
