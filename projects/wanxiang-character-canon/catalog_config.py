from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from excel_reader import HeaderOverride


RESEARCH_ROOT = Path(
    r"D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research"
)
ALL_EXCEL_ROOT = (
    RESEARCH_ROOT
    / "baseline"
    / "game"
    / "wanxiang"
    / "wanxiang"
    / "ModDocs"
    / "AllExcel"
)
RUNTIME_CANDIDATE_ROOT = (
    RESEARCH_ROOT
    / "baseline"
    / "game"
    / "wanxiang"
    / "wanxiang"
    / "WXQXZ_Data"
    / "StreamingAssets"
)
SOURCE_MANIFEST_PATH = (
    RESEARCH_ROOT
    / "evidence"
    / "source-inventory"
    / "current-verification.manifest.json"
)
SOURCE_MANIFEST_SHA256 = (
    "0B607E20ADE02510181CB5B3145AE3F0D68E6AABA16C50458A0E725EFC5C6F1F"
)
SOURCE_LAYER = "SHIPPED_MODDOCS_ALL_EXCEL"
SOURCE_AUTHORITY = "STATIC_DOCUMENTED_DATA_RUNTIME_OWNERSHIP_NOT_MEASURED"
READER_VERSION = "wanxiang-openxml/v1"

TABLE_COUNTS = {
    "Achievement": 120,
    "Assist": 199,
    "Audio": 50,
    "Battle": 308,
    "Birth": 2,
    "Buff": 10,
    "Condition": 2924,
    "Dice": 23,
    "Dictionary": 268,
    "Difficulty": 4,
    "Effect": 34,
    "Ending": 75,
    "Event": 3589,
    "EventDialog": 17210,
    "EventDice": 8,
    "EventNormal": 14,
    "EventPuzzle": 13,
    "EventResult": 1627,
    "EventSelection": 155,
    "Formula": 788,
    "Hero": 270,
    "HotKey": 14,
    "Map": 109,
    "MapInfo": 13,
    "Monster": 267,
    "News": 113,
    "PlayerPortrait": 10,
    "Point": 27,
    "Property": 121,
    "PuzzleGroup": 198,
    "Relation": 50,
    "Skill": 928,
    "SkillCondition": 44,
    "Switch": 77,
    "Talent": 85,
    "UIText": 192,
}


class CatalogContractError(ValueError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class CatalogContract:
    source_root: Path
    manifest_path: Path
    manifest_sha256: str
    table_counts: Mapping[str, int]
    runtime_candidate_root: Path
    runtime_candidate_count: int = 52
    reader_version: str = READER_VERSION

    @property
    def expected_total_rows(self) -> int:
        return sum(self.table_counts.values())

    def workbook_path(self, table: str) -> Path:
        if table not in self.table_counts:
            raise CatalogContractError("unknown_table", table)
        return self.source_root / f"{table}.xlsx"

    def manifest_member(self, table: str) -> str:
        if table not in self.table_counts:
            raise CatalogContractError("unknown_table", table)
        return f"wanxiang/ModDocs/AllExcel/{table}.xlsx"

    def header_overrides(self, table: str) -> tuple[HeaderOverride, ...]:
        if table not in self.table_counts:
            raise CatalogContractError("unknown_table", table)
        if table != "EventSelection":
            return ()
        return (
            HeaderOverride(
                cell_reference="CY1",
                expected_header="Condition9",
                replacement_header="Condition16",
                reason=(
                    "official EventSelection slot-16 header is mislabeled "
                    "as Condition9"
                ),
                expected_workbook_sha256=(
                    "663C7422DE201BD6D5E8EC2923E5798AD94CA2C59F456138FB797AEBF50C2308"
                ),
            ),
        )

    def validate_table_counts(self, observed: Mapping[str, int]) -> int:
        expected = dict(self.table_counts)
        actual = dict(observed)
        if actual != expected:
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            changed = {
                key: {"expected": expected[key], "actual": actual[key]}
                for key in sorted(expected.keys() & actual.keys())
                if expected[key] != actual[key]
            }
            raise CatalogContractError(
                "table_count_mismatch",
                f"missing={missing}, extra={extra}, changed={changed}",
            )
        return sum(actual.values())


def default_catalog_contract() -> CatalogContract:
    return CatalogContract(
        source_root=ALL_EXCEL_ROOT,
        manifest_path=SOURCE_MANIFEST_PATH,
        manifest_sha256=SOURCE_MANIFEST_SHA256,
        table_counts=dict(TABLE_COUNTS),
        runtime_candidate_root=RUNTIME_CANDIDATE_ROOT,
    )
