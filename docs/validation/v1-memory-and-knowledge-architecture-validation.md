# AgentFirst V1 Memory and Knowledge Architecture Validation

## Purpose
Define the bounded validation criteria for the memory store architecture, knowledge/wiki architecture, memory-to-wiki contract, and shared guidance layer before implementation resumes.

This is an architecture-validation artifact, not an implementation-complete claim.

## Validation Mode
This document defines what later implementation must prove.

At this stage, validation is specification-oriented:
- contract completeness
- boundary clarity
- testability of lifecycle and reconciliation behavior
- explicit separation between canonical state, memory, wiki, and guidance

## Documents Validated Together
- `docs/v1-memory-store-architecture.md`
- `docs/v1-knowledge-wiki-architecture.md`
- `docs/v1-memory-knowledge-contract.md`
- `docs/v1-shared-guidance-layer-architecture.md`
- `docs/v1-chunk8-memory-retrieval.md`
- `docs/v1-requirements-reconciliation.md`
- `docs/v1-feature3-minimal-command-surface.md`

## Validation Targets

### A. Memory Store Validation Targets
Implementation must prove that:

1. **source traceability exists**
   - a long-term memory item can be traced back to source evidence or source-memory anchors
2. **lifecycle separation exists**
   - short-term, mid-term, and long-term memory behavior are distinguishable in bounded tests
3. **checkpointing is selective**
   - checkpoint-before-reset preserves durable signal without dumping raw transcript noise indiscriminately
4. **scoped retrieval remains governed**
   - retrieval names scopes explicitly and remains authority-bound
5. **conflict and supersession are represented explicitly**
   - the implementation can mark memory items conflicted or superseded as first-class states
6. **canonical-state separation holds**
   - canonical operational truth is not stored only as memory

### B. Knowledge/Wiki Validation Targets
Implementation must prove that:

1. **reconciliation classification works**
   - a new source or memory candidate can be classified as confirm, refine, conflict, new concept/entity, open question, confidence change, or supersede
2. **citations persist**
   - wiki updates preserve source anchors
3. **confidence persists**
   - wiki claims carry confidence state through retrieval and revision
4. **conflicts remain visible**
   - conflicting evidence is represented instead of silently flattened away
5. **open questions are explicit**
   - unresolved issues can be retrieved as durable wiki objects or sections
6. **derived-layer separation holds**
   - the wiki remains source-grounded derived knowledge rather than a raw dump of memory records

### C. Shared Guidance Validation Targets
Implementation must prove that:

1. **guidance remains distinct**
   - shared mission/vision/values/identity are distinguishable from memory and canonical state
2. **inheritance or translation is inspectable**
   - a user or agent context can reference shared guidance without flattening identity distinctions
3. **revision authority is explicit**
   - authorship, stewarding authority, and revision metadata are inspectable
4. **guidance is not silently mutated by other layers**
   - memory compaction and wiki reconciliation do not implicitly rewrite guidance objects

### D. Cross-Layer Contract Validation Targets
Implementation must prove that:

1. **memory-to-wiki is a controlled handoff**
   - promotion creates candidates for reconciliation instead of directly publishing knowledge
2. **store identity survives retrieval**
   - coordinated retrieval can distinguish memory results from wiki results
3. **wiki does not mutate canonical state**
   - wiki edits cannot act as canonical state writes by accident
4. **memory compaction does not masquerade as settled truth**
   - compacted summaries retain uncertainty and provenance
5. **replaceability remains plausible**
   - alternate memory or wiki engines can satisfy the contracts without rewriting all dependents

## Required Bounded Validation Scenarios

### Scenario 1. `/new` Checkpoint Before Reset
A bounded validation should show:
- short-term lane context exists
- `/new` checkpoints selective durable signal into mid-term or long-term memory outputs
- ephemeral noise is not blindly retained
- lane active context is cleared
- canonical operational state is unchanged

### Scenario 2. `/restart` Checkpoint Before Reinitialization
A bounded validation should show:
- checkpoint occurs before runtime reinitialization
- lane identity and runtime reset semantics are distinguishable from `/new`
- long-term retained memory survives the restart

### Scenario 3. Long-Term Memory Provenance
A bounded validation should show:
- a durable fact or preference memory item
- source refs pointing back to evidence
- confidence state
- later conflict or supersession update

### Scenario 4. Wiki Reconciliation From Memory Candidate
A bounded validation should show:
- a memory item emits a wiki candidate
- the wiki classifies it through reconciliation
- resulting wiki content keeps citations and confidence
- conflict or open-question creation is possible if evidence is mixed

### Scenario 5. Cross-Scope Retrieval Governance
A bounded validation should show:
- explicit requested scopes
- authority approval or denial
- denied cross-scope retrieval returns no leaked results
- returned results preserve provenance and store identity

### Scenario 6. Guidance Inheritance or Translation
A bounded validation should show:
- a shared guidance object at family/team scope
- a user or agent context referencing that guidance through explicit inheritance or translation
- inspectable revision and stewardship metadata

## Evidence Expected From Later Implementation
When code resumes, the validation package should include:

### Contract-level evidence
- doc-to-code mapping showing each contract surface in schema and service code
- named result shapes for memory, wiki, and guidance operations

### Executable evidence
- validation scripts under `scripts/`
- local deterministic fixtures for scopes, lanes, sources, and candidate updates
- machine-readable pass/fail output for each bounded scenario

### Regression evidence
- confirmation that Chunk 8 governed retrieval guarantees still hold
- confirmation that Feature 3 reserved-command boundaries are replaced only where explicitly intended

## Build Criteria Finalized
Architecture is considered build-ready when the repo now has:

1. an explicit memory-store architecture doc
2. an explicit knowledge/wiki architecture doc
3. an explicit memory-to-wiki and layer-boundary contract doc
4. an explicit shared-guidance-layer architecture doc
5. a validation artifact that turns the architecture into bounded acceptance criteria
6. a clear statement that Feature 4 remains paused pending review of these docs

## Validation Criteria Finalized
The architecture is considered validation-ready when later implementation can be tested for:

1. provenance-rich memory retention
2. selective checkpointing and lifecycle separation
3. authority-bound scoped retrieval
4. reconciliation-based wiki updates
5. visible confidence, conflict, and open-question handling
6. distinct shared-guidance authorship and inheritance handling
7. non-collapse of canonical state, memory, wiki, and guidance
8. plausible engine replaceability behind stable contracts

## Recommended First Post-Spec Implementation Slice
Resume with a narrow Feature 4 slice that implements only:

1. lane identity scaffolding
2. short-term active context representation
3. checkpoint artifact creation for `/new` and `/restart`
4. explicit mid-term memory representation
5. transparent checkpoint output
6. no wiki write path beyond optional candidate-emission scaffolding

That is the safest first coding step because it exercises the memory contract without prematurely hardening wiki behavior or collapsing architectural boundaries.
