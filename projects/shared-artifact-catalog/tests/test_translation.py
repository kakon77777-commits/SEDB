from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest

import translation
from catalog import build_parser
from paths import CatalogConfig, sha256_file
from schema import CatalogStore
from translation import (
    TranslationRefused,
    complete_translation,
    mark_stale_translations,
    start_translation,
)


class FakeTemporal:
    def __init__(self) -> None:
        self.calls = 0

    def register_instant(self, captured_utc, batch_id, operation_kind):
        self.calls += 1
        return {
            "id": f"ctcl:instant:{operation_kind}-{self.calls}",
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


class TranslationFixture:
    def __init__(self, tmp_path: Path) -> None:
        self.staging = tmp_path / "staging"
        source_dir = self.staging / "10_Theory" / "pkg"
        source_dir.mkdir(parents=True)
        self.source_name = "paper.zh-Hant.md"
        self.source = source_dir / self.source_name
        self.source.write_text("來源內容", encoding="utf-8")
        self.source_sha256 = sha256_file(self.source)
        self.store = CatalogStore.open(tmp_path / "catalog.sqlite")
        self.store.ensure_schema()
        package = self.store.create_record(
            "package",
            "pkg",
            {
                "source_path": str(source_dir),
                "source_relpath": "10_Theory/pkg",
                "availability_state": "available",
            },
        )
        self.component = self.store.create_record(
            "component",
            self.source_name,
            {
                "source_path": str(self.source),
                "source_relpath": self.source_name,
                "parent_package_id": package["id"],
                "sha256": self.source_sha256,
                "content_identity": self.source_sha256,
                "content_languages": ["zh-Hant"],
                "availability_state": "available",
            },
        )
        self.config = CatalogConfig(
            catalog_root=self.staging,
            database_path=tmp_path / "catalog.sqlite",
            allowed_copy_roots=(tmp_path,),
            library_zones=("10_Theory", "40_Translation_Workspace"),
            translation_zone="40_Translation_Workspace",
            excluded_names=frozenset(),
            package_roots=("10_Theory/pkg",),
            ctcl_base_url="https://commoninstant.org",
            ctcl_timeout_seconds=1,
            timezone="Asia/Taipei",
        )
        self.temporal = FakeTemporal()

    def start_request(self, target_language: str) -> dict:
        return {
            "store": self.store,
            "config": self.config,
            "source_component_id": self.component["id"],
            "target_language": target_language,
            "translation_scope": "full_text",
            "translator_claim": "fixture-ai",
            "host_task_id": "unresolved",
            "temporal_client": self.temporal,
        }

    def complete_request(self, job_id: str) -> dict:
        return {
            "store": self.store,
            "config": self.config,
            "job_id": job_id,
            "translator_claim": "fixture-ai",
            "host_task_id": "unresolved",
            "temporal_client": self.temporal,
        }


@pytest.fixture
def translation_fixture(tmp_path: Path) -> TranslationFixture:
    return TranslationFixture(tmp_path)


def test_start_translation_creates_isolated_source_snapshot(
    translation_fixture: TranslationFixture,
) -> None:
    job = start_translation(
        **translation_fixture.start_request(target_language="en")
    )
    source_ref = json.loads(
        (job.path / "SOURCE_REF.json").read_text(encoding="utf-8")
    )

    assert source_ref["source_sha256"] == translation_fixture.source_sha256
    assert source_ref["target_language"] == "en"
    assert (
        job.path
        / "source_snapshot"
        / translation_fixture.source_name
    ).exists()
    assert (job.path / "work").is_dir()
    assert job.lifecycle_state == "in_progress"
    assert translation_fixture.temporal.calls == 1
    assert len(translation_fixture.store.find("translation_event")) == 2


def test_invalid_language_is_refused_without_creating_job(
    translation_fixture: TranslationFixture,
) -> None:
    with pytest.raises(TranslationRefused, match="BCP 47"):
        start_translation(
            **translation_fixture.start_request(target_language="english")
        )

    assert translation_fixture.store.find("translation_job") == []
    assert translation_fixture.temporal.calls == 0


def test_corrupt_source_snapshot_is_refused_before_job_registration(
    translation_fixture: TranslationFixture, monkeypatch
) -> None:
    def corrupt_copy(_source, destination):
        Path(destination).write_text("corrupt", encoding="utf-8")

    monkeypatch.setattr(translation.shutil, "copy2", corrupt_copy)

    with pytest.raises(TranslationRefused, match="snapshot hash verification"):
        start_translation(
            **translation_fixture.start_request(target_language="en")
        )

    assert translation_fixture.store.find("translation_job") == []


def test_completion_is_candidate_not_approved_and_registers_relation(
    translation_fixture: TranslationFixture,
) -> None:
    job = start_translation(
        **translation_fixture.start_request(target_language="en")
    )
    output = job.path / "work" / "paper.en.md"
    output.write_text("Candidate translation", encoding="utf-8")

    completed = complete_translation(
        **translation_fixture.complete_request(job.id)
    )

    assert completed.lifecycle_state == "candidate"
    assert translation_fixture.temporal.calls == 2
    assert len(completed.output_component_ids) == 1
    relation = translation_fixture.store.find(
        "relation", relation_type="translation_of"
    )
    assert len(relation) == 1
    assert (
        relation[0]["values"]["target_record_id"]
        == translation_fixture.component["id"]
    )
    assert translation_fixture.store.find(
        "translation_job", lifecycle_state="approved"
    ) == []


def test_source_hash_change_marks_job_stale(
    translation_fixture: TranslationFixture,
) -> None:
    job = start_translation(
        **translation_fixture.start_request(target_language="en")
    )
    translation_fixture.source.write_text("來源內容已變更", encoding="utf-8")

    stale = mark_stale_translations(
        translation_fixture.store,
        translation_fixture.config,
        translation_fixture.temporal,
    )

    assert job.id in stale
    assert translation_fixture.temporal.calls == 2
    assert translation_fixture.store.get_record(job.id)["values"][
        "lifecycle_state"
    ] == "stale"
    with pytest.raises(TranslationRefused, match="source hash drift"):
        complete_translation(
            **translation_fixture.complete_request(job.id)
        )


def test_unicode_replacement_character_is_refused(
    translation_fixture: TranslationFixture,
) -> None:
    job = start_translation(
        **translation_fixture.start_request(target_language="en")
    )
    (job.path / "work" / "paper.en.md").write_text(
        "bad \ufffd output", encoding="utf-8"
    )

    with pytest.raises(TranslationRefused, match="replacement character"):
        complete_translation(
            **translation_fixture.complete_request(job.id)
        )

    assert translation_fixture.store.get_record(job.id)["values"][
        "lifecycle_state"
    ] == "in_progress"


def test_translation_cli_exposes_start_and_complete_commands() -> None:
    start = build_parser().parse_args(
        [
            "translate-start",
            "component:test",
            "--target-language",
            "en",
            "--scope",
            "full_text",
        ]
    )
    complete = build_parser().parse_args(
        ["translate-complete", "translation-job:test"]
    )

    assert start.command == "translate-start"
    assert start.host_task_id == "unresolved"
    assert complete.command == "translate-complete"
