from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from config import ProjectConfig


ART_CHECKPOINT = "evidence/checkpoints/task-18-art-extraction-final.json"
METHODOLOGY_CHECKPOINT = "evidence/checkpoints/task-19-methodology-papers.json"

FIXTURE_COUNTS = {
    "wanxiang_build_snapshot": 1,
    "wanxiang_character_identity": 1,
    "wanxiang_character_form_snapshot": 2,
    "wanxiang_visual_asset_snapshot": 3,
    "wanxiang_visual_candidate_snapshot": 1,
    "wanxiang_source_gap_snapshot": 1,
    "wanxiang_methodology_reference": 2,
}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


@dataclass
class SnapshotFixture:
    root: Path
    config: ProjectConfig

    def path(self, relative: str) -> Path:
        return self.root / Path(relative)

    def read_json(self, relative: str) -> Any:
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def write_json(
        self,
        relative: str,
        value: Any,
        *,
        refresh_checkpoint: str | None = None,
    ) -> None:
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_json_bytes(value))
        if refresh_checkpoint is not None:
            self.refresh_checkpoint(relative, refresh_checkpoint)

    def mutate_json(
        self,
        relative: str,
        mutate: Callable[[Any], None],
        *,
        refresh_checkpoint: str | None = None,
    ) -> None:
        value = self.read_json(relative)
        mutate(value)
        self.write_json(
            relative,
            value,
            refresh_checkpoint=refresh_checkpoint,
        )

    def refresh_checkpoint(self, relative: str, checkpoint: str) -> None:
        manifest = self.read_json(checkpoint)
        record = next(item for item in manifest["files"] if item["path"] == relative)
        target = self.path(relative)
        record["length"] = target.stat().st_size
        record["sha256"] = _hash(target)
        self.write_json(checkpoint, manifest)


def build_snapshot_fixture(
    root: Path,
    *,
    catalog_compatible: bool = False,
) -> SnapshotFixture:
    fixture = SnapshotFixture(
        root=root,
        config=ProjectConfig(
            source_root=root,
            database_path=root / "fixture.sqlite",
            expected_entity_counts=FIXTURE_COUNTS,
        ),
    )

    heroes = [
        {
            "birth": 101,
            "expectedCardPath": "Roles/Card/1001",
            "expectedImagePath": "Roles/Image/1001",
            "extraHeroId": None,
            "id": 1001,
            "idName": "万轻舟1" if catalog_compatible else "万轻舟",
            "menpai": "1002",
            "name": "万轻舟",
            "nameTw": "萬輕舟",
            "parentId": -1 if catalog_compatible else 0,
            "skinGroupId": None,
            "sourceRow": 5 if catalog_compatible else 7,
            "storyId": None,
            "title": "南天玉柱",
            "titleTw": "南天玉柱",
            "type": 0,
            "variantCount": 2,
            "variantIndex": 0,
        },
        {
            "birth": 101,
            "expectedCardPath": "Roles/Card/1002",
            "expectedImagePath": "Roles/Image/1002",
            "extraHeroId": None,
            "id": 1002,
            "idName": "万轻舟1",
            "menpai": "1002",
            "name": "万轻舟",
            "nameTw": "萬輕舟",
            "parentId": -1,
            "skinGroupId": None,
            "sourceRow": 26,
            "storyId": None,
            "title": "南天玉柱",
            "titleTw": "南天玉柱",
            "type": 0,
            "variantCount": 2,
            "variantIndex": 1,
        },
    ]
    stats = {
        "duplicateNameGroups": 1,
        "heroRows": 2,
        "mappedImagePaths": 1,
        "uniqueNames": 1,
    }
    role_targets = {
        "duplicateNameGroups": [{"ids": [1001, 1002], "name": "万轻舟"}],
        "heroes": heroes,
        "schema": "wanxiang-role-targets/v1",
        "stats": stats,
    }
    characters = {
        "characters": [
            {**hero, "assets": {}}
            for hero in heroes
        ],
        "schema": "wanxiang-character-registry/v1",
        "stats": stats,
    }
    image_objects = [
        {
            "containerPaths": ["roles/image/1001"],
            "height": 1280,
            "name": "1001",
            "parseStatus": "PARSED",
            "pathId": 10,
            "sourceFile": "resources.assets",
            "streamData": None,
            "textureFormat": None,
            "type": "Sprite",
            "width": 1280,
        },
        {
            "containerPaths": ["roles/card/1001"],
            "height": 340,
            "name": "1001",
            "parseStatus": "PARSED",
            "pathId": 20,
            "sourceFile": "resources.assets",
            "streamData": None,
            "textureFormat": None,
            "type": "Sprite",
            "width": 232,
        },
        {
            "containerPaths": ["roles/assist/9999"],
            "height": 80,
            "name": "9999",
            "parseStatus": "PARSED",
            "pathId": 40,
            "sourceFile": "resources.assets",
            "streamData": None,
            "textureFormat": None,
            "type": "Sprite",
            "width": 71,
        },
    ]
    unity_index = {
        "containerFailureCount": 0,
        "containerFailures": [],
        "failures": [],
        "imageObjectCount": 3,
        "imageObjects": image_objects,
        "objectCount": 3,
        "parseFailureCount": 0,
        "resourcePathCount": 3,
        "schema": "wanxiang-unity-object-index/v1",
        "serializedFiles": ["resources.assets"],
        "status": "INVENTORY_PASS",
        "typeCounts": {"Sprite": 3},
        "unityPyVersion": "fixture",
    }

    exact_image = {
        "containerPaths": ["roles/image/1001"],
        "evidence": "EXACT_CONTAINER_PATH",
        "height": 1280,
        "name": "1001",
        "pathId": 10,
        "sourceFile": "resources.assets",
        "type": "Sprite",
        "width": 1280,
    }
    exact_card = {
        "containerPaths": ["roles/card/1001"],
        "evidence": "EXACT_CONTAINER_PATH",
        "height": 340,
        "name": "1001",
        "pathId": 20,
        "sourceFile": "resources.assets",
        "type": "Sprite",
        "width": 232,
    }
    ambiguous = {
        "containerPaths": [],
        "evidence": "UNIQUE_ID_CANDIDATE",
        "height": 1280,
        "name": "1002",
        "pathId": 30,
        "sourceFile": "resources.assets",
        "type": "Sprite",
        "width": 1280,
    }
    mappings = [
        {
            "candidates": [exact_image],
            "class": "Image",
            "expectedPath": "Roles/Image/1001",
            "heroIdKnown": True,
            "id": 1001,
            "status": "EXACT_CONTAINER_PATH",
        },
        {
            "candidates": [exact_card],
            "class": "Card",
            "expectedPath": "Roles/Card/1001",
            "heroIdKnown": True,
            "id": 1001,
            "status": "EXACT_CONTAINER_PATH",
        },
        {
            "candidates": [ambiguous],
            "class": "Image",
            "expectedPath": "Roles/Image/1002",
            "heroIdKnown": True,
            "id": 1002,
            "status": "AMBIGUOUS",
        },
    ]
    mapping_candidates = {
        "counts": [
            {"class": "Image", "count": 1, "status": "AMBIGUOUS"},
            {"class": "Image", "count": 1, "status": "EXACT_CONTAINER_PATH"},
            {"class": "Card", "count": 1, "status": "EXACT_CONTAINER_PATH"},
        ],
        "mappingCount": 3,
        "mappings": mappings,
        "schema": "wanxiang-role-mapping/v1",
    }

    files = [
        {
            "alphaExtrema": [0, 255],
            "height": 1280,
            "length": 100,
            "mode": "RGBA",
            "path": "Roles/Image/1001.png",
            "sha256": "A" * 64,
            "width": 1280,
        },
        {
            "alphaExtrema": [0, 255],
            "height": 340,
            "length": 200,
            "mode": "RGBA",
            "path": "Roles/Card/1001.png",
            "sha256": "B" * 64,
            "width": 232,
        },
        {
            "alphaExtrema": [0, 255],
            "height": 1280,
            "length": 300,
            "mode": "RGBA",
            "path": "ambiguous/Image/1002/resources.assets__30__Sprite.png",
            "sha256": "C" * 64,
            "width": 1280,
        },
    ]
    output_manifest = {
        "fileCount": 3,
        "files": files,
        "schema": "wanxiang-role-art-output-manifest/v1",
        "totalBytes": 600,
    }
    extraction_result = {
        "outputBytes": 600,
        "schema": "wanxiang-role-extraction/v1",
        "targets": [
            {
                **{key: value for key, value in files[0].items() if key != "path"},
                "class": "Image",
                "heroIdKnown": True,
                "id": 1001,
                "mappingStatus": "EXACT_CONTAINER_PATH",
                "outputPath": files[0]["path"],
                "pathId": 10,
                "selectedType": "Sprite",
                "sourceFile": "resources.assets",
                "status": "EXTRACTED",
            },
            {
                **{key: value for key, value in files[1].items() if key != "path"},
                "class": "Card",
                "heroIdKnown": True,
                "id": 1001,
                "mappingStatus": "EXACT_CONTAINER_PATH",
                "outputPath": files[1]["path"],
                "pathId": 20,
                "selectedType": "Sprite",
                "sourceFile": "resources.assets",
                "status": "EXTRACTED",
            },
            {
                "candidateFailures": [],
                "class": "Image",
                "decodedCandidates": 1,
                "heroIdKnown": True,
                "id": 1002,
                "mappingStatus": "AMBIGUOUS",
                "status": "AMBIGUOUS",
            },
        ],
    }
    source_roots = {
        "schema": "wanxiang-source-roots/v1",
        "observedDate": "2026-08-30",
        "game": {
            "name": "万象群侠传",
            "steamAppId": 3039500,
            "buildId": 25006280,
            "depotId": 3039501,
            "depotManifest": "6780482257387102359",
            "installDir": "wanxiang",
            "sourceRoot": r"D:\SteamLibrary\steamapps\common\wanxiang",
            "unityRoot": r"D:\SteamLibrary\steamapps\common\wanxiang\wanxiang",
            "authority": "STEAM_INSTALL_READ_ONLY",
        },
        "runtime": {
            "gameProcessObservedRunning": False,
            "foregroundAuthorized": False,
            "status": "GAME_RUNTIME_NOT_MEASURED",
        },
    }

    art_values = {
        "art-engineering/inventory/build-25006280/role-targets.json": role_targets,
        "art-engineering/registry/characters.json": characters,
        "art-engineering/inventory/build-25006280/unity-object-index.json": unity_index,
        "art-engineering/inventory/build-25006280/mapping-candidates.json": mapping_candidates,
        "art-engineering/evidence/extraction-result.json": extraction_result,
        "art-engineering/evidence/extraction-output-manifest.json": output_manifest,
    }
    fixture.write_json("evidence/source-inventory/source-roots.json", source_roots)
    for relative, value in art_values.items():
        fixture.write_json(relative, value)
    fixture.write_json(
        ART_CHECKPOINT,
        {
            "schema": "non-git-checkpoint/v1",
            "files": [
                {
                    "path": relative,
                    "length": fixture.path(relative).stat().st_size,
                    "sha256": _hash(fixture.path(relative)),
                }
                for relative in sorted(art_values)
            ],
        },
    )

    methodology = [
        (
            "inputs/methodology-papers/2026-08-30/"
            "exposure-tension-decoupling-v0.1/documents",
            "Exposure_Tension_Decoupling_SFW_Sensuality_Control_Internal_v0.1.md",
            "Exposure–Tension Decoupling / SFW Sensuality Control",
            "v0.1",
        ),
        (
            "inputs/methodology-papers/2026-08-30/"
            "heluo-character-art-methodology-v0.1/documents",
            "Heluo_Character_Art_Methodology_Internal_Paper_v0.1.md",
            "Heluo Character Art Methodology",
            "v0.1",
        ),
    ]
    methodology_paths: list[str] = []
    for directory, filename, title, version in methodology:
        paper_relative = f"{directory}/{filename}"
        manifest_relative = f"{directory}/VALIDATION_MANIFEST.json"
        paper_path = fixture.path(paper_relative)
        paper_path.parent.mkdir(parents=True, exist_ok=True)
        paper_path.write_text(f"# {title}\n\nFixture paper.\n", encoding="utf-8")
        fixture.write_json(
            manifest_relative,
            {
                "title": title,
                "version": version,
                "file": filename,
                "encoding": "UTF-8",
                "newline": "LF",
                "sha256": _hash(paper_path).lower(),
                "validation": "PASS",
            },
        )
        methodology_paths.extend([paper_relative, manifest_relative])
    fixture.write_json(
        METHODOLOGY_CHECKPOINT,
        {
            "schema": "non-git-checkpoint/v1",
            "files": [
                {
                    "path": relative,
                    "length": fixture.path(relative).stat().st_size,
                    "sha256": _hash(fixture.path(relative)),
                }
                for relative in sorted(methodology_paths)
            ],
        },
    )
    return fixture
