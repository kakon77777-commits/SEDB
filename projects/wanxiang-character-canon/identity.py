from __future__ import annotations

import hashlib
import unicodedata


def normalize_name_key(value: str) -> str:
    """Normalize only Unicode width/compatibility and whitespace.

    Script conversion is intentionally out of scope: Simplified and Traditional
    spellings remain distinct identity candidates until reviewed.
    """

    normalized = unicodedata.normalize("NFKC", value).strip()
    return " ".join(normalized.split())


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _build_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("build_id must be a positive integer")
    return value


def _hero_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("hero_id must be a non-negative integer")
    return value


def _normalized_path(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\\", "/")
    normalized = "/".join(part for part in normalized.split("/") if part)
    if not normalized:
        raise ValueError("path must not be empty")
    return normalized.lower()


def _slug(value: str, *, label: str) -> str:
    normalized = normalize_name_key(value).lower().replace(" ", "-")
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def character_identity_id(name: str) -> str:
    normalized = normalize_name_key(name)
    if not normalized:
        raise ValueError("name must not be empty")
    return f"wx-char-{_digest(normalized)}"


def build_entity_id(build_id: int) -> str:
    return f"wx-build-{_build_id(build_id)}"


def form_entity_id(build_id: int, hero_id: int) -> str:
    return f"{build_entity_id(build_id)}-hero-{_hero_id(hero_id)}"


def asset_entity_id(build_id: int, resource_path: str) -> str:
    return f"{build_entity_id(build_id)}-asset-{_digest(_normalized_path(resource_path))}"


def candidate_entity_id(build_id: int, output_path: str) -> str:
    return (
        f"{build_entity_id(build_id)}-candidate-"
        f"{_digest(_normalized_path(output_path))}"
    )


def gap_entity_id(build_id: int, role_class: str, hero_id: int) -> str:
    return (
        f"{build_entity_id(build_id)}-gap-"
        f"{_slug(role_class, label='role_class')}-{_hero_id(hero_id)}"
    )


def methodology_entity_id(slug: str, version: str) -> str:
    return (
        f"wx-methodology-{_slug(slug, label='slug')}-"
        f"{_slug(version, label='version')}"
    )
