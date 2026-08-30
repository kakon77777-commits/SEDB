from __future__ import annotations

import html
import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class XlsxCell:
    value: Any
    cell_type: str


@dataclass(frozen=True)
class CatalogFixture:
    root: Path
    contract: Any


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


def build_catalog_fixture(
    root: Path,
    *,
    include_relation: bool = False,
) -> CatalogFixture:
    from catalog_config import CatalogContract

    source_root = root / "AllExcel"
    runtime_root = root / "StreamingAssets"
    runtime_root.mkdir(parents=True, exist_ok=True)
    books = {
        "Hero": {
            "headers": (
                "Id",
                "IdName",
                "Name",
                "Birth",
                "Type",
                "Title",
                "CardName",
                "BaseDesc",
                "Desc",
                "Level",
                "Menpai",
                "CardRare",
                "CardPath",
                "Image",
                "Hp",
                "Power",
                "SkillId0",
                "SkillId1",
                "SkillId2",
                "SkillId3",
                "IsPlayer",
                "Property0",
                "Property1",
                "Property2",
                "Property3",
                "Property4",
                "Property5",
                "Ji0",
                "JiValue0",
                "Ji1",
                "JiValue1",
                "Ji2",
                "JiValue2",
                "ParentId",
                "IsAtlas",
                "AtlasIndex",
                "GetDesc",
                "Point",
                "ExtraHeroId",
                "SkinGroupId",
                "StoryId",
                "RouteFilter",
                "Flag",
                "NameTw",
                "TitleTw",
                "DescTw",
                "GetDescTw",
                "CardNameTw",
            ),
            "rows": (
                (
                    1001, "万轻舟1", "万轻舟", 101, 0, "南天玉柱",
                    "人物卡", "基础背景", "完整人物背景", 5, "1002", 3,
                    "Roles/Card/1001", "Roles/Image/1001", 100, 20,
                    10, 11, -1, None, False,
                    1, 2, -1, None, None, None,
                    7, 70, -1, -1, None, None,
                    -1, False, -1, "取得说明", 8,
                    None, None, None, -1, True,
                    "萬輕舟", "南天玉柱", "完整人物背景繁中", "取得說明", "人物卡",
                ),
                (
                    20001, "宝物一", "宝物一", 101, 1, "宝物",
                    "宝物卡", None, "宝物描述", 1, None, 1,
                    "Roles/Card/20001", "Roles/Image/20001", None, None,
                    None, None, None, None, None,
                    None, None, None, None, None, None,
                    -1, -1, -1, -1, -1, -1,
                    -1, False, -1, None, None,
                    None, None, None, -1, True,
                    "寶物一", "寶物", "寶物描述", None, "寶物卡",
                ),
                (
                    -1, "无角色", "无角色", 101, None, None,
                    None, None, None, None, None, None,
                    None, None, None, None,
                    None, None, None, None, None,
                    -1, -1, -1, -1, -1, -1,
                    -1, -1, -1, -1, -1, -1,
                    -1, False, -1, None, None,
                    None, None, None, -1, True,
                    "無角色", None, None, None, None,
                ),
            ),
        },
        "EventDialog": {
            "headers": ("Id", "Name", "Desc", "DescTw", "NextDialogId", "NextEventId"),
            "rows": (
                (10, "万轻舟", "完整对话甲", "完整對話甲", 11, -1),
                (11, "主角", "完整对话乙", "完整對話乙", -1, 99),
            ),
        },
        "Formula": {
            "headers": ("Id", "BaseValue"),
            "rows": ((None, 5),),
        },
    }
    if include_relation:
        books["Relation"] = {
            "headers": (
                "Id",
                "Name",
                "Birth",
                "PropertyId",
                "GuidDesc0",
                "GuidDescTw0",
                "GuidEvent0",
            ),
            "rows": (
                (1, "万轻舟", 101, 20, "第一步", "第一步", "10&99"),
            ),
        }
    records = []
    table_counts = {}
    for table, spec in books.items():
        headers = spec["headers"]
        workbook = write_xlsx_fixture(
            source_root / f"{table}.xlsx",
            relationship_target="worksheets/sheet1.xml",
            headers=headers,
            metadata_rows=(
                tuple("STRING" for _ in headers),
                tuple(None for _ in headers),
                tuple(f"{header} description" for header in headers),
            ),
            data_rows=spec["rows"],
        )
        data = workbook.read_bytes()
        table_counts[table] = len(spec["rows"])
        records.append(
            {
                "sourceClass": "GAME",
                "relativePath": f"wanxiang/ModDocs/AllExcel/{table}.xlsx",
                "length": len(data),
                "lastWriteTimeUtc": "2026-08-30T00:00:00Z",
                "attributes": "Archive",
                "sha256": hashlib.sha256(data).hexdigest().upper(),
            }
        )
    manifest = root / "current-verification.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "wanxiang-source-inventory/v1",
                "roots": {"game": "fixture"},
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    contract = CatalogContract(
        source_root=source_root,
        manifest_path=manifest,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest().upper(),
        table_counts=table_counts,
        runtime_candidate_root=runtime_root,
        runtime_candidate_count=0,
    )
    return CatalogFixture(root=root, contract=contract)
