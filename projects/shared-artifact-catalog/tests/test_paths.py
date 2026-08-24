from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import paths
from paths import (
    CatalogConfig,
    PathPolicyError,
    is_reparse_point,
    manifest_digest,
    resolve_under,
    sha256_file,
)


def test_config_loads_exact_roots(project_dir: Path) -> None:
    config = CatalogConfig.load(project_dir / "catalog-config.json")

    assert config.catalog_root == Path(
        r"D:\Ai\work together\Theory_Application_Research_Staging"
    )
    assert config.allowed_copy_roots == (Path(r"D:\Ai"),)
    assert config.translation_zone == "40_Translation_Workspace"


def test_relative_database_path_resolves_from_config_directory(
    project_dir: Path, tmp_path: Path
) -> None:
    raw = json.loads(
        (project_dir / "catalog-config.json").read_text(encoding="utf-8")
    )
    raw["database_path"] = "local-catalog.sqlite"
    config_path = tmp_path / "portable-config.json"
    config_path.write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
    )

    config = CatalogConfig.load(config_path)

    assert config.database_path == tmp_path / "local-catalog.sqlite"


def test_resolve_under_rejects_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    with pytest.raises(PathPolicyError, match="outside allowed roots"):
        resolve_under(tmp_path / "outside" / "x.md", (allowed,))


def test_resolve_under_accepts_descendant(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    result = resolve_under(allowed / "nested" / "x.md", (allowed,))

    assert result == (allowed / "nested" / "x.md").resolve(strict=False)


def test_sha_and_manifest_are_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "b.txt").write_text("B", encoding="utf-8")
    (root / "a.txt").write_text("A", encoding="utf-8")

    first_sha = sha256_file(root / "a.txt")
    first_manifest = manifest_digest(root, frozenset())
    second_manifest = manifest_digest(root, frozenset())
    (root / "a.txt").write_text("changed", encoding="utf-8")

    assert first_sha == "559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd"
    assert first_manifest == second_manifest
    assert manifest_digest(root, frozenset()) != first_manifest


def test_windows_reparse_attribute_is_detected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        paths.os,
        "lstat",
        lambda _: SimpleNamespace(
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
        ),
    )

    assert is_reparse_point(tmp_path)
