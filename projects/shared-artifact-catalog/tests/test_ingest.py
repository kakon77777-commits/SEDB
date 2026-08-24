from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ingest import ingest_package_paths, scan_package
from paths import CatalogConfig, sha256_file
from schema import CatalogStore


class CountingTemporalClient:
    def __init__(self) -> None:
        self.calls = 0

    def register_instant(self, captured_utc, batch_id, operation_kind):
        self.calls += 1
        return {
            "id": f"ctcl:instant:test-{self.calls}",
            "reference": {
                "value": captured_utc.isoformat().replace("+00:00", "Z")
            },
            "source": {"name": "test-clock"},
            "quality": {
                "precision": "ms",
                "estimated_uncertainty_ns": 1_000_000,
            },
        }


class CatalogHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "staging"
        self.zone = self.root / "10_Theory"
        self.zone.mkdir(parents=True)
        self.config = CatalogConfig(
            catalog_root=self.root,
            database_path=tmp_path / "catalog.sqlite",
            allowed_copy_roots=(tmp_path / "consumer",),
            library_zones=("10_Theory",),
            translation_zone="40_Translation_Workspace",
            excluded_names=frozenset(
                {"__pycache__", "node_modules", ".pytest_cache"}
            ),
            package_roots=(),
            ctcl_base_url="https://commoninstant.org",
            ctcl_timeout_seconds=1,
            timezone="Asia/Taipei",
        )
        self.store = CatalogStore.open(self.config.database_path)
        self.store.ensure_schema()
        self.temporal = CountingTemporalClient()
        self.paths: list[Path] = []

    def package(self, name: str, files: dict[str, str]) -> Path:
        root = self.zone / name
        root.mkdir()
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.paths.append(root)
        return root

    def file_package(self, name: str, content: str) -> Path:
        path = self.zone / name
        path.write_text(content, encoding="utf-8")
        self.paths.append(path)
        return path

    def ingest(self):
        return self.ingest_paths(*self.paths)

    def ingest_paths(self, *paths: Path):
        return ingest_package_paths(
            paths, self.config, self.store, self.temporal
        )

    @staticmethod
    def sha_for(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def catalog_fixture(tmp_path: Path) -> CatalogHarness:
    return CatalogHarness(tmp_path)


def test_changed_batch_uses_one_anchor_and_unchanged_rescan_uses_none(
    catalog_fixture: CatalogHarness,
) -> None:
    catalog_fixture.package("a", {"paper.md": "A"})
    catalog_fixture.package("b", {"data.json": "{}"})

    first = catalog_fixture.ingest()
    second = catalog_fixture.ingest()

    assert first.changed_count > 0
    assert first.package_count == 2
    assert first.component_count == 2
    assert first.temporal_anchor_id
    assert second.changed_count == 0
    assert second.temporal_anchor_id is None
    assert catalog_fixture.temporal.calls == 1
    assert len(catalog_fixture.store.find("temporal_anchor")) == 1


def test_duplicate_bytes_keep_two_component_occurrences(
    catalog_fixture: CatalogHarness,
) -> None:
    first = catalog_fixture.package("a", {"paper.md": "same"})
    second = catalog_fixture.package("b", {"copy.md": "same"})

    catalog_fixture.ingest_paths(first, second)
    components = catalog_fixture.store.find(
        "component", content_identity=catalog_fixture.sha_for("same")
    )

    assert len(components) == 2
    assert (
        components[0]["values"]["parent_package_id"]
        != components[1]["values"]["parent_package_id"]
    )


def test_hash_change_creates_version_event_and_updates_current_component(
    catalog_fixture: CatalogHarness,
) -> None:
    package = catalog_fixture.package("p", {"paper.md": "v1"})
    catalog_fixture.ingest_paths(package)
    (package / "paper.md").write_text("v2", encoding="utf-8")

    result = catalog_fixture.ingest_paths(package)
    events = catalog_fixture.store.find(
        "component_version_event", outcome="content_changed"
    )
    component = catalog_fixture.store.find("component")[0]

    assert result.changed_count >= 2
    assert catalog_fixture.temporal.calls == 2
    assert len(events) == 1
    assert events[0]["values"]["source_sha256"] == catalog_fixture.sha_for(
        "v1"
    )
    assert events[0]["values"]["sha256"] == catalog_fixture.sha_for("v2")
    assert component["values"]["sha256"] == catalog_fixture.sha_for("v2")


def test_unchanged_moved_package_preserves_package_identity(
    catalog_fixture: CatalogHarness,
) -> None:
    package = catalog_fixture.package("before", {"paper.md": "same"})
    catalog_fixture.ingest_paths(package)
    original_id = catalog_fixture.store.find("package")[0]["id"]
    moved = package.with_name("after")
    package.rename(moved)

    catalog_fixture.ingest_paths(moved)
    packages = catalog_fixture.store.find("package")
    moved_events = catalog_fixture.store.find(
        "package_version_event", outcome="moved"
    )

    assert len(packages) == 1
    assert packages[0]["id"] == original_id
    assert packages[0]["values"]["source_relpath"] == "10_Theory/after"
    assert len(moved_events) == 1


def test_single_file_package_has_one_component_and_file_hash_manifest(
    catalog_fixture: CatalogHarness,
) -> None:
    path = catalog_fixture.file_package("standalone.md", "standalone")

    snapshot = scan_package(path, catalog_fixture.config)
    result = catalog_fixture.ingest_paths(path)

    assert snapshot.manifest_sha256 == sha256_file(path)
    assert len(snapshot.components) == 1
    assert snapshot.components[0].relpath == "standalone.md"
    assert result.package_count == 1
    assert result.component_count == 1


def test_removed_component_is_marked_missing_not_deleted(
    catalog_fixture: CatalogHarness,
) -> None:
    package = catalog_fixture.package(
        "p", {"keep.md": "keep", "remove.md": "remove"}
    )
    catalog_fixture.ingest_paths(package)
    (package / "remove.md").unlink()

    catalog_fixture.ingest_paths(package)
    missing = catalog_fixture.store.find(
        "component", availability_state="missing"
    )
    events = catalog_fixture.store.find(
        "component_version_event", outcome="missing"
    )

    assert len(catalog_fixture.store.find("component")) == 2
    assert len(missing) == 1
    assert missing[0]["values"]["source_relpath"] == "remove.md"
    assert len(events) == 1


def test_excluded_tree_is_not_ingested(catalog_fixture: CatalogHarness) -> None:
    package = catalog_fixture.package(
        "web", {"index.html": "ok", "node_modules/pkg/index.js": "ignored"}
    )

    catalog_fixture.ingest_paths(package)
    components = catalog_fixture.store.find("component")

    assert [item["values"]["source_relpath"] for item in components] == [
        "index.html"
    ]
