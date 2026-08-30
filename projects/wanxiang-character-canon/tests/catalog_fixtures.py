from __future__ import annotations

import html
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class XlsxCell:
    value: Any
    cell_type: str


def _column_name(index: int) -> str:
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _cell_xml(reference: str, value: Any, shared_indices: dict[str, int]) -> str:
    if value is None:
        return ""
    if isinstance(value, XlsxCell):
        raw = value.value
        if value.cell_type == "shared":
            return f'<c r="{reference}" t="s"><v>{shared_indices[str(raw)]}</v></c>'
        if value.cell_type == "inline":
            escaped = html.escape(str(raw), quote=False)
            return f'<c r="{reference}" t="inlineStr"><is><t>{escaped}</t></is></c>'
        if value.cell_type in {"str", "error"}:
            escaped = html.escape(str(raw), quote=False)
            marker = "str" if value.cell_type == "str" else "e"
            return f'<c r="{reference}" t="{marker}"><v>{escaped}</v></c>'
        raise ValueError(f"unsupported fixture cell type: {value.cell_type}")
    if isinstance(value, bool):
        return f'<c r="{reference}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{reference}"><v>{value}</v></c>'
    escaped = html.escape(str(value), quote=False)
    return (
        f'<c r="{reference}" t="inlineStr"><is><t>{escaped}</t></is></c>'
    )


def _row_xml(
    row_number: int,
    values: Iterable[Any],
    shared_indices: dict[str, int],
) -> str:
    cells = "".join(
        _cell_xml(f"{_column_name(index)}{row_number}", value, shared_indices)
        for index, value in enumerate(values)
    )
    return f'<row r="{row_number}">{cells}</row>'


def write_xlsx_fixture(
    path: Path,
    *,
    relationship_target: str | None,
    headers: tuple[Any, ...],
    metadata_rows: tuple[tuple[Any, ...], ...],
    data_rows: tuple[tuple[Any, ...], ...],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    all_rows = (headers, *metadata_rows, *data_rows)
    shared_values = tuple(
        dict.fromkeys(
            str(value.value)
            for row in all_rows
            for value in row
            if isinstance(value, XlsxCell) and value.cell_type == "shared"
        )
    )
    shared_indices = {value: index for index, value in enumerate(shared_values)}
    rows = [_row_xml(1, headers, shared_indices)]
    rows.extend(
        _row_xml(row_number, values, shared_indices)
        for row_number, values in enumerate(metadata_rows, start=2)
    )
    rows.extend(
        _row_xml(row_number, values, shared_indices)
        for row_number, values in enumerate(data_rows, start=5)
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows)}</sheetData>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    relationship_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    )
    if relationship_target is not None:
        relationship_xml += (
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="{html.escape(relationship_target, quote=True)}"/>'
        )
    relationship_xml += '</Relationships>'

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationship_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if shared_values:
            items = "".join(
                f'<si><t>{html.escape(value, quote=False)}</t></si>'
                for value in shared_values
            )
            archive.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"{items}</sst>",
            )
    return path
