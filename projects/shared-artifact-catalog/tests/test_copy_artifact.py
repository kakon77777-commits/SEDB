from __future__ import annotations

from dataclasses import replace
from datetime import timezone
from pathlib import Path

import pytest

from catalog import build_parser
from copy_artifact import CopyRefused, copy_artifact
from paths import CatalogConfig, manifest_digest, sha256_file
from schema import CatalogStore


class FakeTemporal:
    def __init__(self) -> None:
        self.calls = 0

    def register_instant(self, captured_utc, batch_id, operation_kind):
        self.calls += 1
        return {
            "id": f"ctcl:instant:copy-{self.calls}",
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


class CopyFixture:
    def __init__(self, tmp_path: Path) -> None:
        self.staging = tmp_path / "staging"
        self.source_dir = self.staging / "10_Theory" / "package"
        self.source_dir.mkdir(parents=True)
        self.source = self.source_dir / "paper.md"
        self.source.write_text("source paper", encoding="utf-8")
        self.consumer = tmp_path / "consumer"
        self.consumer.mkdir()
        self.store = CatalogStore.open(tmp_path / "catalog.sqlite")
        self.store.ensure_schema()
        self.package = self.store.create_record(
            "package",
            "package",
            {
                "source_path": str(self.source_dir),
                "source_relpath": "10_Theory/package",
                "manifest_sha256": manifest_digest(
                    self.source_dir, frozenset()
                ),
                "availability_state": "available",
            },
        )
        self.component = self.store.create_record(
            "component",
            "paper.md",
            {
                "source_path": str(self.source),
                "source_relpath": "paper.md",
                "parent_package_id": self.package["id"],
                "sha256": sha256_file(self.source),
                "content_identity": sha256_file(self.source),
                "dependency_mode": "independent",
                "required_component_ids": [],
                "availability_state": "available",
            },
        )
        self.config = CatalogConfig(
            catalog_root=self.staging,
            database_path=tmp_path / "catalog.sqlite",
            allowed_copy_roots=(self.consumer,),
            library_zones=("10_Theory",),
            translation_zone="40_Translation_Workspace",
            excluded_names=frozenset(),
            package_roots=("10_Theory/package",),
            ctcl_base_url="https://commoninstant.org",
            ctcl_timeout_seconds=1,
            timezone="Asia/Taipei",
        )
        self.temporal = FakeTemporal()

    def component_request(self, dependency_mode="independent") -> dict:
        self.store.update_current(
            self.component["id"],
            {"dependency_mode": dependency_mode},
            "test",
        )
        return {
            "store": self.store,
            "config": self.config,
            "record_id": self.component["id"],
            "destination": self.consumer / "paper.md",
            "mode": "component",
            "include_required": False,
            "purpose": "test consumer copy",
            "responsibility_ref": "test:consumer",
            "requester_claim": "fixture-ai",
            "host_task_id": "unresolved",
            "temporal_client": self.temporal,
        }

    def package_request(self) -> dict:
        request = self.component_request()
        request.update(
            {
                "record_id": self.package["id"],
                "destination": self.consumer / "package-copy",
                "mode": "package",
            }
        )
        return request

    def dependency_request(self) -> dict:
        dependency_path = self.source_dir / "schema.json"
        dependency_path.write_text("{}", encoding="utf-8")
        dependency = self.store.create_record(
            "component",
            "schema.json",
            {
                "source_path": str(dependency_path),
                "source_relpath": "schema.json",
                "parent_package_id": self.package["id"],
                "sha256": sha256_file(dependency_path),
                "content_identity": sha256_file(dependency_path),
                "dependency_mode": "independent",
                "required_component_ids": [],
                "availability_state": "available",
            },
        )
        self.store.update_current(
            self.component["id"],
            {
                "dependency_mode": "requires_components",
                "required_component_ids": [dependency["id"]],
            },
            "test",
        )
        request = self.component_request(
            dependency_mode="requires_components"
        )
        request.update(
            {
                "mode": "dependency_closure",
                "include_required": True,
                "destination": self.consumer / "closure",
            }
        )
        return request


@pytest.fixture
def copy_fixture(tmp_path: Path) -> CopyFixture:
    return CopyFixture(tmp_path)


def test_component_copy_verifies_bytes_and_records_event(
    copy_fixture: CopyFixture,
) -> None:
    result = copy_artifact(**copy_fixture.component_request())

    assert result.outcome == "copied"
    assert result.source_sha256 == result.destination_sha256
    events = copy_fixture.store.find("copy_event", outcome="copied")
    assert len(events) == 1
    assert events[0]["values"]["host_task_id"] == "unresolved"
    assert events[0]["values"]["temporal_anchor_id"]


def test_whole_package_copy_verifies_manifest(
    copy_fixture: CopyFixture,
) -> None:
    result = copy_artifact(**copy_fixture.package_request())

    assert result.outcome == "copied"
    assert result.source_sha256 == result.destination_sha256
    assert (copy_fixture.consumer / "package-copy" / "paper.md").exists()


def test_explicit_dependency_closure_copies_required_component(
    copy_fixture: CopyFixture,
) -> None:
    result = copy_artifact(**copy_fixture.dependency_request())

    assert result.outcome == "copied"
    assert (copy_fixture.consumer / "closure" / "paper.md").exists()
    assert (copy_fixture.consumer / "closure" / "schema.json").exists()


def test_different_existing_destination_is_refused_and_recorded(
    copy_fixture: CopyFixture,
) -> None:
    request = copy_fixture.component_request()
    request["destination"].write_text("different", encoding="utf-8")

    with pytest.raises(CopyRefused, match="destination collision"):
        copy_artifact(**request)

    events = copy_fixture.store.find("copy_event", outcome="refused")
    assert len(events) == 1
    assert "collision" in events[0]["values"]["failure_reason"]


def test_identical_existing_destination_is_not_rewritten(
    copy_fixture: CopyFixture,
) -> None:
    request = copy_fixture.component_request()
    request["destination"].write_bytes(copy_fixture.source.read_bytes())
    before = request["destination"].stat().st_mtime_ns

    result = copy_artifact(**request)

    assert result.outcome == "already_present"
    assert request["destination"].stat().st_mtime_ns == before


def test_destination_outside_allowed_root_is_refused(
    copy_fixture: CopyFixture,
) -> None:
    request = copy_fixture.component_request()
    request["destination"] = (
        copy_fixture.staging.parent / "outside" / "paper.md"
    )

    with pytest.raises(CopyRefused, match="outside allowed roots"):
        copy_artifact(**request)


def test_ordinary_copy_cannot_target_staging(
    copy_fixture: CopyFixture,
) -> None:
    request = copy_fixture.component_request()
    request["config"] = replace(
        request["config"],
        allowed_copy_roots=(copy_fixture.staging.parent,),
    )
    request["destination"] = (
        copy_fixture.staging / "90_Needs_Review" / "paper.md"
    )

    with pytest.raises(CopyRefused, match="staging root"):
        copy_artifact(**request)


def test_bundle_required_refuses_component_only(
    copy_fixture: CopyFixture,
) -> None:
    request = copy_fixture.component_request(
        dependency_mode="bundle_required"
    )

    with pytest.raises(CopyRefused, match="bundle_required"):
        copy_artifact(**request)


def test_source_hash_drift_is_refused_before_copy(
    copy_fixture: CopyFixture,
) -> None:
    request = copy_fixture.component_request()
    copy_fixture.source.write_text("changed source", encoding="utf-8")

    with pytest.raises(CopyRefused, match="source hash drift"):
        copy_artifact(**request)

    assert not request["destination"].exists()


def test_copy_cli_requires_explicit_scope_arguments() -> None:
    args = build_parser().parse_args(
        [
            "copy",
            "component:test",
            "--destination",
            r"D:\Ai\consumer\paper.md",
            "--mode",
            "component",
            "--purpose",
            "reuse theory",
            "--responsibility-ref",
            "project:consumer",
        ]
    )

    assert args.command == "copy"
    assert args.mode == "component"
    assert args.include_required is False
    assert args.host_task_id == "unresolved"
