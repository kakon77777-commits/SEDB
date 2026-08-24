from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]
SEDB_ROOT = PROJECT_DIR.parents[1]

for import_root in (PROJECT_DIR, SEDB_ROOT / "current" / "src"):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)


@pytest.fixture
def project_dir() -> Path:
    return PROJECT_DIR
