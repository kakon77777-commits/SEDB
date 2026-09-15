from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from isql_core.semantic_addressing import semantic_address_from_analysis
from isql_core.semantics import SemanticAnalysis, SemanticCoordinateSet
from isql_sedb_readonly import SEDBExactStateMismatch, SEDBReadOnlyAdapter
from isql_sedb_readonly.active_domain import ActiveDomainBudget, plan_active_domain
from isql_sedb_readonly.commitment import (
    MerkleMembershipProof,
    issue_proof_carrying_projection,
    verify_membership_proof,
    verify_nonmembership_proof,
    verify_proof_carrying_projection,
)
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
        analyzer_id="commitment-fixture",
        analyzer_contract="commitment-contract-v1",
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


class ProofCarryingPartialReadTests(unittest.TestCase):
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
        self.entities.set_cell(
            "Entity-A", "topic", {"name": "ISQL"}, source="fixture", confidence=0.9
        )
        self.entities.set_cell(
            "Entity-A", "nullable", None, source="fixture:blank", confidence=1.0
        )
        self.entities.set_cell(
            "Entity-A", "hidden", "secret-but-unloaded", source="fixture:hidden"
        )

        self.view = self.views.create_view(
            "proof-task",
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

    def _projection(self, *, unknown: bool = False):
        kwargs = {}
        if unknown:
            missing = next(field for field in self.plan.selected_fields if field.key == "missing")
            kwargs["unknown_cells"] = {
                ("Entity-A", missing.field_id): "source reports unknown"
            }
        return materialize_partial_domain(
            self.adapter,
            self.plan,
            **kwargs,
        ).projections[0]

    def test_present_blank_absent_and_unloaded_claims_verify(self):
        projection = self._projection()
        bundle = issue_proof_carrying_projection(self.adapter, projection)
        self.assertTrue(verify_proof_carrying_projection(bundle))

        claims = {
            slot.field.key: (slot, claim)
            for slot, claim in zip(projection.fields, bundle.claims, strict=True)
        }
        present, present_claim = claims["topic"]
        blank, blank_claim = claims["nullable"]
        absent, absent_claim = claims["missing"]
        unloaded, unloaded_claim = claims["hidden"]

        self.assertEqual(present.state, FieldProjectionState.PRESENT)
        self.assertIsNotNone(present_claim.cell_membership)
        self.assertIsNone(present_claim.cell_nonmembership)

        self.assertEqual(blank.state, FieldProjectionState.BLANK)
        self.assertIsNotNone(blank_claim.cell_membership)
        self.assertIsNone(blank_claim.cell_nonmembership)

        self.assertEqual(absent.state, FieldProjectionState.ABSENT)
        self.assertIsNone(absent_claim.cell_membership)
        self.assertIsNotNone(absent_claim.cell_nonmembership)
        self.assertTrue(verify_nonmembership_proof(
            absent_claim.cell_nonmembership,
            bundle.entity_commitment.cell_root_sha256,
        ))

        self.assertEqual(unloaded.state, FieldProjectionState.UNLOADED)
        self.assertIsNone(unloaded_claim.cell_membership)
        self.assertIsNone(unloaded_claim.cell_nonmembership)
        self.assertTrue(verify_membership_proof(
            unloaded_claim.field_membership,
            bundle.field_registry_commitment.field_root_sha256,
        ))

    def test_unknown_is_nonmembership_plus_external_epistemic_annotation(self):
        projection = self._projection(unknown=True)
        bundle = issue_proof_carrying_projection(self.adapter, projection)
        self.assertTrue(verify_proof_carrying_projection(bundle))
        slot_index = next(
            index for index, slot in enumerate(projection.fields) if slot.field.key == "missing"
        )
        slot = projection.fields[slot_index]
        claim = bundle.claims[slot_index]
        self.assertEqual(slot.state, FieldProjectionState.UNKNOWN)
        self.assertEqual(slot.unknown_reason, "source reports unknown")
        self.assertIsNotNone(claim.cell_nonmembership)
        self.assertIsNone(claim.cell_membership)

    def test_verifier_is_database_independent_after_issuance(self):
        bundle = issue_proof_carrying_projection(self.adapter, self._projection())
        # Verification consumes only commitments/proofs. The source database is not consulted.
        self.db_path.unlink()
        self.assertTrue(verify_proof_carrying_projection(bundle))

    def test_tampered_projected_value_fails_proof(self):
        bundle = issue_proof_carrying_projection(self.adapter, self._projection())
        fields = list(bundle.projection.fields)
        index = next(i for i, slot in enumerate(fields) if slot.field.key == "topic")
        fields[index] = replace(fields[index], value={"name": "tampered"})
        projection = replace(bundle.projection, fields=tuple(fields))
        tampered = replace(bundle, projection=projection)
        self.assertFalse(verify_proof_carrying_projection(tampered))

    def test_tampered_field_merkle_path_fails(self):
        bundle = issue_proof_carrying_projection(self.adapter, self._projection())
        claim = bundle.claims[0]
        proof = claim.field_membership
        self.assertTrue(proof.siblings)
        siblings = list(proof.siblings)
        siblings[0] = "00" * 32
        bad_proof = replace(proof, siblings=tuple(siblings))
        claims = list(bundle.claims)
        claims[0] = replace(claim, field_membership=bad_proof)
        self.assertFalse(verify_proof_carrying_projection(replace(bundle, claims=tuple(claims))))

    def test_nonmembership_neighbor_index_tampering_fails(self):
        bundle = issue_proof_carrying_projection(self.adapter, self._projection())
        index = next(
            i for i, slot in enumerate(bundle.projection.fields) if slot.field.key == "missing"
        )
        claim = bundle.claims[index]
        proof = claim.cell_nonmembership
        self.assertIsNotNone(proof)
        neighbor = proof.predecessor or proof.successor
        self.assertIsNotNone(neighbor)
        # Change the claimed position while keeping a syntactically valid proof object.
        new_index = 0 if neighbor.index != 0 else min(1, neighbor.count - 1)
        if new_index == neighbor.index:
            self.skipTest("single-leaf boundary has no alternate valid index")
        bad_neighbor = replace(neighbor, index=new_index)
        bad_nonmembership = replace(
            proof,
            predecessor=bad_neighbor if proof.predecessor is not None else None,
            successor=bad_neighbor if proof.predecessor is None else proof.successor,
        )
        claims = list(bundle.claims)
        claims[index] = replace(claim, cell_nonmembership=bad_nonmembership)
        self.assertFalse(verify_proof_carrying_projection(replace(bundle, claims=tuple(claims))))

    def test_global_field_addition_changes_registry_commitment_not_entity_commitment(self):
        projection = self._projection()
        before = issue_proof_carrying_projection(self.adapter, projection)
        self.fields.create_field(key="unrelated-global-field", label="Unrelated", value_type="text")
        after = issue_proof_carrying_projection(self.adapter, projection)

        self.assertEqual(before.entity_commitment, after.entity_commitment)
        self.assertNotEqual(
            before.field_registry_commitment.field_root_sha256,
            after.field_registry_commitment.field_root_sha256,
        )
        self.assertNotEqual(
            before.field_registry_commitment.commitment_sha256(),
            after.field_registry_commitment.commitment_sha256(),
        )

    def test_entity_mutation_changes_commitment_and_stale_projection_cannot_be_issued(self):
        projection = self._projection()
        before = issue_proof_carrying_projection(self.adapter, projection)
        self.entities.set_cell(
            "Entity-A", "topic", {"name": "ISQL-v2"}, source="mutation", confidence=0.91
        )
        current = self.adapter.read_entity_snapshot("Entity-A")
        self.assertNotEqual(before.entity_commitment.legacy_snapshot_sha256, current.sha256())
        with self.assertRaises(SEDBExactStateMismatch):
            issue_proof_carrying_projection(self.adapter, projection)

    def test_legacy_hash_is_bound_as_bridge_reference_but_not_recomputed_by_verifier(self):
        projection = self._projection()
        bundle = issue_proof_carrying_projection(self.adapter, projection)
        self.assertEqual(
            bundle.entity_commitment.legacy_snapshot_sha256,
            projection.source_exact.state_sha256,
        )
        self.assertTrue(verify_proof_carrying_projection(bundle))

        # A different bridge hash must fail projection/commitment consistency even though
        # the Merkle roots themselves are unchanged.
        fake = replace(bundle.entity_commitment, legacy_snapshot_sha256="11" * 32)
        self.assertFalse(verify_proof_carrying_projection(replace(bundle, entity_commitment=fake)))

    def test_commitments_and_proof_bundle_are_deterministic(self):
        projection = self._projection()
        first = issue_proof_carrying_projection(self.adapter, projection)
        second = issue_proof_carrying_projection(self.adapter, projection)
        self.assertEqual(first, second)
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())
        self.assertEqual(first.proof_bundle_sha256(), second.proof_bundle_sha256())
        self.assertEqual(
            first.entity_commitment.commitment_sha256(),
            second.entity_commitment.commitment_sha256(),
        )


if __name__ == "__main__":
    unittest.main()
