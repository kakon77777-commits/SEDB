from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .db import Database
from .entities import EntityService
from .fields import FieldService


_RESERVED_COLUMNS = {"id", "kind", "label"}


def _infer_value_type(value: Any) -> str:
    if value is None:
        return "json"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "text"


def _decode_csv_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


class ExchangeService:
    def __init__(self, db: Database):
        self.db = db
        self.fields = FieldService(db)
        self.entities = EntityService(db)

    def export_jsonl(self, path: str | Path) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        entities = self.entities.list_entities(limit=10_000)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for entity in entities:
                full = self.entities.get_entity(entity["id"])
                payload = {
                    "id": full["id"],
                    "kind": full["kind"],
                    "label": full["label"],
                    "values": full["values"],
                }
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
        return len(entities)

    def import_jsonl(self, path: str | Path, *, create_missing_fields: bool = False) -> int:
        path = Path(path)
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                entity_id = str(payload.get("id") or "").strip() or None
                label = str(payload.get("label") or "").strip()
                if not label:
                    raise ValueError(f"line {line_number}: label is required")
                values = payload.get("values") or {}
                if not isinstance(values, dict):
                    raise ValueError(f"line {line_number}: values must be an object")
                for key, value in values.items():
                    try:
                        self.fields.get_field(key)
                    except KeyError:
                        if not create_missing_fields:
                            raise KeyError(f"field not found: {key}") from None
                        self.fields.create_field(
                            key=key,
                            label=key,
                            value_type=_infer_value_type(value),
                            description="Created during JSONL import.",
                        )
                entity = self.entities.create_entity(
                    label=label,
                    kind=str(payload.get("kind") or "record"),
                    entity_id=entity_id,
                )
                for key, value in values.items():
                    self.entities.set_cell(entity["id"], key, value, source="import:jsonl")
                count += 1
        return count

    def _resolve_export_fields(self, field_keys: Iterable[str] | None) -> list[dict[str, Any]]:
        if field_keys is not None:
            return [self.fields.get_field(key) for key in field_keys]
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM fields ORDER BY key").fetchall()
        return [dict(row) for row in rows]

    def export_csv(self, path: str | Path, *, field_keys: Iterable[str] | None = None) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = self._resolve_export_fields(field_keys)
        keys = [field["key"] for field in fields]
        entities = self.entities.list_entities(limit=10_000)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "kind", "label", *keys])
            writer.writeheader()
            for entity in entities:
                full = self.entities.get_entity(entity["id"])
                row: dict[str, str] = {
                    "id": full["id"],
                    "kind": full["kind"],
                    "label": full["label"],
                }
                values = full["values"]
                for key in keys:
                    if key in values:
                        row[key] = json.dumps(
                            values[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")
                        )
                    else:
                        row[key] = ""
                writer.writerow(row)
        return len(entities)

    def import_csv(self, path: str | Path, *, create_missing_fields: bool = False) -> int:
        path = Path(path)
        count = 0
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return 0
            missing_reserved = _RESERVED_COLUMNS - set(reader.fieldnames)
            if missing_reserved:
                raise ValueError(f"CSV missing required columns: {sorted(missing_reserved)}")
            field_keys = [name for name in reader.fieldnames if name not in _RESERVED_COLUMNS]
            if create_missing_fields:
                for key in field_keys:
                    try:
                        self.fields.get_field(key)
                    except KeyError:
                        self.fields.create_field(
                            key=key,
                            label=key,
                            value_type="json",
                            description="Created from CSV header.",
                        )
            else:
                for key in field_keys:
                    try:
                        self.fields.get_field(key)
                    except KeyError:
                        raise KeyError(f"field not found: {key}") from None
            for line_number, row in enumerate(reader, start=2):
                label = str(row.get("label") or "").strip()
                if not label:
                    raise ValueError(f"line {line_number}: label is required")
                entity = self.entities.create_entity(
                    label=label,
                    kind=str(row.get("kind") or "record"),
                    entity_id=str(row.get("id") or "").strip() or None,
                )
                for key in field_keys:
                    raw = row.get(key)
                    if raw is None or raw == "":
                        continue
                    self.entities.set_cell(
                        entity["id"],
                        key,
                        _decode_csv_value(raw),
                        source="import:csv",
                    )
                count += 1
        return count
