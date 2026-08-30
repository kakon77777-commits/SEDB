from __future__ import annotations

import hashlib
import os

import pytest

from catalog_fixtures import XlsxCell, write_xlsx_fixture
from excel_reader import HeaderOverride, WorkbookReadError, read_workbook


HEADERS = ("Id", "Name")
METADATA = (("INT", "STRING"), (-1, "nil"), ("编号", "名称"))
DATA = ((1, "万轻舟"),)


def test_relative_and_package_absolute_targets_decode_identically(tmp_path):
    relative = write_xlsx_fixture(
        tmp_path / "relative.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=HEADERS,
        metadata_rows=METADATA,
        data_rows=DATA,
    )
    absolute = write_xlsx_fixture(
        tmp_path / "absolute.xlsx",
        relationship_target="/xl/worksheets/sheet1.xml",
        headers=HEADERS,
        metadata_rows=METADATA,
        data_rows=DATA,
    )

    relative_book = read_workbook(relative)
    absolute_book = read_workbook(absolute)

    assert relative_book.rows == absolute_book.rows
    assert absolute_book.headers == HEADERS
    assert absolute_book.metadata_rows == (
        {"Id": "INT", "Name": "STRING"},
        {"Id": -1, "Name": "nil"},
        {"Id": "编号", "Name": "名称"},
    )
    assert absolute_book.rows[0].row_number == 5
    assert absolute_book.rows[0].values == {"Id": 1, "Name": "万轻舟"}


@pytest.mark.parametrize(
    ("target", "reason_code"),
    [
        ("../evil.xml", "relationship_path_escape"),
        ("https://example.invalid/sheet.xml", "external_target_rejected"),
        ("//server/share/sheet.xml", "external_target_rejected"),
    ],
)
def test_unsafe_relationship_target_is_rejected(tmp_path, target, reason_code):
    workbook = write_xlsx_fixture(
        tmp_path / "unsafe.xlsx",
        relationship_target=target,
        headers=HEADERS,
        metadata_rows=METADATA,
        data_rows=DATA,
    )

    with pytest.raises(WorkbookReadError) as error:
        read_workbook(workbook)

    assert error.value.reason_code == reason_code


def test_missing_relationship_is_reason_coded(tmp_path):
    workbook = write_xlsx_fixture(
        tmp_path / "missing-rel.xlsx",
        relationship_target=None,
        headers=HEADERS,
        metadata_rows=METADATA,
        data_rows=DATA,
    )

    with pytest.raises(WorkbookReadError) as error:
        read_workbook(workbook)

    assert error.value.reason_code == "sheet_relationship_missing"


def test_duplicate_header_is_rejected(tmp_path):
    workbook = write_xlsx_fixture(
        tmp_path / "duplicate-header.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=("Id", "Id"),
        metadata_rows=METADATA,
        data_rows=DATA,
    )

    with pytest.raises(WorkbookReadError) as error:
        read_workbook(workbook)

    assert error.value.reason_code == "duplicate_header"


def test_audited_header_override_preserves_both_duplicate_slots(tmp_path):
    workbook = write_xlsx_fixture(
        tmp_path / "known-header-defect.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=("Condition9", "Condition9", "Selection16"),
        metadata_rows=(
            ("STRING", "STRING", "STRING"),
            ("nil", "nil", "nil"),
            ("选项条件id", "选项条件id", "选项文本"),
        ),
        data_rows=((900, 1600, "第十七个选项"),),
    )

    snapshot = read_workbook(
        workbook,
        header_overrides=(
            HeaderOverride(
                cell_reference="B1",
                expected_header="Condition9",
                replacement_header="Condition16",
                reason="fixture mirrors EventSelection CY1 source defect",
            ),
        ),
    )

    assert snapshot.headers == ("Condition9", "Condition16", "Selection16")
    assert snapshot.rows[0].values == {
        "Condition9": 900,
        "Condition16": 1600,
        "Selection16": "第十七个选项",
    }


def test_missing_header_values_are_rejected(tmp_path):
    workbook = write_xlsx_fixture(
        tmp_path / "missing-header.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=(None, None),
        metadata_rows=METADATA,
        data_rows=DATA,
    )

    with pytest.raises(WorkbookReadError) as error:
        read_workbook(workbook)

    assert error.value.reason_code == "header_row_missing"


def test_wrong_sheet_name_is_reason_coded(tmp_path):
    workbook = write_xlsx_fixture(
        tmp_path / "wrong-sheet.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=HEADERS,
        metadata_rows=METADATA,
        data_rows=DATA,
    )

    with pytest.raises(WorkbookReadError) as error:
        read_workbook(workbook, "Missing")

    assert error.value.reason_code == "sheet_missing"


def test_supported_cell_types_decode_to_typed_values(tmp_path):
    workbook = write_xlsx_fixture(
        tmp_path / "cell-types.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=("Shared", "Inline", "Bool", "Int", "Float", "Cached", "Error", "Blank"),
        metadata_rows=(
            ("STRING", "STRING", "BOOL", "INT", "FLOAT", "STRING", "STRING", "STRING"),
            (None,) * 8,
            (None,) * 8,
        ),
        data_rows=(
            (
                XlsxCell("共享文本", "shared"),
                XlsxCell("行内文本", "inline"),
                True,
                -2,
                1.25,
                XlsxCell("缓存文本", "str"),
                XlsxCell("#N/A", "error"),
                None,
            ),
        ),
    )

    row = read_workbook(workbook).rows[0]

    assert row.values == {
        "Shared": "共享文本",
        "Inline": "行内文本",
        "Bool": True,
        "Int": -2,
        "Float": 1.25,
        "Cached": "缓存文本",
        "Error": "#N/A",
        "Blank": None,
    }
    assert "共享文本" in row.canonical_json


def test_catalog_contract_validates_exact_table_counts_and_paths():
    from catalog_config import CatalogContractError, default_catalog_contract

    contract = default_catalog_contract()
    observed = dict(contract.table_counts)

    assert contract.validate_table_counts(observed) == 29939
    assert contract.workbook_path("Hero").name == "Hero.xlsx"
    assert contract.manifest_member("Hero") == "wanxiang/ModDocs/AllExcel/Hero.xlsx"
    assert contract.runtime_candidate_count == 52
    overrides = contract.header_overrides("EventSelection")
    assert overrides == (
        HeaderOverride(
            cell_reference="CY1",
            expected_header="Condition9",
            replacement_header="Condition16",
            reason="official EventSelection slot-16 header is mislabeled as Condition9",
            expected_workbook_sha256="663C7422DE201BD6D5E8EC2923E5798AD94CA2C59F456138FB797AEBF50C2308",
        ),
    )
    assert contract.header_overrides("Hero") == ()

    observed["Event"] -= 1
    with pytest.raises(CatalogContractError) as error:
        contract.validate_table_counts(observed)
    assert error.value.reason_code == "table_count_mismatch"

    with pytest.raises(CatalogContractError) as error:
        contract.workbook_path("Unknown")
    assert error.value.reason_code == "unknown_table"


def test_header_override_can_be_bound_to_exact_workbook_hash(tmp_path):
    workbook = write_xlsx_fixture(
        tmp_path / "hash-bound.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=("Condition9", "Condition9"),
        metadata_rows=(("STRING", "STRING"), ("nil", "nil"), ("条件", "条件")),
        data_rows=((9, 16),),
    )
    override = HeaderOverride(
        cell_reference="B1",
        expected_header="Condition9",
        replacement_header="Condition16",
        reason="test exact workbook binding",
        expected_workbook_sha256="0" * 64,
    )

    with pytest.raises(WorkbookReadError) as error:
        read_workbook(workbook, header_overrides=(override,))

    assert error.value.reason_code == "header_override_workbook_mismatch"


@pytest.mark.skipif(
    os.environ.get("WANXIANG_CANON_LIVE") != "1",
    reason="set WANXIANG_CANON_LIVE=1 for real AllExcel acceptance",
)
def test_real_all_excel_reader_contract_is_exact_and_read_only():
    from catalog_config import default_catalog_contract

    contract = default_catalog_contract()

    def signature():
        return {
            path.name: (
                path.stat().st_size,
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            )
            for path in sorted(contract.source_root.glob("*.xlsx"))
        }

    before = signature()
    observed = {
        table: len(
            read_workbook(
                contract.workbook_path(table),
                header_overrides=contract.header_overrides(table),
            ).rows
        )
        for table in contract.table_counts
    }
    after = signature()

    assert contract.validate_table_counts(observed) == 29939
    assert observed["EventResult"] == 1627
    assert observed["Condition"] == 2924
    assert len(tuple(contract.runtime_candidate_root.glob("*.dat"))) == 52
    assert before == after
