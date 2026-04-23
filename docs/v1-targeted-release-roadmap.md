# AgentFirst V1 Targeted Release Roadmap

## Purpose
This document captures intentionally deferred work for a later targeted release, so the current build can stay focused on functional core behavior rather than premature polish.

## Current Judgment
AgentFirst should **not** prioritize a bundled onboarding LLM until the core product is reliably functional, installable, and supportable without it.

In plain terms: do not add chrome to a non-functioning car.

## Deferred Item: Optional Local Onboarding Guide

### Status
Deferred for later polish and release-hardening.

### Problem
OpenClaw-style setup remains too painful and unapproachable for ordinary users. Even when the core product is promising, installation friction and confusing recovery flows will block adoption.

### Proposed Direction
Bundle an **optional, very small local LLM** with AgentFirst as a guided onboarding and troubleshooting assistant.

### Intended Role
The bundled model should help with:
- first-run onboarding
- install/setup walkthroughs
- plain-English explanation of failures
- repair guidance and next-step suggestions
- local help over docs, config, and environment checks

### Explicit Non-Goals
The bundled model should **not** become responsible for:
- canonical memory
- policy or authority decisions
- security boundaries
- core orchestration
- autonomous background control
- any state mutation that must be deterministic and auditable

## Architectural Recommendation
When this work is picked up later, prefer a three-layer shape:

1. **Deterministic core**
   - product remains useful without any model
   - core actions remain scripted, auditable, and bounded

2. **Optional local guide**
   - tiny bundled model
   - assists with onboarding, explanation, and recovery
   - removable/disableable

3. **Deterministic fallback**
   - if the guide cannot help, product falls back to explicit diagnostics and scripted repair instructions
   - never fake confidence

## Suggested Entry Criteria
Do not begin this work until most of the following are true:
- core install path is already mostly stable
- first-run onboarding flow is defined
- primary operator workflows are functioning end-to-end
- common failure cases are understood well enough to encode deterministic checks
- release packaging/distribution target is clearer

## Suggested Future Deliverables
When the project is ready, this slice could produce:
- one-command installer or packaged bootstrap path
- first-run guided onboarding UX
- local diagnostic assistant wired to bounded environment checks
- help surface over local docs and configuration
- clear escalation path when the local model is insufficient

## Why This Is Deferred
Right now, the more important work is getting the car to run:
- reliable core workflows
- installability
- bounded administration
- validation coverage
- stable operator/user experience

The onboarding guide becomes valuable once it improves an already-functioning product instead of compensating for missing fundamentals.
