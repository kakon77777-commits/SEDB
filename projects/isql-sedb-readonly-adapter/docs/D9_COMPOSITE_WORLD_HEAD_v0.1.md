# D9 Composite World Head Manifest v0.1

**Status:** Experimental read-only integration layer  
**Repositories:** SEDB + ISQL-DSP

## Purpose

D6 provides append-only checkpoint history for the persistent SEDB/ISQL state reservoir.

D8 provides append-only branch-head and merge provenance for DSR dynamic state.

Those identities are not interchangeable.

D9 introduces one small synchronization object that binds them without collapsing their semantics:

$$
\boxed{
W_H
=
(
H_{reservoir\ record},
H_{DSR\ record}
)
}
$$

The manifest itself receives its own SHA-256 identity.

## Reservoir component

The manifest binds an exact D6 checkpoint-history position:

```text
stream_id
sequence
checkpoint-history record SHA-256
proof-sidecar checkpoint SHA-256
```

The D6 record remains authoritative for:

- parent history linkage;
- observed time;
- declared authority reference;
- complete checkpoint structure.

D9 does not duplicate those fields.

## DSR component

The manifest binds one exact D8 record:

```text
D8 record SHA-256
record kind
base revision/hash
result-state hash
```

For a branch-head record it also carries:

```text
branch_ref
```

For a merge record it carries the exact:

```text
source_branch_refs
source_head_sha256s
```

The D8 record remains authoritative for branch artifact identity, source-head CAS, and merge provenance.

## Manifest identity

The deterministic manifest JSON is encoded as UTF-8 with sorted keys and compact separators.

$$
H(W_H)=\operatorname{SHA256}(\operatorname{CanonicalJSON}(W_H))
$$

This is a new cross-domain identity.

It is **not** equal to either the SEDB checkpoint hash or the DSR result-state hash.

## Historical validity vs currentness

D9 deliberately separates:

```text
manifest hash valid
reservoir record exists and matches
DSR record exists and matches
reservoir record is current stream head
DSR record is current
```

A manifest remains historically valid after either subsystem advances.

It ceases to be a current world head when either side no longer points at the bound position.

For DSR branch-head records:

```text
current = branch current head == bound D8 record SHA
```

For DSR merge records:

```text
current = every source branch current head == merge-bound source head SHA
```

Therefore:

$$
\boxed{
\text{Historical Validity}
\neq
\text{Current World Head}
}
$$

## No mutation authority

D9 is read-only.

It does not:

- move SEDB checkpoint heads;
- move DSR branch heads;
- commit a DSR merge;
- mutate SEDB entities;
- create RAL authority;
- imply network consensus.

## Relationship to RAL / D7

D7 can externally anchor exact D6 checkpoint-history records in the existing RAL/CTCL ledger.

A future profile can similarly anchor the D9 manifest SHA-256 if a single externally retained world-head anchor is desired.

That future anchor should bind `H(W_H)` as evidence rather than reinterpret either underlying identity.

## Why this is not a monolithic world state

The manifest is intentionally tiny.

It says:

> this persistent reservoir position and this dynamic DSR computation position together define one synchronized logical world head.

It does **not** serialize the world.

The actual materialized state remains distributed across the reservoir, DSR artifacts, caches, and future placement layers.
