# AgentFirst V1 Shared Guidance Layer Architecture

## Purpose
Define the shared guidance layer as a distinct architectural surface for mission, vision, values, identity, and governing intent.

This layer exists so AgentFirst can be guided by durable purpose without confusing that purpose with memory, wiki knowledge, or canonical operational state.

## Status
Design/spec only.

This document finalizes the boundary that earlier reconciliation work identified as still pending.

## Why This Layer Exists
Some durable inputs shape interpretation and prioritization without being reducible to either facts or system records.

Examples:
- family mission
- team vision
- operating values
- identity statements
- governing intent or telos-like framing
- explicit behavioral guardrails derived from those materials

These inputs matter, but they should not be mixed into ordinary memory or canonical data structures by default.

## Architectural Position
AgentFirst separates:

1. **Canonical operational state**
2. **Memory store**
3. **Knowledge/wiki store**
4. **Shared guidance layer**

The shared guidance layer influences interpretation across the other layers, but remains independently authored, revised, and governed.

## Responsibilities
The shared guidance layer is responsible for:

- storing mission, vision, values, identity, and governing-intent documents
- tracking authorship and revision authority for those documents
- representing inheritance or translation rules into user, family, team, project, or agent context
- providing cited guidance references that other subsystems can consult
- preserving distinctions between shared guidance and individual preferences or memories

It is not responsible for:
- storing episodic experience
- replacing the wiki's reconciled factual synthesis
- acting as system-of-record operational state
- silently mutating user or agent identity records without an explicit authority path

## Guidance Object Model
The contract must support at least these guidance object types:

- **mission document**
- **vision document**
- **values document**
- **identity statement**
- **governing-intent document**
- **translation or inheritance rule**
- **revision note or decision**

## Required Fields
Each guidance object must support, directly or by mapping:

- `guidance_id`
- `guidance_type`
- `title`
- `scope`
- `owner_or_steward_ref`
- `content`
- `effective_at`
- `revision_metadata`
- `authority_metadata`
- `supersession_state`
- `translation_rule_refs` where applicable
- `source_or_rationale_refs` where applicable

## Scope Model
Guidance may exist at multiple scopes such as:
- family
- team
- organization
- project
- agent collective
- individual user or agent overlay

### Scope Rules
- shared guidance should usually originate above the individual lane/session level
- individual overlays may exist, but must remain distinguishable from shared guidance
- lower-level contexts may inherit or translate guidance, not automatically rewrite it

## Inheritance and Translation
This layer must define how shared guidance applies downstream.

### Inheritance
Inheritance means a lower-level context references a higher-level guidance object as applicable.

Examples:
- a family values document applies to all family-scoped agent contexts
- a team mission applies to project-specific work under that team

### Translation
Translation means a lower-level context receives a scoped interpretation of guidance without changing the original guidance document.

Examples:
- a family value becomes an agent instruction preference for a specific context
- a team identity statement becomes a project operating norm

### Required Rules
- translation must be inspectable
- translation must cite the originating guidance object
- translation must preserve scope boundaries
- translation must not silently erase local distinctions

## Relationship to Memory
Guidance is not memory.

Allowed:
- memory records may reference relevant guidance when it shaped a decision
- checkpoint summaries may note that a decision aligned with a value or mission

Not allowed by default:
- storing guidance documents as ordinary memory facts
- letting compaction rewrite or supersede shared guidance
- inferring stable guidance from one-off conversations without explicit curation

## Relationship to Wiki
Guidance is not wiki knowledge.

Allowed:
- wiki pages may cite guidance as contextual framing
- wiki syntheses may explain how guidance affects policy or prioritization

Not allowed by default:
- treating guidance documents as ordinary concept pages with no authorship boundary
- allowing wiki reconciliation to revise mission/values content implicitly

## Relationship to Canonical State
Guidance may influence canonical workflows, but it is not itself equivalent to canonical state.

Examples:
- a value may influence approval policy design
- the actual approval record remains canonical state
- a mission may shape project prioritization
- the project record remains canonical state

## Authorship and Revision Authority
Shared guidance requires explicit stewardship.

The architecture must make it possible to inspect:
- who authored a guidance object
- who can revise it
- when it became effective
- what it superseded
- what contexts inherit or translate it

Unauthenticated or implicit mutation is not acceptable.

## Retrieval Expectations
Guidance retrieval should return:
- the relevant guidance text or excerpt
- scope and applicability
- revision metadata
- authority/steward metadata
- translation or inheritance links where relevant

Guidance retrieval should not be confused with:
- memory retrieval
- wiki retrieval
- canonical record reads

## Replaceability Boundary
The guidance layer should remain modular enough that representation and retrieval can evolve without changing its architectural role.

Potentially replaceable concerns include:
- document representation
- translation-rule representation
- retrieval/ranking strategy
- revision workflow

## Build Criteria
The shared guidance layer is complete only when:

1. a written guidance-layer contract exists
2. object types and required fields are explicit
3. scope, inheritance, and translation rules are explicit
4. authorship and revision authority are explicit
5. separation from memory, wiki, and canonical state is explicit
6. retrieval expectations are explicit

## Decisions Finalized
- shared mission, vision, values, and identity remain a distinct architectural layer
- guidance influences interpretation but does not collapse into memory or wiki
- inheritance and translation must be explicit and inspectable
- authorship and revision authority are first-class requirements
