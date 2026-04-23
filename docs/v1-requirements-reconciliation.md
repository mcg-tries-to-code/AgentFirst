# AgentFirst V1 Requirements Reconciliation

## Purpose

Reconcile the V1 planning surface, chunk docs, validation docs, and implemented code so the repo has a clear source-of-truth hierarchy instead of competing narratives.

## Recommended canonical source-of-truth hierarchy

1. **Executable truth: code and schema**
   - `src/agentfirst_storage/schema.py`
   - `src/agentfirst_storage/*.py`
   - these define what the system actually does now
2. **Proof of executable truth: validation scripts**
   - `scripts/validate_v1_*.py`
   - these define what is actually exercised and what each bounded acceptance claim really means
3. **Bounded design truth: chunk docs and focused architecture decisions**
   - `docs/v1-chunk*.md`
   - `docs/v1-*-decision.md`
   - these should explain intent and boundaries, but must not overrule code
4. **Program map and sequencing truth**
   - the external planning master plan referenced by this repo's implementation docs
   - this is the execution map and rationale, not the canonical implementation spec
5. **Historical or superseded analysis**
   - older stage docs, completion reports, and pre-implementation reviews
   - keep for context, but do not treat them as current truth when code disagrees

## What was reconciled

### 1. Master plan versus current repo state
- The master plan was still written as if the chunk sequence were only prospective.
- It now explicitly states that the eleven planned chunks are implemented in bounded local-validation form.
- It now treats the plan as a historical program map plus remaining-work pointer, not a second implementation spec.

### 2. Google Workspace chunk doc versus actual schema and service behavior
- Chunk 5 previously described only `credential_ref`.
- The doc now reflects the implemented migration hook `credential_secret_id` while keeping `credential_ref` as the legacy opaque path.
- This keeps the chunk doc aligned with `schema.py` and `google_workspace.py`.

### 3. Chunk 11 acceptance versus the newer secrets work
- Chunk 11 integration acceptance is real, but it does not cover the later secret-broker slice.
- The doc now says that explicitly, so secrets custody is not accidentally treated as already integrated everywhere.

### 4. Cross-platform secrets decision/review docs versus actual implementation
- Earlier secrets docs still described the work as future tense and sometimes implied missing implementation.
- They now reflect that phase-1 secrets custody is implemented:
  - `secret_records`
  - `secret_access_events`
  - `LocalEncryptedSecretVault`
  - `SecretBroker`
  - `MacOSKeychainRootKeyProvider`
  - `OperatorPassphraseRootKeyProvider`
  - Telegram brokered token path
- The docs now distinguish clearly between:
  - what is implemented now
  - what remains migration or hardening follow-on work

### 5. Architecture-target language versus current code reality in secrets
- Some earlier docs described a fuller KEK/DEK model and a `KeychainBackedSecretVault` next step.
- The implemented code instead uses a smaller phase-1 design: root-key-provider custody plus root-derived per-version encryption/MAC subkeys in a shared local vault.
- The docs now call that out explicitly rather than pretending the fuller future shape already exists.

### 6. Validation notes that had gone stale
- `docs/validation/v1-cross-platform-secrets-review-validation.md` no longer says secret tables or brokered Telegram retrieval are missing.
- `docs/validation/v1-secrets-custody-validation.md` no longer frames the entire secrets track as not yet implemented.
- Both now reflect the real phase-1 state and the remaining gaps honestly.

## Intentionally pending or not yet implemented

These remain explicit and should stay explicit:
- live Telegram, BlueBubbles, Google, and model-provider acceptance with real deployment credentials
- broad secret-broker migration beyond Telegram
- fully exercised live Google credential handling through `credential_secret_id`
- richer broker authorization and lease semantics
- possible later payload-format hardening beyond the current CBC plus HMAC phase-1 vault format
- broader remote/admin/operator surfaces beyond the current trusted-local CLI and bounded TUI model
- first-time onboarding/bootstrap for initial operator, provider, channel, and secret setup
- bounded `doctor` or repair/fix flows for common setup drift and broken local state
- a small canonical slash-command surface layered over the same governance core
- lane-aware long-lived Telegram conversation management
- explicit short-term, mid-term, and long-term memory lifecycle with checkpoint-on-`/new` and `/restart`
- a shared mission/vision/values/identity guidance layer for family or team operation, distinct from raw memory and distinct from canonical operational state
- explicit inheritance/translation rules between that shared guidance layer and individual user/agent context

## Residual disagreements that should remain explicit

1. **Chunk 11 is not the same thing as full production readiness.**
   It proves bounded local/operator acceptance, not live-service production acceptance.

2. **The secrets architecture target is broader than the current phase-1 implementation.**
   That is okay, as long as docs keep separating implemented reality from later hardening.

3. **Google credential governance is schema-ready before it is live-integration complete.**
   `credential_secret_id` exists, but most exercised validation still uses placeholder `credential_ref`.

4. **BlueBubbles is a platform-specific adapter, not a core cross-platform assumption.**
   The docs should continue saying that plainly.

## Files updated in this reconciliation pass

- the external planning master plan referenced by the reconciliation pass
- `docs/v1-chunk5-google-workspace.md`
- `docs/v1-chunk11-integration-acceptance.md`
- `docs/v1-cross-platform-secrets-decision.md`
- `docs/v1-secrets-custody-architecture.md`
- `docs/v1-cross-platform-secrets-portability-review.md`
- `docs/validation/v1-cross-platform-secrets-review-validation.md`
- `docs/validation/v1-secrets-custody-validation.md`
- `docs/v1-requirements-reconciliation.md`

## Validation and checks run

- inspected the V1 master plan, chunk docs, secrets docs, validation docs, schema, and relevant service code
- checked `schema.py` for implemented tables and fields including:
  - `channel_enrollments`
  - `google_workspace_actions`
  - `tool_invocations`
  - `memory_retrievals`
  - `model_provider_preferences`
  - `model_route_decisions`
  - `secret_records`
  - `secret_access_events`
  - `approval_records`
- reviewed implementation files including:
  - `google_workspace.py`
  - `telegram.py`
  - `secret_broker.py`
  - `cli.py`
  - `operator_surface.py`
- reviewed validation scripts including:
  - `validate_v1_chunk11_integration_acceptance.py`
  - `validate_v1_secret_broker_slice_phase_1.py`
  - `validate_v1_security_remediation_pass1.py`
- ran targeted text searches to find stale claims and confirm they were removed or updated

## Bottom line

The repo now has a cleaner truth stack:
- code and validation define what exists
- chunk docs explain bounded architecture and caveats
- the master plan explains why the sequence existed and what follow-on work remains

That keeps AgentFirst V1 architecture-driven without letting older planning language drift away from implemented reality.
