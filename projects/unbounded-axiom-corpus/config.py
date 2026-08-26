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
    FieldSpec(
        "title",
        "title",
        "Title",
        "Paper title recorded by the Unbounded Axiom registry.",
    ),
    FieldSpec(
        "source_file",
        "source_file",
        "Source file",
        "Canonical source path recorded by the Unbounded Axiom registry.",
    ),
    FieldSpec(
        "language",
        "language",
        "Language",
        "Paper language tag recorded by the Unbounded Axiom registry.",
    ),
    FieldSpec(
        "created",
        "created_date",
        "Created date",
        "Publication or upload date recorded by the registry when present.",
        optional=True,
    ),
    FieldSpec("year", "year", "Year", "Registry year represented as canonical text."),
    FieldSpec(
        "month",
        "month",
        "Month",
        "Registry publication month and bootstrap partition key.",
    ),
    FieldSpec(
        "hash",
        "sha256",
        "SHA-256",
        "Registry SHA-256 identity string preserved verbatim.",
    ),
    FieldSpec(
        "canonical_url",
        "canonical_url",
        "Canonical URL",
        "Permanent public paper route recorded by the registry.",
    ),
    FieldSpec(
        "date_confidence",
        "date_confidence",
        "Date confidence",
        "Registry confidence class for the recorded date.",
        optional=True,
    ),
    FieldSpec(
        "date_basis",
        "date_basis",
        "Date basis",
        "Registry provenance statement explaining the recorded date basis.",
        optional=True,
    ),
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
        source_registry=Path(
            r"D:\Ai\work together\unbounded-axiom\registry\papers.json"
        ),
        database_path=project_dir / "unbounded-axiom-corpus.sqlite",
    )
