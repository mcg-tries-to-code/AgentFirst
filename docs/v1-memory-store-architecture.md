# AgentFirst V1 Memory Store Architecture

## Purpose
Define the bounded architecture for the AgentFirst memory store before Feature 4 implementation resumes.

This document specifies what the memory layer is, what it is not, what contract it must expose, and what later implementation must prove.

## Status
Design/spec only.

Feature 4 lane/reset and memory-lifecycle implementation remains paused until this architecture is reviewed and accepted.

## Architectural Position
AgentFirst has four distinct layers:

1. **Canonical operational state**
   - users, approvals, secrets, enrollments, projects, commitments, audit, and other system-of-record objects
2. **Memory store**
   - episodic experience, compacted summaries, durable retained memory
3. **Knowledge/wiki store**
   - curated, reconciled, source-grounded concept and entity knowledge
4. **Shared guidance layer**
   - mission, vision, values, identity, and governing intent

The memory store is not canonical state, not the wiki, and not the guidance layer.

## Memory Store Responsibilities
The memory store is responsible for:

- short-term active lane or session context
- mid-term checkpoint and compaction artifacts for resumability
- long-term retained memory records
- checkpoint-before-reset behavior for `/new` and `/restart`
- scoped governed retrieval
- provenance-bearing promotion decisions
- conflict, confidence, and supersession tracking
- candidate emission into the wiki reconciliation path

The memory store is not responsible for:

- acting as the system of record for operational truth
- replacing projects, approvals, secrets, or audit tables
- becoming a raw transcript archive with no selection discipline
- flattening uncertainty into settled facts
- directly mutating wiki pages without reconciliation

## Design Principles
1. **Memory is selective, not exhaustive.**
   Durable memory should preserve signal, not dump chat residue.
2. **Compaction is semantic, not merely shorter.**
   Checkpoints and summaries must preserve decisions, stable facts, preferences, conflicts, open questions, and provenance.
3. **Provenance is first-class.**
   Long-term memory must remain traceable to source evidence.
4. **Confidence and conflict are explicit.**
   Memory must distinguish confirmed, tentative, conflicted, superseded, unresolved, and discarded material.
5. **Scope is explicit and authority-bound.**
   Retrieval must name scopes and remain subject to authority checks.
6. **The engine is replaceable.**
   Storage backend, compaction strategy, promotion policy, and retrieval method must sit behind a stable contract.

## Memory Model

### Record Types
The contract must support at least these memory record classes:

- **event memory**: something that happened
- **decision memory**: a choice, resolution, or commitment
- **fact memory**: durable proposition believed to be useful later
- **preference memory**: stated or inferred preference with confidence and scope
- **question memory**: unresolved question, ambiguity, or follow-up
- **summary memory**: compacted checkpoint or resumable synthesis
- **relationship memory**: association between people, entities, projects, or concepts
- **source memory**: pointer to primary evidence used by other records

Implementations may add more types, but these must be representable.

### Required Fields
Each record must support, directly or by mapping:

- `memory_id`
- `memory_type`
- `owner_scope_type`
- `owner_scope_ref`
- `lane_id` or session origin where relevant
- `created_at`
- `updated_at`
- `effective_at` when different from creation time
- `source_refs`
- `content_ref` or inline bounded payload
- `confidence_state`
- `conflict_state`
- `supersession_state`
- `retention_status`
- `canonicality_classification`
- `promotion_status`
- `wiki_candidate_status`

### Canonicality Classification
Memory records may reference canonical state, but they must not silently become it.

At minimum the memory layer must distinguish:

- `derived`
- `mirror`
- `speculative`
- `scratch`
- `canonical_reference_only`

If a memory item reflects canonical truth, the canonical source must still live elsewhere.

## Scope Model
The memory contract must support explicit scopes such as:

- `user`
- `shared_context`
- `family` or `team`
- `project`
- `agent`
- `lane` or `session`

### Scope Rules
- Every memory record belongs to a declared scope.
- Retrieval requests must declare one or more scopes explicitly.
- Cross-scope retrieval is authority-gated.
- Denied scope access must not leak partial hits.
- Lane-local short-term context can exist without being promoted into durable cross-lane memory.

## Lifecycle Model
The memory architecture must represent three distinct lifecycle layers.

### 1. Short-Term Active Context
Purpose:
- current lane/session working set
- high-churn, low-durability context
- safe reset target for `/new` and `/restart`

Properties:
- may include recent conversational fragments and working notes
- must not be treated as durable truth by default
- can be checkpointed selectively before reset

### 2. Mid-Term Compacted Memory
Purpose:
- resumable summaries and checkpoint artifacts
- reduced-context continuation across sessions or resets

Properties:
- semantically compacted, not raw transcript dumps
- preserves durable signal, provenance, uncertainty, and open questions
- serves as the main bridge between short-term context and durable retention

### 3. Long-Term Retained Memory
Purpose:
- stable facts, preferences, decisions, relationships, and historically important summaries

Properties:
- selectively promoted
- provenance-bearing
- confidence-marked
- conflict-aware
- reviewable and later correctable

## Core Operations
The stable memory contract must define these operations.

### Capture or Checkpoint
Create a bounded memory artifact from active context.

Must support:
- explicit source set
- scope and lane attribution
- operator-visible description of what was kept
- omission of raw noise that does not merit retention

### Compact
Convert short-term or mid-term material into a smaller semantic form.

Must support:
- preservation of decisions, preferences, unresolved questions, conflicts, and citations
- explicit confidence handling
- explicit compaction output type

### Promote
Move or mark a memory artifact as durable long-term memory.

Must support:
- promotion reason
- retained provenance
- retained uncertainty
- supersession of older records when applicable
- optional wiki-candidate emission

### Retrieve
Return memory results from named scopes.

Must support:
- scope-explicit retrieval requests
- authority-linked retrieval decisions
- provenance-bearing results
- status for `returned`, `empty`, or `denied`

### Mark Conflicted
Annotate a memory item or cluster as contradicted by other evidence.

### Mark Superseded
Link a memory item to a newer better-supported successor.

### Emit Wiki Candidates
Produce candidate knowledge claims for wiki reconciliation without directly mutating the wiki.

### Clear or Reset Ephemeral Lane Context
Support `/new` and `/restart` semantics without deleting long-term memory or canonical state.

## Checkpoint-Before-Reset Semantics
Feature 4 implementation must follow these boundaries:

### `/new`
- checkpoints durable signal from the current lane
- clears short-term lane context
- starts a fresh active lane/session working set
- does not erase long-term retained memory
- does not mutate canonical operational state

### `/restart`
- checkpoints durable signal from the current lane
- reinitializes the active lane/session state for the same conversational lane or operator context as defined by Feature 4
- may preserve lane identity while resetting runtime context
- does not erase long-term retained memory
- does not mutate canonical operational state

Both commands must disclose:
- what was checkpointed
- what was left ephemeral and dropped
- what persisted unchanged

## Retrieval and Governance
Chunk 8 remains the baseline for governed retrieval.

The V1 memory architecture extends that work by requiring:

- lifecycle-aware retrieval across short-term, mid-term, and long-term layers
- the same explicit scope naming discipline
- the same authority linkage discipline
- provenance-bearing results that cite the memory/source basis for each returned item
- no implicit broad retrieval based on ambient identity alone

## Relationship to Wiki
The memory store may produce wiki candidates, but it does not publish settled knowledge directly.

Required rule set:
- new information can land in memory first
- compaction may identify candidate durable claims
- wiki candidates must carry provenance and confidence
- wiki publication must go through reconciliation, not direct ingestion

## Relationship to Canonical State
Canonical operational state remains outside memory.

Examples that must remain canonical-first:
- approvals
- secrets and secret custody metadata
- enrollments
- project records
- audit events
- authoritative commitments and policy decisions

Memory may reference or summarize these, but memory must not become the only location where they exist.

## Replaceability Boundary
The default V1 implementation may be simple, but dependent code must target a stable contract rather than a specific backend.

The contract must permit later replacement of:
- storage engine
- checkpoint strategy
- compaction strategy
- retrieval strategy
- promotion policy
- wiki-candidate emission policy

Dependent callers should rely on operations and stable result shapes, not storage internals.

## Implementation Implications For Feature 4
When implementation resumes, Feature 4 should build only the bounded scaffolding implied here:

1. lane identity representation
2. short-term active context representation
3. checkpoint artifact representation for mid-term memory
4. long-term memory record scaffolding
5. explicit `/new` and `/restart` checkpoint-before-reset behavior
6. transparent output showing checkpoint contents and untouched state

It should not yet attempt:
- fully general compaction intelligence
- broad ranking optimization
- automatic truth settlement
- wiki publishing logic beyond candidate emission scaffolding

## Build Criteria
The memory-store architecture is complete only when:

1. a written stable memory contract exists
2. record types and required fields are explicit
3. scopes and authority rules are explicit
4. short-term, mid-term, and long-term lifecycle layers are explicit
5. capture, compact, promote, retrieve, conflict, supersession, wiki-candidate, and reset operations are explicit
6. checkpoint-before-reset semantics for `/new` and `/restart` are explicit
7. separation from canonical state is explicit
8. plugin replacement assumptions are explicit

## Decisions Finalized
- memory remains a distinct subsystem, not a catch-all storage layer
- memory lifecycle is explicitly three-tiered
- compaction is selective and provenance-rich
- conflict and confidence are required data, not optional commentary
- memory can feed wiki reconciliation but cannot replace it
- Feature 4 remains paused until implementation follows this contract
