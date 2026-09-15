# D11 Physical Placement Resolver + Verified Fetch v0.1

**Status:** Experimental world-materialization infrastructure  
**Repository:** SEDB experimental project workspace  
**Project:** `projects/isql-world-materializer`

## Purpose

The preceding ISQL/SEDB work separates semantic addressing from exact identity:

$$
Q
\rightarrow
A_S
\rightarrow
\mathcal C
\rightarrow
A_I
$$

D11 adds the missing physical resolution plane:

$$
\boxed{
R_P:
A_I\times C_t
\rightarrow
\mathcal L_t
}
$$

and the full local fetch path:

$$
\boxed{
A_I
\rightarrow
R_P(A_I,C_t)
\rightarrow
\mathcal L_t
\rightarrow
\operatorname{Fetch}
\rightarrow
\operatorname{Verify}(A_I)
}
$$

The central rule is:

$$
\boxed{
\text{Fetch}
\neq
\text{Trust}
}
$$

A placement only tells the runtime where candidate bytes may exist. The bytes are trusted only after recomputing the exact content identity.

## Exact content identity

D11 v0.1 defines:

```text
ExactContentIdentity(
  algorithm = "sha256",
  digest = 64 lowercase hex characters
)
```

The canonical textual reference is:

```text
sha256:<digest>
```

Only SHA-256 is enabled in v0.1. This is an implementation profile boundary, not a claim that the Meta-Core can never support other exact-identity algorithms.

## Placement record

One placement contains:

```text
exact identity
placement_id
provider_id
object_key
size_bytes
region
tier
priority
enabled
```

The placement metadata is not part of the content identity.

Therefore:

$$
\boxed{
\text{Placement Migration}
\neq
\text{State Mutation}
}
$$

and:

$$
\boxed{
\text{Replication}
\neq
\text{Identity Multiplication}
}
$$

Multiple placement records may point to the same exact content identity.

## Derived placement catalog

`PlacementCatalog` is a mutable SQLite lookup catalog.

It is explicitly **derived infrastructure**:

- records may be added or removed;
- metadata replacement requires an explicit `replace=True`;
- exact duplicate registration is idempotent;
- the whole catalog can be rebuilt with `replace_all()`.

The catalog is not a canonical state source.

## Resolution policy

`PhysicalPlacementResolver` can filter by:

- allowed provider IDs;
- allowed tiers;
- maximum object size.

It can also prefer one region.

The v0.1 ranking order is:

```text
preferred-region match
-> placement priority
-> placement ID
```

This is a replaceable local policy, not a protocol-level global ordering law.

## Local provider

D11 v0.1 ships only `LocalDirectoryProvider`.

Object keys are canonical relative POSIX paths. The provider rejects:

- absolute paths;
- `.` / `..` traversal;
- backslash path syntax;
- noncanonical duplicate separators/trailing separators;
- resolved paths that leave the configured provider root;
- non-regular files;
- objects exceeding the read limit.

A symbolic link that resolves outside the provider root is rejected.

The v0.1 local provider is a correctness/test provider. It does not claim protection from an attacker with arbitrary concurrent filesystem replacement privileges.

## Verified fetch

`VerifiedFetcher` receives one requested `ExactContentIdentity` and never changes it during failover.

For each resolved placement it:

1. selects the registered provider;
2. fetches at most the declared placement size;
3. requires exact byte length equality;
4. recomputes SHA-256 over the returned bytes;
5. accepts the bytes only if the digest equals the requested identity.

A failed placement may be skipped.

Examples of failover conditions:

- provider unavailable;
- object unavailable;
- resolved path escape;
- object too large;
- byte length mismatch;
- digest mismatch.

If every eligible placement fails:

```text
FETCH_ALL_PLACEMENTS_FAILED
```

is returned with structured per-placement attempts.

The runtime never substitutes a different exact identity merely because a requested replica is unavailable.

Thus:

$$
\boxed{
\text{Replica Failover}
\neq
\text{Identity Failover}
}
$$

## D11 non-claims

D11 v0.1 does **not** provide:

- HTTP/S3/Azure/GCS/network providers;
- authorization or access-control semantics;
- provider authenticity;
- cryptographic placement attestation;
- content encryption;
- distributed consensus;
- network retry/backoff policy;
- partial/range proof verification;
- compute placement;
- Public ISQL wire changes.

Those concerns remain separate layers.

## Relationship to D9/D10

D9/D10 establish an exact, externally anchorable world-head identity.

D11 begins the next operational stage: resolving exact content referenced by a world into physical candidate locations and accepting bytes only after exact verification.

The architecture is therefore moving from:

```text
what state is current?
```

toward:

```text
where are the exact bytes, and can this fetched replica be proven to be those bytes?
```

A later materializer can combine D2 active-domain selection, D4/D5 partial proofs, D9 world-head identity, and D11 verified placement resolution without collapsing their responsibilities.
