from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "p": PACKAGE_REL_NS}


class WorkbookReadError(ValueError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class HeaderOverride:
    cell_reference: str
    expected_header: str
    replacement_header: str
    reason: str
    expected_workbook_sha256: str | None = None


@dataclass(frozen=True)
class WorkbookRow:
    row_number: int
    values: dict[str, Any]
    canonical_json: str
    sha256: str


@dataclass(frozen=True)
class WorkbookSnapshot:
    path: Path
    sha256: str
    headers: tuple[str, ...]
    metadata_rows: tuple[dict[str, Any], ...]
    rows: tuple[WorkbookRow, ...]
    header_overrides: tuple[HeaderOverride, ...] = ()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    if not letters:
        raise WorkbookReadError("invalid_cell_reference", reference)
    value = 0
    for character in letters.upper():
        value = value * 26 + (ord(character) - ord("A") + 1)
    return value - 1


def _normalize_relationship_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    if "://" in normalized or normalized.startswith("//"):
        raise WorkbookReadError("external_target_rejected", target)
    parts = PurePosixPath(normalized.lstrip("/")).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise WorkbookReadError("relationship_path_escape", target)
    if parts[0] == "xl":
        return PurePosixPath(*parts).as_posix()
    return (PurePosixPath("xl") / PurePosixPath(*parts)).as_posix()


def _sheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError) as exc:
        raise WorkbookReadError("workbook_structure_invalid", str(exc)) from exc

    relationship_id: str | None = None
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        if sheet.attrib.get("name") == sheet_name:
            relationship_id = sheet.attrib.get(f"{{{REL_NS}}}id")
            break
    if relationship_id is None:
        raise WorkbookReadError("sheet_missing", sheet_name)

    target: str | None = None
    for relationship in relationships.findall("p:Relationship", NS):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib.get("Target")
            break
    if not target:
        raise WorkbookReadError("sheet_relationship_missing", sheet_name)
    return _normalize_relationship_target(target)


def _shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return ()
    except ET.ParseError as exc:
        raise WorkbookReadError("shared_strings_invalid", str(exc)) from exc
    return tuple(
        "".join(node.text or "" for node in item.findall(".//m:t", NS))
        for item in root.findall("m:si", NS)
    )


def _cell_value(cell: ET.Element, shared_strings: tuple[str, ...]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", NS))
    value_node = cell.find("m:v", NS)
    if value_node is None or value_node.text is None:
        return None
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError) as exc:
            raise WorkbookReadError("shared_string_index_invalid", raw) from exc
    if cell_type == "b":
        return raw == "1"
    if cell_type in {"str", "e"}:
        return raw
    if re.fullmatch(r"[-+]?\d+", raw):
        return int(raw)
    try:
        return float(raw)
    except ValueError:
        return raw


def read_workbook(
    path: Path,
    sheet_name: str = "Sheet1",
    *,
    header_overrides: tuple[HeaderOverride, ...] = (),
) -> WorkbookSnapshot:
    source = path.read_bytes()
    workbook_sha256 = hashlib.sha256(source).hexdigest().upper()
    try:
        with zipfile.ZipFile(path, "r") as archive:
            member = _sheet_path(archive, sheet_name)
            shared_strings = _shared_strings(archive)
            try:
                sheet = ET.fromstring(archive.read(member))
            except KeyError as exc:
                raise WorkbookReadError("sheet_member_missing", member) from exc
    except zipfile.BadZipFile as exc:
        raise WorkbookReadError("invalid_xlsx_zip", str(exc)) from exc
    except ET.ParseError as exc:
        raise WorkbookReadError("sheet_xml_invalid", str(exc)) from exc

    parsed_rows: dict[int, dict[int, Any]] = {}
    for row_node in sheet.findall("m:sheetData/m:row", NS):
        row_number = int(row_node.attrib["r"])
        cells: dict[int, Any] = {}
        for cell in row_node.findall("m:c", NS):
            cells[_column_index(cell.attrib["r"])] = _cell_value(
                cell, shared_strings
            )
        parsed_rows[row_number] = cells

    header_cells = dict(parsed_rows.get(1, {}))
    overridden_indices: set[int] = set()
    for override in header_overrides:
        if (
            override.expected_workbook_sha256 is not None
            and override.expected_workbook_sha256.upper() != workbook_sha256
        ):
            raise WorkbookReadError(
                "header_override_workbook_mismatch",
                f"{path}: expected {override.expected_workbook_sha256}, got {workbook_sha256}",
            )
        if not re.fullmatch(r"[A-Za-z]+1", override.cell_reference):
            raise WorkbookReadError(
                "header_override_reference_invalid", override.cell_reference
            )
        if not override.reason.strip() or not override.replacement_header.strip():
            raise WorkbookReadError(
                "header_override_invalid", override.cell_reference
            )
        index = _column_index(override.cell_reference)
        if index in overridden_indices:
            raise WorkbookReadError(
                "header_override_duplicate", override.cell_reference
            )
        actual = header_cells.get(index)
        if actual != override.expected_header:
            raise WorkbookReadError(
                "header_override_mismatch",
                f"{override.cell_reference}: expected {override.expected_header!r}, got {actual!r}",
            )
        overridden_indices.add(index)
        header_cells[index] = override.replacement_header
    headers_by_index = {
        index: str(value)
        for index, value in header_cells.items()
        if value is not None and str(value).strip()
    }
    if not headers_by_index:
        raise WorkbookReadError("header_row_missing", str(path))
    header_values = tuple(headers_by_index.values())
    if len(set(header_values)) != len(header_values):
        raise WorkbookReadError("duplicate_header", str(path))

    def values_for(row_number: int) -> dict[str, Any]:
        cells = parsed_rows.get(row_number, {})
        return {
            header: cells.get(index)
            for index, header in headers_by_index.items()
        }

    metadata_rows = tuple(values_for(row_number) for row_number in (2, 3, 4))
    rows: list[WorkbookRow] = []
    for row_number in sorted(number for number in parsed_rows if number >= 5):
        values = values_for(row_number)
        payload = _canonical_json(values)
        rows.append(
            WorkbookRow(
                row_number=row_number,
                values=values,
                canonical_json=payload,
                sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest().upper(),
            )
        )
    return WorkbookSnapshot(
        path=path,
        sha256=workbook_sha256,
        headers=header_values,
        metadata_rows=metadata_rows,
        rows=tuple(rows),
        header_overrides=header_overrides,
    )
