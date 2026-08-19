# SEDB

**Semantic Evolution Database / AI-Native Unbounded Dynamic Field System**

SEDB is an experimental AI-native data infrastructure project for storing not only values, but also the evolution of fields, claims, provenance, epistemic status, and the reasons why a schema expands, converges, splits, merges, or becomes inactive.

This repository is currently in the **design and local-first development stage**. The first implementation will be developed and validated locally before larger code snapshots are synchronized to GitHub.

---

## 1. Current focus: Unbounded Dynamic Field Layer

The current development target is an AI-native dynamic field system designed for datasets whose logical field space may grow from hundreds to thousands, or potentially tens of thousands of fields.

The core principle is:

$$
\boxed{\text{Add Field} \not\Rightarrow \text{Fill Field}}
$$

A field may exist globally while remaining blank for most records. Blank is a valid state, not an error.

Let $E$ be the set of entities or records, $F$ the open-ended set of logical fields, and $D_f$ the value domain of field $f$. Then the logical data model is:

$$
V:E\times F\rightarrow D_f\cup\{\varnothing\}.
$$

Only non-empty cells need to be physically stored:

$$
C=\{(e,f,v)\mid V(e,f)\neq\varnothing\}.
$$

This separates **logical schema width** from **physical storage density**.

A database may therefore expose:

$$
|F|=10^2,\;10^3,\;10^4,\;10^5
$$

logical fields without requiring each record to materialize every field.

---

## 2. Why this is AI-native

Traditional forms and tables assume that humans first decide a relatively stable schema and then fill it.

SEDB treats schema itself as an evolving object.

An AI agent may:

1. observe a new distinction;
2. propose a new field;
3. check whether an equivalent field already exists;
4. register the field;
5. optionally fill only relevant records;
6. evaluate whether the field remains useful;
7. converge, merge, split, deprecate, or reactivate the field;
8. preserve the reason and provenance of every such decision.

The intended loop is:

$$
\text{Observe}
\rightarrow
\text{Propose Field}
\rightarrow
\text{Deduplicate}
\rightarrow
\text{Register}
\rightarrow
\text{Optional Fill}
\rightarrow
\text{Evaluate}
\rightarrow
\text{Expand / Converge}
\rightarrow
\text{Repeat}.
$$

This is closer to a true AI-native "form": the form does not need to be complete before data collection begins.

---

## 3. Field lifecycle

Fields are not merely added or deleted. They have an explicit lifecycle.

Initial states are expected to include:

- `Proposed`
- `Active`
- `Converged`
- `Reactivated`
- `Merged`
- `Split`
- `Deprecated`

A converged field is **not automatically deleted**. It means that the system currently has insufficient reason to keep expanding or actively requesting that dimension.

Every convergence decision should preserve an evaluation record such as:

- reason;
- evidence;
- coverage;
- missing rate;
- usefulness or discriminatory value;
- retrieval / computation cost;
- evaluator;
- timestamp;
- reversibility;
- provenance.

Conceptually:

$$
R_f=(\text{reason},\text{evidence},\text{metrics},\text{evaluator},\text{time},\text{reversible}).
$$

The system should be able to answer not only:

> What fields exist?

but also:

> Why does this field exist, why was it converged, and under what conditions should it be reactivated?

---

## 4. Proposed storage architecture

The first implementation is expected to use a sparse logical-field architecture rather than a physically ultra-wide SQL table.

Planned core components:

| Component | Responsibility |
|---|---|
| `entities` | Records / research objects / observed objects |
| `field_registry` | Dynamic field definitions and semantic metadata |
| `cells` | Sparse non-empty values |
| `field_events` | Add / rename / split / merge / converge / reactivate history |
| `field_evaluations` | Reasons and metrics behind field governance decisions |
| `field_proposals` | AI-generated candidate fields |
| `views` | Task-specific projections over large field spaces |
| `provenance` | Source and derivation tracking |
| `search_index` | Search, filtering, classification and retrieval support |

The first local prototype is currently expected to use **Python + SQLite + a browser-based UI**, while keeping the logical model portable enough for later PostgreSQL, DuckDB, Parquet, or distributed implementations.

---

## 5. Task-local views

A global schema may be extremely large while a particular task needs only a small subset.

For a query or task $Q$, the system should construct an effective field support:

$$
F_Q\subseteq F.
$$

For example, a database may contain thousands of fields while a particular research classification task activates only a few dozen.

This avoids confusing:

$$
\text{available dimensions}
$$

with:

$$
\text{currently useful dimensions}.
$$

The UI therefore should not behave like a conventional spreadsheet that renders ten thousand columns at once. Planned views include:

- **Matrix View** — sparse wide-table editing with virtualization;
- **Entity View** — inspect known values for one record;
- **Field View** — inspect one field across records and its lifecycle;
- **Task View** — project only the fields relevant to the current task.

---

## 6. Initial MVP boundary

The first local MVP is intended to validate the architecture rather than maximize features.

Target capabilities:

- 10,000+ logical fields;
- legal blank cells;
- dynamic field creation;
- sparse value storage;
- field search and filtering;
- field lifecycle tracking;
- convergence with mandatory reason records;
- reactivation of converged fields;
- task-local field projections;
- CSV / JSONL import and export;
- AI field-proposal API boundary;
- provenance and audit history;
- reproducible tests for large sparse schemas.

Not yet claimed:

- production readiness;
- distributed scale;
- autonomous schema governance without review;
- replacement of relational, graph, vector, or document databases in all workloads.

---

## 7. Relationship to SEDB

SEDB originally focuses on semantic evolution: claims, versions, provenance, epistemic status, lineage, and the question:

> **Why did knowledge become what it is now?**

The Unbounded Dynamic Field Layer extends this idea to schema evolution itself:

> **Why does this field exist, what does it mean, when should it be used, and why did its status change?**

The intended direction is therefore not merely a flexible database schema, but a system in which **data, fields, and schema-governance decisions are all first-class evolving objects**.

---

## 8. Development strategy

For the current phase:

$$
\boxed{\text{Local Development} \rightarrow \text{Validation} \rightarrow \text{Stable Snapshot} \rightarrow \text{GitHub}}
$$

The project will be developed locally first because the application is expected to change rapidly at the schema, storage, UI, and agent-governance layers. GitHub will initially serve as the stable public anchor and later receive tested snapshots rather than every experimental local mutation.

---

## Status

**Stage:** Architecture defined / local implementation pending  
**Repository role:** Public anchor and stable snapshot destination  
**Current priority:** Unbounded Dynamic Field Layer MVP
