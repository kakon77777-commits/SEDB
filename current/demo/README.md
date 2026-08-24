# SEDB Demo Databases

The `demo/` directory contains local validation fixtures from successive SEDB checkpoints.

## v0.4B

- `sedb-autonomy-governance-v0.4b.sqlite` — reflexive autonomous canonical-commit fixture covering autonomous proposal acceptance, semantic-conflict escalation, authority-legal novel action with missing capability, and compensating rollback.
- `autonomy-stats-v0.4b.json` — exact captured v0.4B governance output and autonomy metrics.
- `DEMO_SHA256_v0.4B.txt` — SHA-256 for the packaged v0.4B SQLite fixture.

The fixture demonstrates:

$$
\text{Decision}\neq\text{Commit},
\qquad
\text{Capability}\neq\text{Authority},
$$

and preserves Decision/Commit history across rollback. The recorded values are release-fixture evidence, not a general claim about autonomous-system safety or model capability.

## v0.4A

- `sedb-campaign-governance-v0.4a.sqlite` — five-run coordination fixture producing `strong_agreement` and `incompatible` packets while preserving canonical field/cell counts.
- `sedb-campaign-benchmark-v0.4a.sqlite` — bounded 80-run / 8-key local coordination benchmark.
- `campaign-stats-v0.4a.json` — exact captured outputs, metrics, and packets from both v0.4A fixtures.
- `DEMO_SHA256_v0.4A.txt` — SHA-256 for the two packaged v0.4A SQLite fixtures.

The benchmark elapsed time (`1.606748 s` in the captured release run) is specific to this fixture and environment and is not a general performance guarantee.

## v0.3C

- `sedb-agent-governance-v0.3c.sqlite` — governed Agent fixture covering deterministic discovery, external suggestions, a denied `set_cell` intent, and budget exhaustion while preserving canonical field/cell counts.
- `sedb-agent-observation-v0.3c.sqlite` — 2,000-record × 20-field provider-free deterministic observation benchmark.
- `agent-stats-v0.3c.json` — exact captured outputs from both v0.3C fixtures.
- `DEMO_SHA256_v0.3C.txt` — SHA-256 for the two packaged v0.3C SQLite fixtures.

## v0.3B

- `sedb-family-governance-v0.3b.sqlite` — reviewed duplicate/related/split/reject family-governance fixture.
- `sedb-family-10k-v0.3b.sqlite` — bounded 10,000-field family-scan fixture.
- `family-stats-v0.3b.json` — exact captured v0.3B family benchmark output.
- `DEMO_SHA256_v0.3B.txt` — SHA-256 for the two packaged v0.3B SQLite fixtures.

## v0.3A

- `sedb-utility-governance-v0.3a.sqlite` — small field-utility governance fixture containing all utility-v1 recommendation categories and an explicit apply trail.
- `sedb-utility-10k-v0.3a.sqlite` — fresh 10,000-field registry with 10,000 immutable utility-v1 assessments.
- `utility-stats-v0.3a.json` — exact output captured from the packaged v0.3A utility demo/benchmark run.
- `DEMO_SHA256_v0.3A.txt` — SHA-256 for the two packaged v0.3A SQLite fixtures.

## v0.2B retained fixtures

- `sedb-demo-10k-v0.2b.sqlite` — sparse 10K field base demo.
- `sedb-semantic-scan-10k-v0.2b.sqlite` — bounded semantic-candidate scan fixture.
- `sedb-governance-v0.2b.sqlite` — canonical field governance and semantic review fixture.

Older fixtures are retained as migration/regression evidence; v0.3A does not rewrite them in place.
