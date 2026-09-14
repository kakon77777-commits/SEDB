from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from isql_core.semantic_addressing import semantic_address_from_analysis
from isql_core.semantics import SemanticAnalysis, SemanticCoordinateSet
from isql_sedb_readonly import SEDBExactStateMismatch, SEDBReadOnlyAdapter
from isql_sedb_readonly.active_domain import ActiveDomainBudget, plan_active_domain
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


def semantic(*concepts: str) -> SemanticAnalysis:
    return SemanticAnalysis(
        analyzer_id="active-domain-fixture",
        analyzer_contract="active-domain-contract-v1",
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


class ActiveDomainPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "sedb.sqlite3"
        self.db = Database(self.db_path)
        self.fields = FieldService(self.db)
        self.entities = EntityService(self.db)
        self.views = ViewService(self.db)

        for key in ("topic", "score", "notes"):
            self.fields.create_field(key=key, label=key.title(), value_type="json")

        for entity_id in ("Entity-A", "Entity-B", "Entity-C"):
            self.entities.create_entity(label=entity_id, kind="record", entity_id=entity_id)

        self.entities.set_cell("Entity-A", "topic", "isql", source="fixture")
        self.entities.set_cell("Entity-A", "score", 10, source="fixture")
        self.entities.set_cell("Entity-A", "notes", "hot", source="fixture")
        self.entities.set_cell("Entity-B", "topic", "isql", source="fixture")
        self.entities.set_cell("Entity-C", "topic", "other", source="fixture")

        self.view = self.views.create_view(
            "research-task",
            ["topic", "score", "notes"],
            query_text="ISQL research task",
        )
        self.adapter = SEDBReadOnlyAdapter(self.db_path)

        self.analyses = {
            "Entity-A": semantic("isql", "memory"),
            "Entity-B": semantic("isql"),
            "Entity-C": semantic("other"),
        }
        self.index = self.adapter.build_semantic_index(self.analyses)
        self.query = semantic_address_from_analysis(semantic("isql", "memory"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_task_view_field_support_is_reused_and_budgeted(self):
        plan = plan_active_domain(
            self.adapter,
            self.query,
            self.index,
            view_id=self.view["id"],
            budget=ActiveDomainBudget(
                max_candidate_scan=8,
                max_entities=2,
                max_fields=2,
                max_cells=10,
            ),
        )
        self.assertEqual(plan.total_view_fields, 3)
        self.assertEqual([field.key for field in plan.selected_fields], ["topic", "score"])
        self.assertTrue(plan.field_support_truncated)

    def test_semantic_ranking_and_entity_budget_define_finite_domain(self):
        plan = plan_active_domain(
            self.adapter,
            self.query,
            self.index,
            view_id=self.view["id"],
            budget=ActiveDomainBudget(
                max_candidate_scan=8,
                max_entities=1,
                max_fields=3,
                max_cells=10,
            ),
        )
        self.assertEqual(len(plan.selected_entities), 1)
        self.assertEqual(plan.selected_entities[0].exact.entity_id, "Entity-A")
        self.assertTrue(plan.entity_budget_exhausted)
        self.assertLessEqual(len(plan.selected_entities), 1)

    def test_cell_budget_can_skip_expensive_higher_ranked_candidate(self):
        plan = plan_active_domain(
            self.adapter,
            self.query,
            self.index,
            view_id=self.view["id"],
            budget=ActiveDomainBudget(
                max_candidate_scan=8,
                max_entities=2,
                max_fields=2,
                max_cells=1,
            ),
        )
        self.assertEqual(plan.omitted_for_cell_budget, ("Entity-A",))
        self.assertEqual([item.exact.entity_id for item in plan.selected_entities], ["Entity-B"])
        self.assertEqual(plan.selected_cell_count, 1)
        self.assertTrue(plan.cell_budget_exhausted)

    def test_candidate_scan_limit_is_explicit(self):
        shared = semantic("shared")
        index = self.adapter.build_semantic_index({
            "Entity-A": shared,
            "Entity-B": shared,
            "Entity-C": shared,
        })
        query = semantic_address_from_analysis(shared)
        plan = plan_active_domain(
            self.adapter,
            query,
            index,
            view_id=self.view["id"],
            budget=ActiveDomainBudget(
                max_candidate_scan=1,
                max_entities=1,
                max_fields=1,
                max_cells=10,
            ),
        )
        self.assertEqual(plan.probe_count, 3)
        self.assertTrue(plan.candidate_scan_truncated)
        self.assertEqual(len(plan.selected_entities), 1)

    def test_stale_exact_state_aborts_domain_planning(self):
        self.entities.set_cell("Entity-A", "topic", "isql-updated", source="mutation")
        with self.assertRaises(SEDBExactStateMismatch):
            plan_active_domain(
                self.adapter,
                self.query,
                self.index,
                view_id=self.view["id"],
                budget=ActiveDomainBudget(
                    max_candidate_scan=8,
                    max_entities=2,
                    max_fields=3,
                    max_cells=10,
                ),
            )

    def test_missing_task_view_fails_closed(self):
        with self.assertRaises(KeyError):
            plan_active_domain(
                self.adapter,
                self.query,
                self.index,
                view_id="missing-view",
            )

    def test_budget_contract_rejects_unbounded_or_inconsistent_values(self):
        with self.assertRaises(Exception):
            ActiveDomainBudget(max_candidate_scan=1, max_entities=2)
        with self.assertRaises(Exception):
            ActiveDomainBudget(max_candidate_scan=10_001)
        with self.assertRaises(Exception):
            ActiveDomainBudget(max_cells=1_000_001)


if __name__ == "__main__":
    unittest.main()
