# Unbounded Axiom Corpus SEDB Month-Split MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, month-split SEDB consumer that imports Unbounded Axiom registry metadata into one cumulative local SQLite database without silently changing existing paper identities or values.

**Architecture:** A thin project under `SEDB/projects/unbounded-axiom-corpus` separates configuration, source validation, SEDB storage/difference planning, and CLI presentation. The importer reads `unbounded-axiom/registry/papers.json` directly, preflights the complete target month, blocks the whole batch on unresolved differences, and creates all new paper entities/cells in one SQLite transaction.

**Tech Stack:** Python 3.11+ standard library, SQLite through SEDB v0.4B, `pytest`, Windows PowerShell, Git.

**Spec:** `docs/superpowers/specs/2026-08-26-unbounded-axiom-corpus-sedb-mvp-design.md`

## Global Constraints

- Work directly on `D:\Ai\work together\SEDB` `main`; do not create a worktree or feature branch.
- Create the project only at `D:\Ai\work together\SEDB\projects\unbounded-axiom-corpus`.
- Read metadata only from `D:\Ai\work together\unbounded-axiom\registry\papers.json`.
- Keep the dependency one-way: the new SEDB project reads Unbounded Axiom; Unbounded Axiom receives no SEDB files or imports.
- Do not modify `SEDB/current/`; consume its v0.4B source through `PYTHONPATH=current\src`.
- Preserve all existing unrelated changes and untracked files, including `docs/BRIEF_unbounded_axiom_corpus_sedb_2026-08-25.md` and `projects/amral-ns-symbols/`.
- Do not read paper bodies, scan the corpus filesystem, recompute paper hashes, call AI providers, or infer research relationships.
- Do not add CTCL, copy, translation, deployment, publication, release, merge, or remote-write behavior.
- Use one cumulative SQLite database; paper identity is the global `lm-NNNNNN` ID, never `(month, id)`.
- Treat JSON null/missing values as blank-by-absence; never synthesize `unknown`, `N/A`, zero, or an empty cell.
- Compare only the 11 MVP-owned fields; future AI-governed fields must not affect bootstrap equality.
- Any `conflict` or `missing_from_source` blocks all new paper writes in that invocation.
- A syntactically valid month with zero papers is `target_month_empty`, exit code `2`, not a successful no-op.
- Schema mismatch is `schema_conflict`, exit code `3`, and never overwrites the existing field or Task View.
- Successful paper creation is one SQLite transaction; an injected or real failure rolls back the complete batch.
- Generated SQLite/WAL/SHM files and caches remain Git-ignored.
- Commit only the exact files listed by each task.

---

## File Structure

Create these files:

```text
projects/unbounded-axiom-corpus/
  .gitignore                   SQLite/cache exclusions
  README.md                    operator commands and authority boundary
  config.py                    paths, field contracts, entity/view constants
  source.py                    registry validation and month selection
  store.py                     SEDB schema, diff, atomic apply, statistics
  cli.py                       argparse, JSON output, exit-code mapping
  tests/
    conftest.py                import roots and shared fixtures
    test_source.py             registry/month validation
    test_store.py              schema, diff, transaction, sparse behavior
    test_cli.py                JSON and exit-code contract
    test_live_acceptance.py    opt-in real-registry acceptance
```

`config.py` owns static contracts. `source.py` never opens SQLite. `store.py`
never parses command-line arguments. `cli.py` contains no raw SQL. Tests import
the modules through the project directory and SEDB `current/src`.

---

### Task 1: Project Foundation and Registry Source Contract

**Files:**
- Create: `projects/unbounded-axiom-corpus/.gitignore`
- Create: `projects/unbounded-axiom-corpus/config.py`
- Create: `projects/unbounded-axiom-corpus/source.py`
- Create: `projects/unbounded-axiom-corpus/tests/conftest.py`
- Create: `projects/unbounded-axiom-corpus/tests/test_source.py`

**Interfaces:**
- Consumes: Python standard library and `registry/papers.json` shape `{version,count,items}`.
- Produces: `FieldSpec`, `ProjectConfig`, `default_config()`, `SourceValidationError`, `PaperRecord`, `RegistrySelection`, `validate_month()`, and `load_month()`.

- [ ] **Step 1: Write the test fixtures and failing source-contract tests**

Create `tests/conftest.py` with exact import ordering and fixture helpers:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
SEDB_ROOT = PROJECT_DIR.parents[1]
for import_root in (PROJECT_DIR, SEDB_ROOT / "current" / "src"):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)


def paper(item_id: str, month: str = "2026-04", **overrides):
    result = {
        "id": item_id,
        "title": f"Paper {item_id}",
        "source_file": f"content/papers/2026/{month}/Paper-{item_id}.md",
        "language": "zh-Hant",
        "created": "2026-04-01",
        "year": 2026,
        "month": month,
        "hash": "sha256:" + ("a" * 64),
        "canonical_url": f"/p/{item_id}/",
        "date_confidence": "explicit",
        "date_basis": "git-first-add (publication/upload date; not the author's in-text writing date)",
    }
    result.update(overrides)
    return result


@pytest.fixture
def write_registry(tmp_path: Path):
    def write(items, *, version="0.2", count=None):
        path = tmp_path / "papers.json"
        path.write_text(
            json.dumps(
                {"version": version, "count": len(items) if count is None else count, "items": items},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path
    return write
```

Create `tests/test_source.py` with focused cases:

```python
import pytest

from conftest import paper
from source import SourceValidationError, load_month, validate_month


def test_load_month_normalizes_owned_values(write_registry):
    path = write_registry([paper("lm-000001", created=None)])
    selected = load_month(path, "2026-04")
    assert selected.registry_version == "0.2"
    assert selected.registry_count == 1
    assert selected.papers[0].paper_id == "lm-000001"
    assert selected.papers[0].values["year"] == "2026"
    assert "created_date" not in selected.papers[0].values


def test_valid_but_empty_month_is_an_error(write_registry):
    path = write_registry([paper("lm-000001")])
    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-09")
    assert exc.value.reason_code == "target_month_empty"


@pytest.mark.parametrize("month", ["2026-4", "2026-00", "2026-13", "April", ""])
def test_invalid_month_is_rejected(month):
    with pytest.raises(SourceValidationError) as exc:
        validate_month(month)
    assert exc.value.reason_code == "invalid_month"


def test_registry_count_must_match_items(write_registry):
    path = write_registry([paper("lm-000001")], count=2)
    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-04")
    assert exc.value.reason_code == "registry_count_mismatch"


def test_global_duplicate_id_is_rejected_even_outside_target_month(write_registry):
    path = write_registry([
        paper("lm-000001", month="2026-04"),
        paper("lm-000001", month="2026-05"),
    ])
    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-04")
    assert exc.value.reason_code == "duplicate_paper_id"


def test_invalid_registry_hash_is_rejected(write_registry):
    path = write_registry([paper("lm-000001", hash="not-a-sha")])
    with pytest.raises(SourceValidationError) as exc:
        load_month(path, "2026-04")
    assert exc.value.reason_code == "invalid_paper_hash"


def test_optional_date_provenance_is_blank_by_absence(write_registry):
    path = write_registry([
        paper("lm-000001", created=None, date_confidence=None, date_basis=None)
    ])
    record = load_month(path, "2026-04").papers[0]
    assert set(record.values) == {
        "paper_id", "title", "source_file", "language", "year", "month", "sha256", "canonical_url"
    }
```

- [ ] **Step 2: Run the source tests and verify RED**

Run:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_source.py
```

Expected: collection fails because `source.py` does not exist.

- [ ] **Step 3: Implement the static project contract**

Create `.gitignore`:

```gitignore
*.sqlite
*.sqlite3
*.sqlite-wal
*.sqlite-shm
__pycache__/
.pytest_cache/
```

Create `config.py` with these exact public types and constants:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FieldSpec:
    source_key: str
    key: str
    label: str
    description: str
    optional: bool = False
    value_type: str = "text"


FIELD_SPECS = (
    FieldSpec("id", "paper_id", "Paper ID", "Permanent Logic Matrix paper ID."),
    FieldSpec("title", "title", "Title", "Paper title recorded by the Unbounded Axiom registry."),
    FieldSpec("source_file", "source_file", "Source file", "Canonical source path recorded by the Unbounded Axiom registry."),
    FieldSpec("language", "language", "Language", "Paper language tag recorded by the Unbounded Axiom registry."),
    FieldSpec("created", "created_date", "Created date", "Publication or upload date recorded by the registry when present.", optional=True),
    FieldSpec("year", "year", "Year", "Registry year represented as canonical text."),
    FieldSpec("month", "month", "Month", "Registry publication month and bootstrap partition key."),
    FieldSpec("hash", "sha256", "SHA-256", "Registry SHA-256 identity string preserved verbatim."),
    FieldSpec("canonical_url", "canonical_url", "Canonical URL", "Permanent public paper route recorded by the registry."),
    FieldSpec("date_confidence", "date_confidence", "Date confidence", "Registry confidence class for the recorded date.", optional=True),
    FieldSpec("date_basis", "date_basis", "Date basis", "Registry provenance statement explaining the recorded date basis.", optional=True),
)

NAMESPACE = "unbounded_axiom"
ENTITY_KIND = "unbounded_axiom_paper"
TASK_VIEW_NAME = "Unbounded Axiom Paper Metadata"
CELL_SOURCE = "unbounded-axiom:registry/papers.json"


@dataclass(frozen=True)
class ProjectConfig:
    source_registry: Path
    database_path: Path
    namespace: str = NAMESPACE
    entity_kind: str = ENTITY_KIND
    task_view_name: str = TASK_VIEW_NAME


def default_config() -> ProjectConfig:
    project_dir = Path(__file__).resolve().parent
    return ProjectConfig(
        source_registry=Path(r"D:\Ai\work together\unbounded-axiom\registry\papers.json"),
        database_path=project_dir / "unbounded-axiom-corpus.sqlite",
    )
```

- [ ] **Step 4: Implement strict source validation and normalization**

Create `source.py` with these exact types and functions:

```python
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
    def __init__(self, reason_code: str, message: str, details: list[dict] | None = None):
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
    if value is None or isinstance(value, (dict, list, bool)) or not str(value).strip():
        raise SourceValidationError(
            "invalid_paper_field",
            f"paper {paper_id} has invalid required field {key}",
            [{"paper_id": paper_id, "field": key}],
        )
    return str(value)


def _record(item: dict[str, Any], month: str) -> PaperRecord:
    paper_id = _required_text(item, "id", "unresolved")
    if not PAPER_ID_RE.fullmatch(paper_id):
        raise SourceValidationError("invalid_paper_id", f"invalid paper id: {paper_id}")
    if item.get("month") != month:
        raise SourceValidationError("paper_month_mismatch", f"paper {paper_id} month mismatch")
    if not SHA256_RE.fullmatch(str(item.get("hash", ""))):
        raise SourceValidationError("invalid_paper_hash", f"paper {paper_id} has invalid hash")
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
                f"paper {paper_id} field {spec.source_key} is not scalar text-compatible",
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
        raise SourceValidationError("invalid_registry", "registry root must be an object")
    if payload.get("version") != "0.2":
        raise SourceValidationError("unsupported_registry_version", "registry version must be 0.2")
    items = payload.get("items")
    count = payload.get("count")
    if not isinstance(items, list) or not isinstance(count, int):
        raise SourceValidationError("invalid_registry", "registry count/items shape is invalid")
    if count != len(items):
        raise SourceValidationError("registry_count_mismatch", "registry count does not match items")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise SourceValidationError("invalid_registry_item", "registry item must be an object")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not PAPER_ID_RE.fullmatch(item_id):
            raise SourceValidationError("invalid_paper_id", f"invalid paper id: {item_id!r}")
        if item_id in seen:
            raise SourceValidationError("duplicate_paper_id", f"duplicate paper id: {item_id}")
        seen.add(item_id)
    selected_items = [item for item in items if item.get("month") == month]
    if not selected_items:
        raise SourceValidationError("target_month_empty", f"month {month} contains zero papers")
    papers = tuple(sorted((_record(item, month) for item in selected_items), key=lambda item: item.paper_id))
    return RegistrySelection(str(payload["version"]), count, month, papers)
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_source.py
python -m compileall -q projects/unbounded-axiom-corpus/config.py projects/unbounded-axiom-corpus/source.py
```

Expected: all source tests pass; compilation is silent.

- [ ] **Step 6: Commit the source contract**

```powershell
git add -- projects/unbounded-axiom-corpus/.gitignore projects/unbounded-axiom-corpus/config.py projects/unbounded-axiom-corpus/source.py projects/unbounded-axiom-corpus/tests/conftest.py projects/unbounded-axiom-corpus/tests/test_source.py
git commit -m "feat: add Unbounded Axiom registry source contract"
```

---

### Task 2: Idempotent SEDB Schema, Task View, and Statistics

**Files:**
- Create: `projects/unbounded-axiom-corpus/store.py`
- Create: `projects/unbounded-axiom-corpus/tests/test_store.py`

**Interfaces:**
- Consumes: `ProjectConfig`, `FIELD_SPECS`, SEDB `Database`, `FieldService`, `EntityService`, and `ViewService`.
- Produces: `SchemaConflictError`, `StorageError`, `InitResult`, `CorpusStore.open()`, `CorpusStore.ensure_schema()`, `CorpusStore.integrity_check()`, and `CorpusStore.stats()`.

- [ ] **Step 1: Write failing schema and statistics tests**

Start `tests/test_store.py` with:

```python
import pytest

from config import FIELD_SPECS, ProjectConfig, TASK_VIEW_NAME
from sedb.db import Database
from sedb.fields import FieldService
from sedb.views import ViewService
from store import CorpusStore, SchemaConflictError


def cfg(tmp_path):
    return ProjectConfig(tmp_path / "papers.json", tmp_path / "corpus.sqlite")


def test_init_is_idempotent_and_creates_exact_view(tmp_path):
    store = CorpusStore.open(cfg(tmp_path))
    first = store.ensure_schema()
    second = store.ensure_schema()
    assert first.fields_created == 11
    assert first.view_created is True
    assert second.fields_created == 0
    assert second.fields_reused == 11
    assert second.view_created is False
    views = ViewService(store.db).list_views()
    assert [view["name"] for view in views] == [TASK_VIEW_NAME]
    view = ViewService(store.db).get_view(views[0]["id"])
    assert [field["key"] for field in view["fields"]] == [spec.key for spec in FIELD_SPECS]


def test_field_schema_conflict_does_not_overwrite_or_create_other_fields(tmp_path):
    config = cfg(tmp_path)
    db = Database(config.database_path)
    existing = FieldService(db).create_field(
        key="paper_id", label="Wrong", value_type="integer", description="Wrong", namespace="other"
    )
    with pytest.raises(SchemaConflictError) as exc:
        CorpusStore.open(config).ensure_schema()
    assert exc.value.reason_code == "schema_conflict"
    loaded = FieldService(db).get_field(existing["id"])
    assert loaded["label"] == "Wrong"
    assert loaded["value_type"] == "integer"
    assert len(FieldService(db).list_fields(limit=10000)) == 1


def test_normalized_key_collision_is_schema_conflict(tmp_path):
    config = cfg(tmp_path)
    db = Database(config.database_path)
    existing = FieldService(db).create_field(
        key="paper-id", label="Legacy paper id", namespace=config.namespace
    )
    with pytest.raises(SchemaConflictError) as exc:
        CorpusStore.open(config).ensure_schema()
    assert exc.value.details[0]["reason"] == "normalized_key_collision"
    assert FieldService(db).get_field(existing["id"])["key"] == "paper-id"
    assert len(FieldService(db).list_fields(limit=10000)) == 1


def test_task_view_schema_conflict_does_not_create_owned_fields(tmp_path):
    config = cfg(tmp_path)
    db = Database(config.database_path)
    FieldService(db).create_field(key="foreign", label="Foreign")
    ViewService(db).create_view(TASK_VIEW_NAME, ["foreign"])
    with pytest.raises(SchemaConflictError):
        CorpusStore.open(config).ensure_schema()
    assert [field["key"] for field in FieldService(db).list_fields(limit=10000)] == ["foreign"]


def test_empty_stats_are_sparse_and_integrity_is_ok(tmp_path):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    stats = store.stats()
    assert stats["fields"] == 11
    assert stats["paper_entities"] == 0
    assert stats["cells"] == 0
    assert stats["density"] == 0.0
    assert stats["integrity"] == "ok"
```

- [ ] **Step 2: Run schema tests and verify RED**

Run:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_store.py
```

Expected: collection fails because `store.py` does not exist.

- [ ] **Step 3: Implement storage errors, initialization, and exact schema preflight**

Create the first part of `store.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import FIELD_SPECS, ProjectConfig
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


class SchemaConflictError(RuntimeError):
    reason_code = "schema_conflict"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.details = details or []


class StorageError(RuntimeError):
    def __init__(self, reason_code: str, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or []


@dataclass(frozen=True)
class InitResult:
    fields_created: int
    fields_reused: int
    view_created: bool
    integrity: str


class CorpusStore:
    def __init__(self, config: ProjectConfig, db: Database):
        self.config = config
        self.db = db
        self.fields = FieldService(db)
        self.entities = EntityService(db)
        self.views = ViewService(db)

    @classmethod
    def open(cls, config: ProjectConfig) -> "CorpusStore":
        return cls(config, Database(config.database_path))

    def integrity_check(self) -> str:
        result = str(self.db.scalar("PRAGMA integrity_check"))
        if result != "ok":
            raise StorageError("integrity_failure", f"SQLite integrity check failed: {result}")
        return result

    def _schema_preflight(self) -> tuple[list, bool]:
        rows = self.fields.list_fields(limit=10000)
        existing = {row["key"]: row for row in rows}
        normalized = {
            (row.get("namespace", "global"), row.get("normalized_key")): row
            for row in rows
        }
        missing = []
        conflicts = []
        for spec in FIELD_SPECS:
            row = existing.get(spec.key)
            identity_row = normalized.get((self.config.namespace, spec.key))
            if row is None and identity_row is not None:
                conflicts.append({
                    "field": spec.key,
                    "reason": "normalized_key_collision",
                    "expected_key": spec.key,
                    "actual_key": identity_row["key"],
                })
                continue
            if row is None:
                missing.append(spec)
                continue
            expected = {
                "namespace": self.config.namespace,
                "normalized_key": spec.key,
                "label": spec.label,
                "value_type": spec.value_type,
                "description": spec.description,
                "status": "active",
            }
            actual = {key: row.get(key) for key in expected}
            if actual != expected:
                conflicts.append({"field": spec.key, "expected": expected, "actual": actual})
        matching_views = [view for view in self.views.list_views() if view["name"] == self.config.task_view_name]
        if len(matching_views) > 1:
            conflicts.append({"view": self.config.task_view_name, "reason": "duplicate_view_name"})
        elif matching_views:
            view = self.views.get_view(matching_views[0]["id"])
            actual_keys = [field["key"] for field in view["fields"]]
            expected_keys = [spec.key for spec in FIELD_SPECS]
            if actual_keys != expected_keys:
                conflicts.append({"view": self.config.task_view_name, "expected": expected_keys, "actual": actual_keys})
        if conflicts:
            raise SchemaConflictError("SEDB schema conflicts with the MVP contract", conflicts)
        return missing, not matching_views

    def ensure_schema(self) -> InitResult:
        missing, view_missing = self._schema_preflight()
        if missing:
            self.fields.bulk_create_fields([
                {
                    "key": spec.key,
                    "label": spec.label,
                    "value_type": spec.value_type,
                    "description": spec.description,
                    "status": "active",
                    "namespace": self.config.namespace,
                }
                for spec in missing
            ])
        if view_missing:
            self.views.create_view(self.config.task_view_name, [spec.key for spec in FIELD_SPECS])
        return InitResult(len(missing), len(FIELD_SPECS) - len(missing), view_missing, self.integrity_check())
```

- [ ] **Step 4: Implement statistics without source reads**

Add `CorpusStore.stats()`:

```python
    def stats(self) -> dict[str, Any]:
        base = self.views.stats()
        with self.db.connect() as conn:
            paper_entities = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE kind=?", (self.config.entity_kind,)
            ).fetchone()[0]
            month_rows = conn.execute(
                """
                SELECT json_extract(c.value_json, '$') AS month, COUNT(*) AS count
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                JOIN entities e ON e.id=c.entity_id
                WHERE e.kind=? AND f.key='month' AND f.namespace=?
                GROUP BY month ORDER BY month
                """,
                (self.config.entity_kind, self.config.namespace),
            ).fetchall()
        return {
            **base,
            "paper_entities": paper_entities,
            "by_month": {row["month"]: row["count"] for row in month_rows},
            "integrity": self.integrity_check(),
        }
```

- [ ] **Step 5: Run schema tests and verify GREEN**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_store.py
python -m compileall -q projects/unbounded-axiom-corpus/store.py
```

Expected: all schema/statistics tests pass.

- [ ] **Step 6: Commit the SEDB schema boundary**

```powershell
git add -- projects/unbounded-axiom-corpus/store.py projects/unbounded-axiom-corpus/tests/test_store.py
git commit -m "feat: initialize Unbounded Axiom SEDB schema"
```

---

### Task 3: Deterministic Difference Planning and Whole-Batch Gate

**Files:**
- Modify: `projects/unbounded-axiom-corpus/store.py`
- Modify: `projects/unbounded-axiom-corpus/tests/test_store.py`

**Interfaces:**
- Consumes: `RegistrySelection` and `PaperRecord` from Task 1, initialized schema from Task 2.
- Produces: `MISSING`, `FieldDifference`, `RecordConflict`, `MissingSourceRecord`, `DiffPlan`, and `CorpusStore.plan(selection)`.

- [ ] **Step 1: Write failing difference tests**

Append tests that build selections through `load_month()` and seed controlled
SEDB state:

```python
from conftest import paper
from config import CELL_SOURCE, FIELD_SPECS
from source import load_month


def selection(write_registry, items, month="2026-04"):
    return load_month(write_registry(items), month)


def seed_paper(store, record):
    entity = store.entities.create_entity(
        entity_id=record.paper_id, label=record.label, kind=store.config.entity_kind
    )
    for key, value in record.values.items():
        store.entities.set_cell(entity["id"], key, value, source=CELL_SOURCE)


def test_new_and_unchanged_are_deterministic(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(write_registry, [paper("lm-000001"), paper("lm-000002")])
    first = store.plan(selected)
    assert [item.paper_id for item in first.new] == ["lm-000001", "lm-000002"]
    seed_paper(store, selected.papers[0])
    second = store.plan(selected)
    assert [item.paper_id for item in second.new] == ["lm-000002"]
    assert second.unchanged == ("lm-000001",)


def test_conflict_and_new_block_the_plan(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    original = selection(write_registry, [paper("lm-000001", title="Old")])
    seed_paper(store, original.papers[0])
    changed = selection(write_registry, [
        paper("lm-000001", title="New", hash="sha256:" + "b" * 64),
        paper("lm-000002"),
    ])
    plan = store.plan(changed)
    assert plan.blocked is True
    assert [item.paper_id for item in plan.new] == ["lm-000002"]
    assert plan.conflicts[0].paper_id == "lm-000001"
    assert {diff.field for diff in plan.conflicts[0].differences} == {"entity.label", "title", "sha256"}


def test_missing_from_source_blocks_new_records(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    original = selection(write_registry, [paper("lm-000001")])
    seed_paper(store, original.papers[0])
    current = selection(write_registry, [paper("lm-000002")])
    plan = store.plan(current)
    assert plan.blocked is True
    assert [item.paper_id for item in plan.new] == ["lm-000002"]
    assert [item.paper_id for item in plan.missing_from_source] == ["lm-000001"]


def test_month_reassignment_is_global_identity_conflict(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    april = selection(write_registry, [paper("lm-000001", month="2026-04")], "2026-04")
    seed_paper(store, april.papers[0])
    may = selection(write_registry, [paper("lm-000001", month="2026-05")], "2026-05")
    plan = store.plan(may)
    assert plan.conflicts[0].reason_code == "month_reassignment"
    assert plan.conflicts[0].differences[0].field == "month"


def test_future_non_owned_cell_is_ignored(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(write_registry, [paper("lm-000001")])
    seed_paper(store, selected.papers[0])
    store.fields.create_field(key="theory_family", label="Theory family", namespace="future")
    store.entities.set_cell("lm-000001", "theory_family", "MWT", source="future:proposal")
    plan = store.plan(selected)
    assert plan.unchanged == ("lm-000001",)
    assert plan.blocked is False
```

- [ ] **Step 2: Run the focused difference tests and verify RED**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_store.py -k "new_and_unchanged or conflict_and_new or missing_from_source or month_reassignment or future_non_owned"
```

Expected: failures because `CorpusStore.plan()` and difference types do not exist.

- [ ] **Step 3: Implement immutable difference types**

Add to `store.py`:

```python
from source import PaperRecord, RegistrySelection

MISSING = {"state": "missing"}


@dataclass(frozen=True)
class FieldDifference:
    field: str
    expected: Any
    actual: Any
    reason: str


@dataclass(frozen=True)
class RecordConflict:
    paper_id: str
    reason_code: str
    differences: tuple[FieldDifference, ...]


@dataclass(frozen=True)
class MissingSourceRecord:
    paper_id: str
    actual_month: str


@dataclass(frozen=True)
class DiffPlan:
    month: str
    new: tuple[PaperRecord, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[RecordConflict, ...]
    missing_from_source: tuple[MissingSourceRecord, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts or self.missing_from_source)
```

- [ ] **Step 4: Implement owned projection loading and comparison**

Add private methods and `plan()` to `CorpusStore`. Query all entities once and
only the owned namespace/keys; do not call `get_entity()` 3,189 times:

```python
    def _owned_state(self) -> dict[str, dict[str, Any]]:
        owned = tuple(spec.key for spec in FIELD_SPECS)
        placeholders = ",".join("?" for _ in owned)
        with self.db.connect() as conn:
            entities = {
                row["id"]: {"kind": row["kind"], "label": row["label"], "values": {}}
                for row in conn.execute("SELECT id,kind,label FROM entities").fetchall()
            }
            rows = conn.execute(
                f"""
                SELECT c.entity_id,f.key,c.value_json
                FROM cells c JOIN fields f ON f.id=c.field_id
                WHERE f.namespace=? AND f.key IN ({placeholders})
                """,
                (self.config.namespace, *owned),
            ).fetchall()
        import json
        for row in rows:
            if row["entity_id"] in entities:
                entities[row["entity_id"]]["values"][row["key"]] = json.loads(row["value_json"])
        return entities

    def plan(self, selection: RegistrySelection) -> DiffPlan:
        state = self._owned_state()
        source_by_id = {paper.paper_id: paper for paper in selection.papers}
        new = []
        unchanged = []
        conflicts = []
        for paper in selection.papers:
            actual = state.get(paper.paper_id)
            if actual is None:
                new.append(paper)
                continue
            diffs = []
            if actual["kind"] != self.config.entity_kind:
                diffs.append(FieldDifference("entity.kind", self.config.entity_kind, actual["kind"], "value_mismatch"))
            if actual["label"] != paper.label:
                diffs.append(FieldDifference("entity.label", paper.label, actual["label"], "value_mismatch"))
            actual_values = actual["values"]
            for spec in FIELD_SPECS:
                expected = paper.values.get(spec.key, MISSING)
                observed = actual_values.get(spec.key, MISSING)
                if expected != observed:
                    diffs.append(FieldDifference(spec.key, expected, observed, "value_mismatch"))
            if diffs:
                reason = "month_reassignment" if any(diff.field == "month" for diff in diffs) else "source_conflict"
                conflicts.append(RecordConflict(paper.paper_id, reason, tuple(sorted(diffs, key=lambda d: d.field))))
            else:
                unchanged.append(paper.paper_id)
        missing = []
        for paper_id, actual in state.items():
            if actual["kind"] != self.config.entity_kind:
                continue
            if actual["values"].get("month") == selection.month and paper_id not in source_by_id:
                missing.append(MissingSourceRecord(paper_id, selection.month))
        return DiffPlan(
            selection.month,
            tuple(sorted(new, key=lambda item: item.paper_id)),
            tuple(sorted(unchanged)),
            tuple(sorted(conflicts, key=lambda item: item.paper_id)),
            tuple(sorted(missing, key=lambda item: item.paper_id)),
        )
```

- [ ] **Step 5: Run difference tests and verify GREEN**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_store.py
```

Expected: schema/statistics and all difference tests pass.

- [ ] **Step 6: Commit the difference engine**

```powershell
git add -- projects/unbounded-axiom-corpus/store.py projects/unbounded-axiom-corpus/tests/test_store.py
git commit -m "feat: plan conservative corpus differences"
```

---

### Task 4: Atomic Batch Creation, Readback, and Rollback

**Files:**
- Modify: `projects/unbounded-axiom-corpus/store.py`
- Modify: `projects/unbounded-axiom-corpus/tests/test_store.py`

**Interfaces:**
- Consumes: an unblocked `DiffPlan` from Task 3.
- Produces: `WriteResult` and `CorpusStore.apply(plan)` with one transaction and complete rollback.

- [ ] **Step 1: Write failing atomic-apply tests**

Append:

```python
def test_apply_creates_exact_entities_and_nonblank_cells(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(write_registry, [
        paper("lm-000001", created=None),
        paper("lm-000002"),
    ])
    plan = store.plan(selected)
    result = store.apply(plan)
    assert result.created_entities == 2
    assert result.created_cells == sum(len(record.values) for record in selected.papers)
    assert store.entities.get_entity("lm-000001")["cells"].get("created_date") is None
    assert store.integrity_check() == "ok"


def test_apply_refuses_a_blocked_plan_before_writing(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    original = selection(write_registry, [paper("lm-000001")])
    seed_paper(store, original.papers[0])
    changed = selection(write_registry, [
        paper("lm-000001", title="Changed"), paper("lm-000002")
    ])
    with pytest.raises(StorageError) as exc:
        store.apply(store.plan(changed))
    assert exc.value.reason_code == "blocked_plan"
    with pytest.raises(KeyError):
        store.entities.get_entity("lm-000002")


def test_injected_cell_failure_rolls_back_whole_batch(tmp_path, write_registry, monkeypatch):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(write_registry, [paper("lm-000001"), paper("lm-000002")])
    original = store._insert_cells

    def fail_after_one(conn, rows):
        original(conn, rows[:1])
        raise OSError("injected write failure")

    monkeypatch.setattr(store, "_insert_cells", fail_after_one)
    with pytest.raises(StorageError) as exc:
        store.apply(store.plan(selected))
    assert exc.value.reason_code == "storage_failure"
    assert store.stats()["paper_entities"] == 0
    assert store.db.scalar("SELECT COUNT(*) FROM cells") == 0
    assert store.integrity_check() == "ok"


def test_rerun_after_apply_is_no_op_plan(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(write_registry, [paper("lm-000001")])
    store.apply(store.plan(selected))
    rerun = store.plan(selected)
    assert rerun.new == ()
    assert rerun.unchanged == ("lm-000001",)
    assert rerun.blocked is False
```

- [ ] **Step 2: Run atomic tests and verify RED**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_store.py -k "apply or rollback or rerun_after"
```

Expected: failures because `apply()`, `_insert_cells()`, and `WriteResult` do not exist.

- [ ] **Step 3: Implement exact batch writes and transaction rollback**

Add:

```python
import json
from datetime import datetime, timezone

from config import CELL_SOURCE


@dataclass(frozen=True)
class WriteResult:
    created_entities: int
    created_cells: int
    integrity: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

Add these methods to `CorpusStore`:

```python
    def _insert_cells(self, conn, rows: list[tuple]) -> None:
        conn.executemany(
            """
            INSERT INTO cells(entity_id,field_id,value_json,source,confidence,updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            rows,
        )

    def apply(self, plan: DiffPlan) -> WriteResult:
        if plan.blocked:
            raise StorageError("blocked_plan", "blocked difference plan cannot be applied")
        if not plan.new:
            return WriteResult(0, 0, self.integrity_check())
        now = _now()
        try:
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                field_rows = conn.execute(
                    "SELECT id,key FROM fields WHERE namespace=?",
                    (self.config.namespace,),
                ).fetchall()
                field_ids = {row["key"]: row["id"] for row in field_rows}
                expected_keys = {spec.key for spec in FIELD_SPECS}
                if expected_keys - field_ids.keys():
                    raise StorageError(
                        "storage_failure",
                        "owned field IDs changed after successful schema preflight",
                    )
                conn.executemany(
                    "INSERT INTO entities(id,kind,label,created_at,updated_at) VALUES(?,?,?,?,?)",
                    [
                        (paper.paper_id, self.config.entity_kind, paper.label, now, now)
                        for paper in plan.new
                    ],
                )
                cell_rows = [
                    (
                        paper.paper_id,
                        field_ids[key],
                        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        CELL_SOURCE,
                        None,
                        now,
                    )
                    for paper in plan.new
                    for key, value in paper.values.items()
                ]
                self._insert_cells(conn, cell_rows)
                ids = [paper.paper_id for paper in plan.new]
                id_marks = ",".join("?" for _ in ids)
                entity_count = conn.execute(
                    f"SELECT COUNT(*) FROM entities WHERE id IN ({id_marks})", ids
                ).fetchone()[0]
                cell_count = conn.execute(
                    f"SELECT COUNT(*) FROM cells WHERE entity_id IN ({id_marks})", ids
                ).fetchone()[0]
                if entity_count != len(plan.new) or cell_count != len(cell_rows):
                    raise StorageError("readback_failure", "created entity/cell counts do not match plan")
                for paper in plan.new:
                    actual = {
                        row["key"]: json.loads(row["value_json"])
                        for row in conn.execute(
                            """
                            SELECT f.key,c.value_json FROM cells c
                            JOIN fields f ON f.id=c.field_id
                            WHERE c.entity_id=? AND f.namespace=?
                            """,
                            (paper.paper_id, self.config.namespace),
                        ).fetchall()
                    }
                    if actual != paper.values:
                        raise StorageError("readback_failure", f"paper readback mismatch: {paper.paper_id}")
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise StorageError("integrity_failure", f"SQLite integrity check failed: {integrity}")
            return WriteResult(len(plan.new), len(cell_rows), "ok")
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("storage_failure", str(exc)) from exc
```

The connection context rolls back automatically when an exception leaves the
block. Confirm this with the injected failure test before continuing.

- [ ] **Step 4: Run all store tests and verify GREEN**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_store.py
python -m compileall -q projects/unbounded-axiom-corpus/store.py
```

Expected: all store tests pass, including complete rollback.

- [ ] **Step 5: Commit atomic creation**

```powershell
git add -- projects/unbounded-axiom-corpus/store.py projects/unbounded-axiom-corpus/tests/test_store.py
git commit -m "feat: atomically import corpus month batches"
```

---

### Task 5: CLI JSON Contract and Exit Codes

**Files:**
- Create: `projects/unbounded-axiom-corpus/cli.py`
- Create: `projects/unbounded-axiom-corpus/tests/test_cli.py`

**Interfaces:**
- Consumes: `default_config()`, `load_month()`, `CorpusStore.ensure_schema()`, `CorpusStore.plan()`, `CorpusStore.apply()`, and `CorpusStore.stats()`.
- Produces: `build_parser()`, `plan_details()`, `run_command()`, and `main(argv=None) -> int`; commands `init`, `bootstrap`, and `stats`; exit codes 0-5.

- [ ] **Step 1: Write failing CLI tests for success and every expected failure class**

Create `tests/test_cli.py`:

```python
import json

from conftest import paper
from cli import main
from config import ProjectConfig
from sedb.db import Database
from sedb.fields import FieldService


def run(capsys, *args):
    code = main(list(args))
    captured = capsys.readouterr()
    assert captured.out.count("\n{") == 0
    return code, json.loads(captured.out)


def base_args(registry, db):
    return ("--source", str(registry), "--db", str(db))


def test_bootstrap_then_no_op_json(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001"), paper("lm-000002")])
    db = tmp_path / "corpus.sqlite"
    code, first = run(capsys, *base_args(registry, db), "bootstrap", "--month", "2026-04")
    assert code == 0
    assert first["status"] == "imported"
    assert first["diff"]["new"] == 2
    code, second = run(capsys, *base_args(registry, db), "bootstrap", "--month", "2026-04")
    assert code == 0
    assert second["status"] == "no_op"
    assert second["no_op"] is True
    assert second["diff"]["unchanged"] == 2


def test_empty_valid_month_is_exit_2(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001")])
    code, result = run(capsys, *base_args(registry, tmp_path / "db.sqlite"), "bootstrap", "--month", "2026-09")
    assert code == 2
    assert result["status"] == "error"
    assert result["reason_code"] == "target_month_empty"


def test_schema_conflict_is_exit_3_and_is_not_overwritten(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001")])
    db_path = tmp_path / "db.sqlite"
    db = Database(db_path)
    conflict = FieldService(db).create_field(key="paper_id", label="Wrong", namespace="wrong")
    code, result = run(capsys, *base_args(registry, db_path), "bootstrap", "--month", "2026-04")
    assert code == 3
    assert result["reason_code"] == "schema_conflict"
    assert FieldService(db).get_field(conflict["id"])["label"] == "Wrong"


def test_data_conflict_is_exit_4_and_blocks_new(write_registry, tmp_path, capsys):
    first_registry = write_registry([paper("lm-000001")])
    db = tmp_path / "db.sqlite"
    assert run(capsys, *base_args(first_registry, db), "bootstrap", "--month", "2026-04")[0] == 0
    changed_registry = write_registry([
        paper("lm-000001", title="Changed"), paper("lm-000002")
    ])
    code, result = run(capsys, *base_args(changed_registry, db), "bootstrap", "--month", "2026-04")
    assert code == 4
    assert result["status"] == "blocked"
    assert result["diff"]["conflict"] == 1
    assert result["diff"]["new"] == 1


def test_storage_failure_is_exit_5(write_registry, tmp_path, capsys, monkeypatch):
    import cli
    from store import StorageError

    registry = write_registry([paper("lm-000001")])
    db = tmp_path / "db.sqlite"

    def fail_apply(self, plan):
        raise StorageError("storage_failure", "injected CLI storage failure")

    monkeypatch.setattr(cli.CorpusStore, "apply", fail_apply)
    code, result = run(capsys, *base_args(registry, db), "bootstrap", "--month", "2026-04")
    assert code == 5
    assert result["status"] == "error"
    assert result["reason_code"] == "storage_failure"


def test_init_and_stats_are_json_commands(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001")])
    db = tmp_path / "db.sqlite"
    code, initialized = run(capsys, *base_args(registry, db), "init")
    assert code == 0 and initialized["status"] == "initialized"
    code, stats = run(capsys, *base_args(registry, db), "stats")
    assert code == 0 and stats["status"] == "ok"
    assert stats["stats"]["integrity"] == "ok"
```

- [ ] **Step 2: Run CLI tests and verify RED**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_cli.py
```

Expected: collection fails because `cli.py` does not exist.

- [ ] **Step 3: Implement parser, deterministic detail serialization, and commands**

Create `cli.py` with exact command routing:

```python
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from config import ProjectConfig, default_config
from source import SourceValidationError, load_month
from store import CorpusStore, SchemaConflictError, StorageError


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise SourceValidationError("invalid_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description="Unbounded Axiom corpus SEDB month bootstrap")
    defaults = default_config()
    parser.add_argument("--source", type=Path, default=defaults.source_registry)
    parser.add_argument("--db", type=Path, default=defaults.database_path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--month", required=True)
    sub.add_parser("stats")
    return parser


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def plan_details(plan):
    return {
        "new": [paper.paper_id for paper in plan.new],
        "unchanged": list(plan.unchanged),
        "conflicts": _jsonable(plan.conflicts),
        "missing_from_source": _jsonable(plan.missing_from_source),
    }


def run_command(args) -> tuple[int, dict]:
    config = ProjectConfig(args.source, args.db)
    store = CorpusStore.open(config)
    if args.command == "init":
        result = store.ensure_schema()
        return 0, {"result_version": 1, "command": "init", "status": "initialized", "reason_code": None, "init": _jsonable(result)}
    if args.command == "stats":
        store.ensure_schema()
        return 0, {"result_version": 1, "command": "stats", "status": "ok", "reason_code": None, "stats": store.stats()}
    init = store.ensure_schema()
    selected = load_month(config.source_registry, args.month)
    plan = store.plan(selected)
    counts = {
        "new": len(plan.new),
        "unchanged": len(plan.unchanged),
        "conflict": len(plan.conflicts),
        "missing_from_source": len(plan.missing_from_source),
    }
    base = {
        "result_version": 1,
        "command": "bootstrap",
        "source": {
            "registry_version": selected.registry_version,
            "registry_count": selected.registry_count,
            "month": selected.month,
            "selected_count": len(selected.papers),
        },
        "diff": counts,
        "details": plan_details(plan),
        "init": _jsonable(init),
    }
    if plan.blocked:
        reasons = [item.reason_code for item in plan.conflicts]
        reason = "month_reassignment" if "month_reassignment" in reasons else (
            "source_conflict" if plan.conflicts else "missing_from_source"
        )
        return 4, {**base, "status": "blocked", "reason_code": reason, "write": {"created_entities": 0, "created_cells": 0}, "no_op": False, "integrity": store.integrity_check()}
    written = store.apply(plan)
    no_op = not plan.new
    return 0, {
        **base,
        "status": "no_op" if no_op else "imported",
        "reason_code": None,
        "write": {"created_entities": written.created_entities, "created_cells": written.created_cells},
        "no_op": no_op,
        "integrity": written.integrity,
    }
```

- [ ] **Step 4: Implement error-to-exit mapping and one-document output**

Complete `cli.py`:

```python
def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        code, payload = run_command(args)
    except SourceValidationError as exc:
        code = 2
        payload = {"result_version": 1, "command": "bootstrap", "status": "error", "reason_code": exc.reason_code, "message": str(exc), "details": exc.details}
    except SchemaConflictError as exc:
        code = 3
        payload = {"result_version": 1, "command": getattr(locals().get("args"), "command", None), "status": "error", "reason_code": "schema_conflict", "message": str(exc), "details": exc.details}
    except StorageError as exc:
        code = 5
        payload = {"result_version": 1, "command": getattr(locals().get("args"), "command", None), "status": "error", "reason_code": exc.reason_code, "message": str(exc), "details": exc.details}
    except Exception as exc:
        code = 1
        payload = {"result_version": 1, "command": getattr(locals().get("args"), "command", None), "status": "error", "reason_code": "unexpected_error", "message": str(exc), "details": []}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
```

Do not print progress messages. Expected command results remain one JSON object
on stdout. Unexpected exception details required for development may be added
to stderr only under an explicit local debug switch; no debug switch is needed
for this MVP.

- [ ] **Step 5: Run CLI and complete project tests**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_source.py projects/unbounded-axiom-corpus/tests/test_store.py projects/unbounded-axiom-corpus/tests/test_cli.py
python projects/unbounded-axiom-corpus/cli.py --help
python -m compileall -q projects/unbounded-axiom-corpus
```

Expected: all tests pass; help lists `init`, `bootstrap`, and `stats`; compilation is silent.

- [ ] **Step 6: Commit the CLI contract**

```powershell
git add -- projects/unbounded-axiom-corpus/cli.py projects/unbounded-axiom-corpus/tests/test_cli.py
git commit -m "feat: add corpus bootstrap CLI contract"
```

---

### Task 6: Operator Documentation, Real-Registry Acceptance, and Full Verification

**Files:**
- Create: `projects/unbounded-axiom-corpus/README.md`
- Create: `projects/unbounded-axiom-corpus/tests/test_live_acceptance.py`
- Verify only: `D:\Ai\work together\unbounded-axiom\registry\papers.json`
- Verify only: `D:\Ai\work together\SEDB\current\`

**Interfaces:**
- Consumes: complete project API and real registry.
- Produces: an opt-in real-registry test, operator runbook, populated ignored local acceptance DB, and full verification evidence.

- [ ] **Step 1: Write the opt-in live acceptance test**

Create `tests/test_live_acceptance.py`:

```python
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from config import ProjectConfig
from source import load_month
from store import CorpusStore

REGISTRY = Path(r"D:\Ai\work together\unbounded-axiom\registry\papers.json")
UNBOUNDED_ROOT = REGISTRY.parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_status(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "status", "--short", "--branch"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


@pytest.mark.skipif(
    os.environ.get("SEDB_RUN_LIVE_ACCEPTANCE") != "1",
    reason="set SEDB_RUN_LIVE_ACCEPTANCE=1 for the read-only real-registry acceptance",
)
def test_real_april_import_and_no_op(tmp_path):
    before_hash = sha256(REGISTRY)
    before_status = git_status(UNBOUNDED_ROOT)
    selected = load_month(REGISTRY, "2026-04")
    assert len(selected.papers) == 87
    store = CorpusStore.open(ProjectConfig(REGISTRY, tmp_path / "acceptance.sqlite"))
    store.ensure_schema()
    first_plan = store.plan(selected)
    assert len(first_plan.new) == 87
    expected_cells = sum(len(paper.values) for paper in selected.papers)
    first = store.apply(first_plan)
    assert first.created_entities == 87
    assert first.created_cells == expected_cells
    second_plan = store.plan(selected)
    assert second_plan.new == ()
    assert len(second_plan.unchanged) == 87
    second = store.apply(second_plan)
    assert second.created_entities == 0
    assert second.created_cells == 0
    assert store.integrity_check() == "ok"
    assert sha256(REGISTRY) == before_hash
    assert git_status(UNBOUNDED_ROOT) == before_status
```

- [ ] **Step 2: Run ordinary tests and confirm the live test is skipped by default**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
Remove-Item Env:SEDB_RUN_LIVE_ACCEPTANCE -ErrorAction SilentlyContinue
python -m pytest -q projects/unbounded-axiom-corpus/tests
```

Expected: all ordinary tests pass and exactly one live test is skipped.

- [ ] **Step 3: Run the opt-in real-registry acceptance in a temporary database**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
$env:SEDB_RUN_LIVE_ACCEPTANCE = '1'
python -m pytest -q projects/unbounded-axiom-corpus/tests/test_live_acceptance.py
Remove-Item Env:SEDB_RUN_LIVE_ACCEPTANCE
```

Expected: one test passes; it selects 87 papers, imports 87, immediately proves
87 unchanged, and preserves registry SHA-256 plus the exact pre-existing
Unbounded Axiom Git status.

- [ ] **Step 4: Write the operator README with exact authority and commands**

Create `README.md` containing:

````markdown
# Unbounded Axiom Corpus SEDB MVP

This project imports published paper metadata from
`D:\Ai\work together\unbounded-axiom\registry\papers.json` into one cumulative,
local, Git-ignored SEDB SQLite database.

## Authority boundary

- The Unbounded Axiom registry is the read-only metadata source of truth.
- This SQLite database is a local SEDB projection, not a publication source.
- The importer never scans paper files, recomputes hashes, edits the corpus,
  deploys, publishes, registers CTCL instants, or calls an AI provider.
- Any `conflict` or `missing_from_source` blocks the complete month write.
- A bootstrap run never overwrites, deletes, moves, or re-identifies a paper.

## Setup

From `D:\Ai\work together\SEDB`:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python projects/unbounded-axiom-corpus/cli.py init
```

## Import one month

```powershell
python projects/unbounded-axiom-corpus/cli.py bootstrap --month 2026-04
```

Run the same command again. A stable month returns `status: no_op`, `new: 0`,
and the full selected count as `unchanged`.

## Statistics

```powershell
python projects/unbounded-axiom-corpus/cli.py stats
```

## Exit codes

- `0`: successful init, import, no-op, or stats
- `1`: unexpected exception
- `2`: configuration/source/month validation error
- `3`: SEDB schema conflict
- `4`: source difference blocked the batch
- `5`: SQLite write/readback/integrity failure

The local database and SQLite sidecars are ignored by Git.
````

- [ ] **Step 5: Run the full inherited SEDB suite and static verification**

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests
python -m compileall -q projects/unbounded-axiom-corpus
Push-Location current
try { python -m pytest -q } finally { Pop-Location }
git diff --check
git status --short
```

Expected:

- all ordinary project tests pass with the live test skipped;
- project compilation is silent;
- the inherited SEDB v0.4B suite passes;
- `git diff --check` is silent;
- only intended new project/documentation paths plus pre-existing unrelated
  untracked paths appear.

- [ ] **Step 6: Run the two real CLI acceptance invocations against a new ignored database**

First inspect the exact default target. If it already exists, do not delete or
overwrite it. Use `--db projects/unbounded-axiom-corpus/acceptance-2026-04.sqlite`
instead.

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
$db = 'projects/unbounded-axiom-corpus/unbounded-axiom-corpus.sqlite'
if (Test-Path -LiteralPath $db) {
  $db = 'projects/unbounded-axiom-corpus/acceptance-2026-04.sqlite'
  if (Test-Path -LiteralPath $db) { throw "acceptance database already exists: $db" }
}
python projects/unbounded-axiom-corpus/cli.py --db $db bootstrap --month 2026-04
if ($LASTEXITCODE -ne 0) { throw 'first live bootstrap failed' }
python projects/unbounded-axiom-corpus/cli.py --db $db bootstrap --month 2026-04
if ($LASTEXITCODE -ne 0) { throw 'second live bootstrap failed' }
python projects/unbounded-axiom-corpus/cli.py --db $db stats
if ($LASTEXITCODE -ne 0) { throw 'live stats failed' }
git check-ignore -v -- $db
```

Verify the first JSON result reports `selected_count=87`, `new=87`, and
`created_entities=87`. Verify the second reports `new=0`, `unchanged=87`, and
`no_op=true`. Verify stats report `integrity="ok"` and 87 paper entities for
`2026-04`.

- [ ] **Step 7: Commit operator documentation and live acceptance**

```powershell
git add -- projects/unbounded-axiom-corpus/README.md projects/unbounded-axiom-corpus/tests/test_live_acceptance.py
git commit -m "docs: add corpus SEDB acceptance runbook"
```

---

## Final Verification Gate

After all six task commits, rerun one fresh verification pass:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests
python -m compileall -q projects/unbounded-axiom-corpus
Push-Location current
try { python -m pytest -q } finally { Pop-Location }
$verifiedDb = 'projects/unbounded-axiom-corpus/unbounded-axiom-corpus.sqlite'
if (-not (Test-Path -LiteralPath $verifiedDb)) {
  $verifiedDb = 'projects/unbounded-axiom-corpus/acceptance-2026-04.sqlite'
}
if (-not (Test-Path -LiteralPath $verifiedDb)) {
  throw 'verified acceptance database not found'
}
python projects/unbounded-axiom-corpus/cli.py --db $verifiedDb stats
git diff --check
git status --short --branch
git log -7 --oneline
```

Then check the acceptance database read-only:

```powershell
python -c "import sqlite3,sys; p=sys.argv[1]; c=sqlite3.connect('file:'+p.replace('\\','/')+'?mode=ro',uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0])" $verifiedDb
```

Completion requires all of the following evidence:

1. project tests pass and the opt-in live test passes when explicitly enabled;
2. inherited SEDB v0.4B tests pass unchanged;
3. the real registry selects exactly 87 papers for `2026-04`;
4. first CLI import creates 87 entities and the computed nonblank cell count;
5. immediate rerun is a true 87-paper no-op;
6. `target_month_empty` is independently tested as exit code `2`;
7. incompatible field/view schema is independently tested as exit code `3`
   without overwrite;
8. `conflict` and `missing_from_source` independently block valid new records;
9. month reassignment is a global-ID conflict, not a new entity;
10. injected write failure rolls back the complete transaction;
11. future non-owned fields do not affect equality;
12. SQLite integrity is `ok`;
13. the database and sidecars are Git-ignored;
14. Unbounded Axiom registry bytes and worktree status are unchanged;
15. SEDB `current/` and unrelated untracked files are unchanged;
16. no deployment, publication, CTCL call, remote write, merge, release, or
    source mutation occurred.
