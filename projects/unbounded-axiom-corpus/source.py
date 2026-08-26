from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import FIELD_SPECS


MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PAPER_ID_RE = re.compile(r"^lm-\d{6}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class SourceValidationError(ValueError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        details: list[dict] | None = None,
    ):
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or []


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    label: str
    values: dict[str, str]


@dataclass(frozen=True)
class RegistrySelection:
    registry_version: str
    registry_count: int
    month: str
    papers: tuple[PaperRecord, ...]


def validate_month(month: str) -> str:
    if not isinstance(month, str) or not MONTH_RE.fullmatch(month):
        raise SourceValidationError("invalid_month", f"invalid month: {month!r}")
    return month


def _required_text(item: dict[str, Any], key: str, paper_id: str) -> str:
    value = item.get(key)
    if (
        value is None
        or isinstance(value, (dict, list, bool))
        or not str(value).strip()
    ):
        raise SourceValidationError(
            "invalid_paper_field",
            f"paper {paper_id} has invalid required field {key}",
            [{"paper_id": paper_id, "field": key}],
        )
    return str(value)


def _record(item: dict[str, Any], month: str) -> PaperRecord:
    paper_id = _required_text(item, "id", "unresolved")
    if not PAPER_ID_RE.fullmatch(paper_id):
        raise SourceValidationError(
            "invalid_paper_id", f"invalid paper id: {paper_id}"
        )
    if item.get("month") != month:
        raise SourceValidationError(
            "paper_month_mismatch", f"paper {paper_id} month mismatch"
        )
    if not SHA256_RE.fullmatch(str(item.get("hash", ""))):
        raise SourceValidationError(
            "invalid_paper_hash", f"paper {paper_id} has invalid hash"
        )

    values: dict[str, str] = {}
    for spec in FIELD_SPECS:
        value = item.get(spec.source_key)
        if value is None:
            if spec.optional:
                continue
            raise SourceValidationError(
                "invalid_paper_field",
                f"paper {paper_id} missing required field {spec.source_key}",
            )
        if isinstance(value, (dict, list, bool)):
            raise SourceValidationError(
                "invalid_paper_field",
                f"paper {paper_id} field {spec.source_key} "
                "is not scalar text-compatible",
            )
        text = str(value)
        if not text.strip() and not spec.optional:
            raise SourceValidationError(
                "invalid_paper_field",
                f"paper {paper_id} field {spec.source_key} is blank",
            )
        if text.strip() or not spec.optional:
            values[spec.key] = text

    return PaperRecord(paper_id=paper_id, label=values["title"], values=values)


def load_month(path: str | Path, month: str) -> RegistrySelection:
    month = validate_month(month)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceValidationError("registry_read_error", str(exc)) from exc

    if not isinstance(payload, dict):
        raise SourceValidationError(
            "invalid_registry", "registry root must be an object"
        )
    if payload.get("version") != "0.2":
        raise SourceValidationError(
            "unsupported_registry_version", "registry version must be 0.2"
        )

    items = payload.get("items")
    count = payload.get("count")
    if not isinstance(items, list) or not isinstance(count, int):
        raise SourceValidationError(
            "invalid_registry", "registry count/items shape is invalid"
        )
    if count != len(items):
        raise SourceValidationError(
            "registry_count_mismatch", "registry count does not match items"
        )

    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise SourceValidationError(
                "invalid_registry_item", "registry item must be an object"
            )
        item_id = item.get("id")
        if not isinstance(item_id, str) or not PAPER_ID_RE.fullmatch(item_id):
            raise SourceValidationError(
                "invalid_paper_id", f"invalid paper id: {item_id!r}"
            )
        if item_id in seen:
            raise SourceValidationError(
                "duplicate_paper_id", f"duplicate paper id: {item_id}"
            )
        seen.add(item_id)

    selected_items = [item for item in items if item.get("month") == month]
    if not selected_items:
        raise SourceValidationError(
            "target_month_empty", f"month {month} contains zero papers"
        )

    papers = tuple(
        sorted(
            (_record(item, month) for item in selected_items),
            key=lambda item: item.paper_id,
        )
    )
    return RegistrySelection(str(payload["version"]), count, month, papers)
