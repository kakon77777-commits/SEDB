from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SOURCE_ROOT = Path(
    r"D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research"
)
BUILD_ID = 25006280
NAMESPACE = "wanxiang_character_canon"
DATABASE_NAME = "wanxiang-character-canon.sqlite"

ENTITY_COUNTS = {
    "wanxiang_build_snapshot": 1,
    "wanxiang_character_identity": 165,
    "wanxiang_character_form_snapshot": 228,
    "wanxiang_visual_asset_snapshot": 1391,
    "wanxiang_visual_candidate_snapshot": 172,
    "wanxiang_source_gap_snapshot": 8,
    "wanxiang_methodology_reference": 2,
}
TOTAL_ENTITY_COUNT = sum(ENTITY_COUNTS.values())


@dataclass(frozen=True)
class ProjectConfig:
    source_root: Path = SOURCE_ROOT
    database_path: Path = Path(__file__).resolve().parent / DATABASE_NAME
    build_id: int = BUILD_ID
    namespace: str = NAMESPACE


def default_config() -> ProjectConfig:
    return ProjectConfig()
