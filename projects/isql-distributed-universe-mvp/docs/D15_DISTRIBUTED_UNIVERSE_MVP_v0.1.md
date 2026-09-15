# D15 Distributed Universe Synthetic MVP / Acceptance Harness v0.1

**Status:** Experimental application-runtime acceptance layer  
**Purpose:** compose the already merged ISQL / SEDB / DSR / RAL layers into one measurable finite-universe execution

## 1. Why D15 exists

The previous work established the pieces independently:

```text
A2  semantic -> exact addressing
D2  active-domain planning
D5  persistent proof checkpoint
D6  checkpoint history
D8  branch publication / merge history
D9  composite world head
D10 world-head RAL/CTCL anchor
D11 physical placement / exact verified fetch
D12 proof-verified range fetch
D13 materialization manifest
D14 materialization-manifest RAL/CTCL anchor
```

D15 asks the system-level question:

> Can these pieces actually operate together so that a universe is larger than the materialized working set, while exact identity and external evidence remain intact?

## 2. Executed path

The harness creates a real synthetic SEDB universe and executes:

$$
\boxed{
Q
\rightarrow
A_S
\rightarrow
\mathcal C
\rightarrow
(E,H)
\rightarrow
D_Q
\rightarrow
\text{D5 checkpoint}
\rightarrow
\text{D6 history}
}
$$

in parallel with a real DSR branch publication:

$$
\boxed{
\text{DSR base}
\rightarrow
\text{D8 branch head}
}
$$

These are combined into:

$$
\boxed{
D9:\quad H(W_H)
}
$$

Then only active-domain artifacts receive D12 range commitments and are listed in:

$$
\boxed{
D13:\quad H(M_W)
}
$$

Before physical reads, both identities are externally evidenced in one RAL history:

```text
D10 world-head anchor
-> D14 materialization anchor
-> externally retained final RAL head
```

Finally:

$$
\boxed{
H(M_W)
\rightarrow
\{H(X_i),H(C_{R,i})\}
\rightarrow
D11\ R_P
\rightarrow
D12\ \text{verified range reads}
}
$$

## 3. Synthetic universe

Every synthetic entity has:

- exact case-sensitive entity ID;
- topic field;
- ordinal field;
- artifact ref;
- deterministic binary artifact payload.

Entities are divided into semantic topics. The query addresses exactly one topic, so the semantic inverted index reduces the candidate domain before D2 budget selection.

Every universe artifact physically exists in the good provider, but only active-domain artifacts receive range-proof commitments and enter the materialization manifest.

This creates a real distinction between:

$$
\text{Universe Objects}
\gg
\text{Semantic Candidates}
\ge
\text{Active Entities}
=
\text{Materialization Artifacts}
$$

## 4. Metrics

The acceptance report records:

```text
universe_objects
total_universe_bytes
semantic_profile_entries
semantic_probe_count
semantic_probe_ratio
active_entities
active_domain_ratio
selected_cells
materialization_artifacts
requested_payload_bytes
physical_range_bytes
physical_fetch_ratio
range_sidecar_bytes
reservoir_sidecar_bytes
replica_failover_count
world_head_sha256
materialization_manifest_sha256
world_head_ral_anchor_verified
materialization_ral_anchor_verified
ral_final_chain_digest
historical_world_head_valid_after_dsr_advance
historical_world_head_current_after_dsr_advance
new_world_head_current
stale_materialization_rejected_for_new_world_head
```

The key operational ratios are:

$$
r_S=
\frac{\text{semantic probes}}{\text{universe objects}}
$$

$$
r_A=
\frac{\text{active entities}}{\text{universe objects}}
$$

$$
r_B=
\frac{\text{physical range bytes}}{\text{total universe artifact bytes}}
$$

For the functional acceptance profile, all three must be strictly below 1.

## 5. Corrupt replica experiment

The highest-priority placement for one active artifact is deliberately corrupted inside the requested chunk.

The D12 proof fails for that replica. D11 then tries the next placement while preserving:

```text
same H(X)
same H(C_R)
same requested byte range
```

The acceptance report requires at least one observed replica failover.

Thus the MVP verifies:

$$
\boxed{
\text{Replica Failover}
\neq
\text{Identity Failover}
}
$$

## 6. Historical world-head experiment

After the initial world/materialization reads succeed, D15 advances the DSR branch through D8 CAS publication.

The old D9 world head must then satisfy:

```text
historical valid = true
current = false
```

A new D9 world head built from the new D8 record must be current.

The old D13 materialization manifest is then checked against the new D9 hash and must fail the world-head binding gate.

This verifies:

$$
\boxed{
\text{Historical Validity}
\neq
\text{Currentness}
}
$$

across the composed system.

## 7. External evidence experiment

D15 creates one synthetic-but-contract-valid CTCL registered anchor for D10 and another for D14.

Both events are appended to the same RAL ledger, with the D14 event causally referencing the D10 event.

The final RAL head is then used to verify both historical inclusions.

The fixture intentionally uses `verification_status=not_performed` for the synthetic CTCL signature. D15 tests contract/inclusion behavior; it does not claim real external CTCL service verification or real world-state authorship authority.

## 8. Acceptance rule

`acceptance_passes(report)` requires:

- universe larger than active domain;
- semantic probe ratio $<1$;
- active-domain ratio $<0.25$;
- physical bytes fetched less than total universe bytes;
- at least one corrupt-replica failover;
- D10 world-head anchor verification;
- D14 materialization-anchor verification;
- old D9 head historically valid after DSR advance;
- old D9 head no longer current;
- new D9 head current;
- stale D13 materialization rejected against the new D9 head.

## 9. Reproducibility boundary

Artifact bytes, entity IDs, topic partition, query, DSR events, and acceptance ratios are deterministic under the configured seed.

Current SEDB creates field IDs and timestamps internally. Therefore D15 does **not** claim that independent runs produce the same full SEDB checkpoint SHA-256.

The exact hashes in each report are the genuine identities of that run.

## 10. Scale boundary

D15 v0.1 is a functional MVP, not a PB-scale performance proof.

CI runs a bounded synthetic universe large enough to demonstrate candidate/active/materialized reduction without turning correctness CI into a stress benchmark.

A later benchmark phase should scale toward $10^5$–$10^6$ objects and report:

- candidate lookup complexity;
- sidecar construction cost;
- proof index size;
- range-proof overhead;
- cache hit rate;
- multi-provider latency;
- concurrent active-domain behavior.

That future benchmark must not weaken the exact correctness gates established here.

## 11. Architectural result

D15 is the first executable system-level demonstration of the Paper 06 principle:

$$
\boxed{
\text{One Logical Universe}
+
\text{Many Finite Materialized Domains}
}
$$

The universe can contain all artifacts while one query resolves, verifies, externally anchors, and physically reads only the finite subset required by the active domain.
