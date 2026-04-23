# AgentFirst V1 Knowledge and Wiki Architecture

## Purpose
Define the bounded architecture for the AgentFirst knowledge/wiki store as a subsystem distinct from both memory and canonical operational state.

This document specifies how curated knowledge is represented, updated, reconciled, and validated.

## Status
Design/spec only.

No wiki implementation should resume or be implied by Feature 4 work unless it conforms to this architecture.

## Architectural Position
AgentFirst separates:

1. **Canonical operational state** for system-of-record truth
2. **Memory store** for episodic and retained experience
3. **Knowledge/wiki store** for curated, reconciled, source-grounded knowledge
4. **Shared guidance layer** for mission, vision, values, identity, and governing intent

The wiki is derived and maintained knowledge. It is not a raw event log, not a transcript dump, and not canonical operational state.

## Knowledge/Wiki Responsibilities
The knowledge/wiki store is responsible for:

- concept pages
- entity pages
- synthesis pages
- open-question tracking
- contradiction and disagreement representation
- confidence-marked knowledge summaries
- source-linked maintenance of durable understanding
- cross-source reconciliation of claims

The knowledge/wiki store is not responsible for:

- storing every raw message or event
- acting as the source of record for approvals, secrets, projects, or audit
- accepting new claims at face value without reconciliation
- flattening contradictory evidence into one unsupported statement
- replacing short-term or episodic memory

## Design Principles
1. **Derived, not primary.**
   Wiki content is built from evidence and synthesis, not treated as self-justifying truth.
2. **Reconciliation before update.**
   New material must be compared against existing knowledge, not appended blindly.
3. **Provenance is mandatory.**
   Each important claim must point to source evidence.
4. **Confidence is explicit.**
   The wiki must say what is strong, tentative, disputed, or unresolved.
5. **Conflicts stay visible.**
   Contradictions must be represented, not silently erased.
6. **The engine is replaceable.**
   Representation and reconciliation mechanics must remain modular behind a stable contract.

## Object Model
The contract must support at least these wiki object types.

### Concept Page
Used for stable topics, abstractions, categories, and recurring ideas.

Examples:
- a workflow concept
- a policy concept
- a medical concept
- a product or system concept

### Entity Page
Used for people, organizations, systems, projects, places, or named objects.

### Synthesis Page
Used when multiple sources and pages need a reconciled interpretation.

Examples:
- project state synthesis
- longitudinal health synthesis
- cross-source architecture synthesis

### Open-Question Page or Section
Used to track unresolved questions, ambiguities, or evidence gaps.

### Conflict Note or Conflict State
Used to represent meaningful disagreement between sources, interpretations, or time periods.

### Source Linkage Object
Used to anchor claims to memory items, documents, messages, fetched sources, or canonical references.

## Required Fields
Each wiki object must support, directly or by mapping:

- `wiki_object_id`
- `wiki_object_type`
- `title` or canonical label
- `scope`
- `subject_refs` or linked entities/concepts
- `summary`
- `claim_blocks` or equivalent structured claims
- `source_refs`
- `confidence_state`
- `conflict_state`
- `open_question_refs`
- `revision_metadata`
- `curation_status`
- `supersession_state` where applicable

## Claim Model
The wiki must support claims as structured units rather than only freeform text.

A claim should be able to represent:
- the proposition itself
- supporting evidence
- counter-evidence
- confidence level
- time relevance or effective period
- whether it is confirmed, tentative, conflicted, superseded, or unresolved

This allows page-level synthesis without losing evidentiary structure.

## Reconciliation Model
Every proposed wiki update must pass through a reconciliation path.

At minimum, reconciliation must classify the new material as one or more of:

- **confirm**: supports existing understanding
- **refine**: narrows, sharpens, or qualifies an existing claim
- **conflict**: contradicts current understanding or another cited source
- **new_concept_or_entity**: introduces a new page-worthy subject
- **open_question**: creates or sharpens an unresolved question
- **confidence_change**: raises or lowers confidence in an existing synthesis
- **supersede**: replaces a previously best-known synthesis because newer evidence is stronger

## Update Discipline
Wiki updates must:

- cite their evidence
- preserve uncertainty when uncertainty exists
- preserve conflict when conflict exists
- distinguish synthesis from direct quotation or raw source content
- retain revision metadata so changes are inspectable
- avoid copying memory summaries into the wiki as if they were already settled truth

Wiki updates must not:
- silently overwrite strong prior claims without recording the basis
- treat one fresh source as automatically authoritative
- mutate canonical operational state directly
- strip out source linkage for convenience

## Source Inputs
A wiki update may originate from:

- memory store candidates
- direct source documents
- canonical references used as evidence inputs
- research/search citations
- curated operator review flows

Regardless of input path, the wiki contract must treat the update as a reconciliation event rather than a face-value ingest.

## Relationship to Memory
The wiki and memory store cooperate but remain distinct.

### Required Boundary
- memory holds episodic and retained experience
- wiki holds curated, reconciled understanding
- memory may emit candidate claims to a wiki queue
- wiki objects may cite memory records as evidence
- wiki objects must not simply mirror every memory record

### Why the Boundary Matters
If memory and wiki collapse into one layer:
- transcript noise pollutes durable knowledge
- uncertain recollection can masquerade as settled understanding
- downstream retrieval cannot tell experience from synthesis
- later engine replacement becomes much harder

## Relationship to Canonical State
Canonical state remains the source of truth for operational objects.

The wiki may summarize canonical state or contextualize it, but it must not become the only place where those truths live.

Examples:
- a wiki page may summarize a project's history
- the canonical project record still lives in project storage
- a wiki page may explain approval policy behavior
- approval records still live in canonical approval storage

## Relationship to Shared Guidance
Shared mission, vision, values, and identity may influence how the wiki organizes or prioritizes knowledge, but they remain a separate layer.

The wiki may cite guidance documents. It must not absorb them as ordinary memory or ordinary factual wiki claims.

## Retrieval Expectations
Knowledge retrieval should return:
- synthesized understanding
- confidence state
- conflict state
- open questions
- cited evidence anchors

Knowledge retrieval should not be mistaken for:
- raw memory replay
- canonical state read APIs
- unquestioned truth detached from sources

## Replaceability Boundary
The default wiki implementation may be pragmatic, but callers must target a stable contract.

The contract must permit later replacement of:
- page/object representation
- reconciliation strategy
- confidence model
- conflict model
- source-linking strategy
- curation workflow

## Build Criteria
The knowledge/wiki architecture is complete only when:

1. a written stable wiki contract exists
2. object types are explicit
3. structured claim and source-linkage expectations are explicit
4. reconciliation classifications are explicit
5. citation, confidence, conflict, and open-question handling are explicit
6. separation from memory and canonical state is explicit
7. replaceability assumptions are explicit

## Decisions Finalized
- the wiki is a distinct derived knowledge layer
- wiki updates require reconciliation, not blind ingestion
- confidence and conflict remain first-class wiki concepts
- open questions are durable knowledge objects, not informal leftovers
- the wiki can cite memory but cannot collapse into memory
- the wiki can contextualize canonical truth but cannot replace canonical truth
