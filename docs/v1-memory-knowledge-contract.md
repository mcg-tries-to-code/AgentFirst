# AgentFirst V1 Memory and Knowledge Contract

## Purpose
Specify the stable interface boundary between:

- canonical operational state
- memory store
- knowledge/wiki store
- shared guidance layer

This document defines how memory and wiki cooperate without collapsing into one subsystem.

## System Boundary Contract

### Layer 0. Canonical Operational State
Owns system-of-record truth such as:
- users
- approvals
- secrets and secret custody metadata
- enrollments
- projects
- commitments
- audit and policy decisions

### Layer 1. Memory Store
Owns:
- episodic capture
- short-term active context
- mid-term checkpoint summaries
- long-term retained memory
- provenance-bearing retrieval and promotion

### Layer 2. Knowledge/Wiki Store
Owns:
- curated concept and entity knowledge
- reconciled syntheses
- open questions
- conflict-aware durable understanding

### Layer 3. Shared Guidance Layer
Owns:
- mission
- vision
- values
- identity
- governing intent and translation rules

## Non-Collapse Rules
1. canonical state must not exist only in memory
2. canonical state must not exist only in the wiki
3. memory compaction must not masquerade as settled knowledge
4. wiki synthesis must not masquerade as canonical operational truth
5. shared guidance must not be treated as ordinary memory
6. shared guidance must not be flattened into canonical state fields by default

## Memory Contract
The memory subsystem must expose stable operations for:

- `capture_checkpoint`
- `compact`
- `promote`
- `retrieve`
- `mark_conflicted`
- `mark_superseded`
- `emit_wiki_candidates`
- `clear_ephemeral_lane_context`

### Required Memory Inputs
Memory operations must be able to carry:
- scope
- lane/session origin where applicable
- source refs
- retention intent
- confidence/conflict state
- actor or system attribution where relevant

### Required Memory Outputs
Memory operations must return bounded result objects with at least:
- ids of created or touched records
- lifecycle layer affected
- provenance/source anchors
- confidence/conflict/supersession state
- machine-readable status

## Wiki Contract
The wiki subsystem must expose stable operations for:

- `propose_update`
- `reconcile_candidate`
- `apply_reconciled_update`
- `retrieve_knowledge`
- `record_open_question`
- `mark_conflict`
- `supersede_synthesis`

### Required Wiki Inputs
Wiki operations must be able to carry:
- candidate claim or page target
- source refs
- reconciliation classification
- confidence and conflict metadata
- curator or system attribution where relevant

### Required Wiki Outputs
Wiki operations must return bounded result objects with at least:
- affected object ids
- reconciliation disposition
- confidence/conflict/open-question state
- revision metadata
- cited source anchors
- machine-readable status

## Memory-to-Wiki Promotion Contract
This is the most important cooperating boundary.

### Rule 1. Memory lands first
New conversational or experiential material may land in memory first.

### Rule 2. Promotion creates candidates, not automatic truth
Memory may emit candidate claims to a wiki reconciliation queue, but it must not directly author settled wiki content.

### Rule 3. Candidate payloads must be provenance-rich
A memory-to-wiki candidate must include at least:
- candidate id
- source memory ids
- source refs
- scope
- proposed subject or page target
- proposed claim text or structured claim payload
- confidence state
- conflict indicators if known
- rationale for why the item appears durable or page-worthy

### Rule 4. Wiki must reconcile before applying
The wiki must classify each candidate as:
- confirm
- refine
- conflict
- new concept/entity
- open question
- confidence change
- supersede
- reject or defer

### Rule 5. Applied wiki content must retain evidence links
A reconciled wiki update must preserve the upstream memory/source trail.

## Retrieval Contract Across Stores
AgentFirst may later support coordinated retrieval across memory and wiki, but retrieval results must preserve store identity.

### Retrieval Rules
- callers must know whether a result came from memory or wiki
- memory results should expose episodic/provenance context
- wiki results should expose synthesis/confidence/conflict context
- coordinated retrieval must not merge them into an undifferentiated list without source typing
- cross-scope retrieval remains authority-bound

## Canonical-State Interaction Contract
Memory and wiki may reference canonical state but may not silently override it.

### Allowed Patterns
- memory item references canonical project id
- wiki page summarizes a canonical project or approval process
- canonical state is cited as an evidence source

### Forbidden Patterns
- storing the only approval truth as memory text
- updating a project record by editing a wiki synthesis alone
- treating a compacted memory summary as if it changed canonical state

## Guidance-Layer Interaction Contract
Shared guidance may influence interpretation, prioritization, ranking, or curation, but it remains a distinct source layer.

Allowed:
- memory or wiki outputs may cite applicable mission/values guidance
- retrieval may include relevant guidance references
- user or agent context may inherit selected guidance through explicit rules

Not allowed by default:
- rewriting guidance into ordinary memory facts
- treating guidance as canonical operational data
- mutating shared guidance through memory compaction or wiki reconciliation flows

## Replaceability Contract
Both memory and wiki engines must remain replaceable behind stable interfaces.

This means later changes in:
- storage backend
- ranking/retrieval strategy
- compaction method
- reconciliation method
- page representation
- confidence model
- operator curation workflow

must not require rewriting every dependent subsystem.

## Feature 4 Constraint
Feature 4 lane/reset work may implement only the bounded memory scaffolding needed for:
- lane identity
- checkpoint-before-reset
- lifecycle representation
- transparent operator-visible checkpoint output

It must not implicitly define the wiki contract by accident.

## Build Criteria Finalized
This contract layer is complete only when:

1. the four-layer system boundary is explicit
2. non-collapse rules are explicit
3. memory operations and outputs are explicit
4. wiki operations and outputs are explicit
5. memory-to-wiki promotion is defined as candidate emission plus reconciliation
6. retrieval across stores preserves store identity
7. canonical-state and guidance-layer interaction rules are explicit
8. replaceability expectations are explicit

## Decisions Finalized
- memory and wiki are distinct but cooperating subsystems
- memory promotion to wiki is a controlled handoff, not a direct write path
- coordinated retrieval may exist later, but store identity must remain visible
- canonical state, memory, wiki, and guidance are separate layers with explicit contracts
