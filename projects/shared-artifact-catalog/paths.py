from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


class PathPolicyError(ValueError):
    """Raised when a filesystem target crosses a configured safety boundary."""


@dataclass(frozen=True)
class CatalogConfig:
    catalog_root: Path
    database_path: Path
    allowed_copy_roots: tuple[Path, ...]
    library_zones: tuple[str, ...]
    translation_zone: str
    excluded_names: frozenset[str]
    package_roots: tuple[str, ...]
    ctcl_base_url: str
    ctcl_timeout_seconds: float
    timezone: str

    @classmethod
    def load(cls, path: str | Path) -> "CatalogConfig":
        config_path = Path(path)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("unsupported catalog config schema_version")
        database_path = Path(raw["database_path"])
        if not database_path.is_absolute():
            database_path = config_path.parent / database_path
        return cls(
            catalog_root=Path(raw["catalog_root"]),
            database_path=database_path,
            allowed_copy_roots=tuple(
                Path(item) for item in raw["allowed_copy_roots"]
            ),
            library_zones=tuple(str(item) for item in raw["library_zones"]),
            translation_zone=str(raw["translation_zone"]),
            excluded_names=frozenset(
                str(item) for item in raw["excluded_names"]
            ),
            package_roots=tuple(str(item) for item in raw["package_roots"]),
            ctcl_base_url=str(raw["ctcl"]["base_url"]).rstrip("/"),
            ctcl_timeout_seconds=float(raw["ctcl"]["timeout_seconds"]),
            timezone=str(raw["ctcl"]["timezone"]),
        )


def resolve_under(
    path: str | Path, roots: Iterable[str | Path]
) -> Path:
    resolved = Path(path).resolve(strict=False)
    allowed = tuple(Path(root).resolve(strict=False) for root in roots)

    def inside(root: Path) -> bool:
        try:
            return os.path.commonpath((str(resolved), str(root))) == str(root)
        except ValueError:
            return False

    if not any(inside(root) for root in allowed):
        raise PathPolicyError(f"outside allowed roots: {resolved}")
    return resolved


def is_reparse_point(path: str | Path) -> bool:
    attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    return bool(
        attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_safe_files(
    root: str | Path, exclusions: frozenset[str]
) -> Iterator[Path]:
    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise PathPolicyError(f"package root is not a directory: {root_path}")
    if is_reparse_point(root_path):
        raise PathPolicyError(f"reparse point refused: {root_path}")

    for current, dirs, files in os.walk(root_path, followlinks=False):
        current_path = Path(current)
        retained_dirs: list[str] = []
        for dirname in sorted(dirs):
            if dirname in exclusions:
                continue
            child = current_path / dirname
            if is_reparse_point(child):
                raise PathPolicyError(f"reparse point refused: {child}")
            retained_dirs.append(dirname)
        dirs[:] = retained_dirs

        for name in sorted(files):
            if name in exclusions:
                continue
            path = current_path / name
            if is_reparse_point(path):
                raise PathPolicyError(f"reparse point refused: {path}")
            yield path


def manifest_digest(
    root: str | Path, exclusions: frozenset[str]
) -> str:
    root_path = Path(root).resolve(strict=True)
    digest = hashlib.sha256()
    for path in iter_safe_files(root_path, exclusions):
        relative = path.relative_to(root_path).as_posix()
        digest.update(
            (
                f"{relative}\t{path.stat().st_size}\t"
                f"{sha256_file(path)}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()
