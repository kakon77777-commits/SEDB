from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


def normalize_table_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not slug:
        raise ValueError("table must contain an ASCII letter or digit")
    return slug


def canonical_source_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("source_id must be a string or number")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def table_row_entity_id(
    build_id: int,
    table: str,
    source_id: Any,
    *,
    row_number: int,
    workbook_sha256: str,
) -> str:
    if isinstance(build_id, bool) or not isinstance(build_id, int) or build_id <= 0:
        raise ValueError("build_id must be a positive integer")
    table_key = normalize_table_key(table)
    prefix = f"wx-build-{build_id}-row-{table_key}"
    if source_id is not None:
        canonical_id = canonical_source_id(source_id)
        return f"{prefix}-{_digest([build_id, table_key, canonical_id])}"
    if isinstance(row_number, bool) or not isinstance(row_number, int) or row_number < 1:
        raise ValueError("row_number must be a positive integer")
    normalized_sha = workbook_sha256.strip().upper()
    if not re.fullmatch(r"[0-9A-F]{64}", normalized_sha):
        raise ValueError("workbook_sha256 must be 64 hexadecimal characters")
    return f"{prefix}-r{row_number}-{_digest([build_id, table_key, row_number, normalized_sha])}"


def reference_edge_entity_id(
    source_entity_id: str,
    source_field: str,
    slot: int,
    target_table: str | None,
    target_source_id: Any,
) -> str:
    return "wx-edge-" + _digest(
        [
            source_entity_id,
            source_field,
            slot,
            target_table,
            target_source_id,
        ]
    )
