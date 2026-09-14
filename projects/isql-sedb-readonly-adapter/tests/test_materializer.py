from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from isql_core.semantic_addressing import semantic_address_from_analysis
from isql_core.semantics import SemanticAnalysis, SemanticCoordinateSet
from isql_sedb_readonly import SEDBExactStateMismatch, SEDBReadOnlyAdapter
from isql_sedb_readonly.active_domain import ActiveDomainBudget, plan_active_domain
from isql_sedb_readonly.materializer import (
    FieldProjectionState,
    materialize_partial_domain,
)
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


def semantic(*concepts: str) -> SemanticAnalysis:
    return SemanticAnalysis(
        analyzer_id="partial-fixture",
        analyzer_contract="partial-contract-v1",
        coordinates=SemanticCoordinateSet(
            summary="fixture",
            concepts=tuple(concepts),
            entities=(),
            relations=(),
            claims=(),
            intent=None,
            uncertainty=(),
            tags=(),
            language="en",
        ),
    )


class PartialMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "sedb.sqlite3"
        self.db = Database(self.db_path)
        self.fields = FieldService(self.db)
        self.entities = EntityService(self.db)
        self.views = ViewService(self.db)

        for key in ("topic", "nullable", "missing", "hidden"):
            self.fields.create_field(key=key, label=key.title(), value_type="json")

        self.entities.create_entity(label="Alpha", kind="record", entity_id="Entity-A")
        self.entities.set_cell("Entity-A", "topic", {"name": "ISQL"}, source="fixture", confidence=0.9)
        self.entities.set_cell("Entity-A", "nullable", None, source="fixture:blank", confidence=1.0)
        self.entities.set_cell("Entity-A", "hidden", "secret-but-not-selected", source="fixture:hidden")

        self.view = self.views.create_view(
            "partial-task",
            ["topic", "nullable", "missing", "hidden"],
        )
        self.adapter = SEDBReadOnlyAdapter(self.db_path)
        self.index = self.adapter.build_semantic_index({"Entity-A": semantic("isql")})
        self.query = semantic_address_from_analysis(semantic("isql"))
        self.plan = plan_active_domain(
            self.adapter,
            self.query,
            self.index,
            view_id=self.view["id"],
            budget=ActiveDomainBudget(
                max_candidate_scan=4,
                max_entities=1,
                max_fields=3,
                max_cells=10,
            ),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _projection(self):
        result = materialize_partial_domain(self.adapter, self.plan)
        self.assertEqual(len(result.projections), 1)
        return result.projections[0]

    def test_present_blank_absent_and_unloaded_are_distinct(self):
        projection = self._projection()
        states = {slot.field.key: slot.state for slot in projection.fields}
        self.assertEqual(states["topic"], FieldProjectionState.PRESENT)
        self.assertEqual(states["nullable"], FieldProjectionState.BLANK)
        self.assertEqual(states["missing"], FieldProjectionState.ABSENT)
        self.assertEqual(states["hidden"], FieldProjectionState.UNLOADED)

    def test_blank_is_explicit_json_null_not_missing_cell(self):
        projection = self._projection()
        blank = next(slot for slot in projection.fields if slot.field.key == "nullable")
        absent = next(slot for slot in projection.fields if slot.field.key == "missing")
        self.assertIsNone(blank.value)
        self.assertEqual(blank.source, "fixture:blank")
        self.assertIsNotNone(blank.updated_at)
        self.assertEqual(absent.to_dict()["state"], "absent")
        self.assertNotIn("value", absent.to_dict())

    def test_unknown_requires_explicit_marker_and_never_inferred_from_absence(self):
        absent_projection = self._projection()
        missing = next(slot for slot in absent_projection.fields if slot.field.key == "missing")
        self.assertEqual(missing.state, FieldProjectionState.ABSENT)

        missing_field = next(field for field in self.plan.selected_fields if field.key == "missing")
        marked = materialize_partial_domain(
            self.adapter,
            self.plan,
            unknown_cells={("Entity-A", missing_field.field_id): "source explicitly reports unknown"},
        ).projections[0]
        unknown = next(slot for slot in marked.fields if slot.field.key == "missing")
        self.assertEqual(unknown.state, FieldProjectionState.UNKNOWN)
        self.assertEqual(unknown.unknown_reason, "source explicitly reports unknown")
        self.assertNotIn("value", unknown.to_dict())

    def test_unknown_marker_cannot_override_present_or_unloaded_state(self):
        topic = next(field for field in self.plan.selected_fields if field.key == "topic")
        with self.assertRaisesRegex(Exception, "PARTIAL_UNKNOWN_CONFLICTS_WITH_PRESENT_CELL"):
            materialize_partial_domain(
                self.adapter,
                self.plan,
                unknown_cells={("Entity-A", topic.field_id): "wrong override"},
            )

        hidden_id = next(
            item["id"] for item in self.view["fields"] if item["key"] == "hidden"
        )
        with self.assertRaisesRegex(Exception, "PARTIAL_UNKNOWN_CELL_OUTSIDE_SELECTED_DOMAIN"):
            materialize_partial_domain(
                self.adapter,
                self.plan,
                unknown_cells={("Entity-A", hidden_id): "not loaded"},
            )

    def test_partial_projection_has_separate_identity_from_full_exact_snapshot(self):
        projection = self._projection()
        self.assertEqual(projection.source_exact, self.plan.selected_entities[0].exact)
        self.assertNotEqual(
            projection.projection_sha256(),
            projection.source_exact.state_sha256,
        )
        self.assertEqual(projection.to_dict()["schema"], "isql-sedb.partial-entity-projection/v0.1")

    def test_projection_is_deterministic_for_same_plan_and_epistemic_markers(self):
        first = materialize_partial_domain(self.adapter, self.plan)
        second = materialize_partial_domain(self.adapter, self.plan)
        self.assertEqual(first, second)
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())
        self.assertEqual(first.materialization_sha256(), second.materialization_sha256())

    def test_unloaded_field_can_contain_real_sedb_value_without_becoming_absent(self):
        projection = self._projection()
        hidden = next(slot for slot in projection.fields if slot.field.key == "hidden")
        self.assertEqual(hidden.state, FieldProjectionState.UNLOADED)
        self.assertNotIn("value", hidden.to_dict())
        full = self.adapter.read_entity_snapshot("Entity-A")
        full_hidden = next(cell for cell in full.cells if cell.field.key == "hidden")
        self.assertEqual(full_hidden.value, "secret-but-not-selected")

    def test_stale_plan_aborts_before_partial_projection(self):
        self.entities.set_cell("Entity-A", "topic", {"name": "ISQL-v2"}, source="mutation")
        with self.assertRaises(SEDBExactStateMismatch):
            materialize_partial_domain(self.adapter, self.plan)

    def test_projection_preserves_all_task_view_field_ordinals_as_coverage_metadata(self):
        projection = self._projection()
        self.assertEqual(
            [(slot.field.ordinal, slot.field.key) for slot in projection.fields],
            [(0, "topic"), (1, "nullable"), (2, "missing"), (3, "hidden")],
        )


if __name__ == "__main__":
    unittest.main()
