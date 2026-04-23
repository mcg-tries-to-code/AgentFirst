# AgentFirst V1 Secrets Custody Validation and Readiness Note

## Validation objective

Prove that AgentFirst V1 has a real, bounded secrets path for ingest, custody, retrieval, redaction, rotation, and revocation without using ordinary chat or plaintext artifact sprawl.

## Current readiness judgment

**Phase-1 ready for bounded local/operator use. Not yet fully ready for broad production rollout.**

What is now true:
- dedicated `secret_records` metadata and `secret_access_events` audit tables exist
- a trusted local CLI ingest/rotate/revoke/list path exists
- payloads are kept in a dedicated encrypted local vault
- Telegram has an end-to-end brokered retrieval path
- access, rotation, and revocation are audited

Why this is still not a full production green:
- migration is incomplete across integrations
- Google still uses a schema hook (`credential_secret_id`) more than a fully exercised live path
- broker authorization remains trusted-local oriented
- live deployment acceptance under real credentials is still outstanding

## Repo findings informing this judgment

1. `google_connections.credential_ref` remains a valid legacy opaque abstraction, and `credential_secret_id` is now the governed migration hook.
2. Telegram and BlueBubbles still keep verifier-style challenge material minimized rather than storing reusable plaintext.
3. `TelegramBotApiTransport` now supports brokered `bot_token_secret_id`, but still keeps raw `bot_token` as a compatibility fallback.
4. `AgentFirstStore.write_artifact()` is still generic plaintext artifact storage and must remain outside the secrets path.
5. `secret_broker.py` now provides the canonical bounded custody implementation for V1 phase 1.

## Executed validation evidence

Primary implemented validation script:
- `scripts/validate_v1_secret_broker_slice_phase_1.py`

It already proves:
1. secure ingest success through trusted local CLI
2. metadata-only canonical record creation
3. encrypted payload existence under dedicated secret root
4. redacted Telegram runtime transport preparation with brokered retrieval
5. access audit creation
6. rotation success
7. revocation enforcement

Related supporting evidence:
- `docs/validation/v1-secret-broker-slice-phase-1-validation.md`
- `docs/validation/v1-cross-platform-secrets-review-validation.md`

## Required V1 acceptance tests that are now satisfied in bounded form

### A. Safe ingest
Satisfied in bounded local form.
- operator can submit a secret via trusted local CLI
- terminal input can come from non-echo prompt, stdin, or local file
- canonical state stores metadata and handle, not plaintext payload

### B. At-rest custody
Satisfied in bounded local form.
- encrypted payload exists in dedicated secret store
- metadata row exists separately
- normal DB plus normal artifact tree alone is insufficient to recover plaintext
- root custody stays outside normal repo/app state

### C. Runtime retrieval and injection
Satisfied for Telegram in bounded form.
- Telegram send path can resolve token from secret handle at call time
- transport artifacts remain sanitized
- retrieval is audited

### D. Redaction
Satisfied for the validated slice.
- plaintext test tokens are absent from CLI output, artifacts, and validation output
- masked metadata remains available for operator use

### E. Rotation
Satisfied in bounded form.
- new secret version becomes current
- audit captures the rotation
- broker resolves the new version after cutover

### F. Revocation
Satisfied in bounded form.
- revoked secret is denied on subsequent use
- revocation is explicit and auditable

## Remaining acceptance still needed before broader rollout

1. live environment validation with real credentials and deployment supervision
2. broader migration beyond Telegram, especially Google and future provider/channel credentials
3. stronger broker-side authorization if more actors or remote admin paths are introduced
4. continued verification that plaintext never leaks into newly added operator, transport, or tool surfaces

## Minimum schema and service checks

Implemented additions now present:
- `secret_records` table
- `secret_access_events` table
- vault service abstraction
- broker retrieval boundary
- secret-aware Telegram transport integration

Still intentionally incomplete:
- broad integration-by-integration migration
- richer policy/lease semantics around broker access
- later payload-format hardening beyond the current phase-1 CBC plus HMAC scheme

## Fail conditions

The secrets slice should fail broader readiness if any of the following occur:
- raw secret appears in ordinary chat, docs, or validation output
- raw secret appears in normal artifact tree
- raw secret appears in event log or audit rows
- runtime integration requires manually pasting credentials into ordinary operator workflows as the primary path
- Linux/headless support regresses into a desktop-only secret-store assumption
- root encryption material is stored in repo or standard app state

## Recommended staged rollout from the current state

### Stage 1, complete
- local secret broker
- secret metadata registry
- encrypted payload store
- masked list view
- Telegram bot token migration

### Stage 2, next
- migrate Google credential references toward governed secret bindings where live credentials are used
- expand migration to additional provider/channel credentials
- keep live acceptance and redaction checks coupled to each migration

### Stage 3, later hardening
- extend same model to more integrations
- consider richer broker authorization and lease semantics
- consider payload-format hardening if needed
- add remote trusted admin surface only if actually required

## Exit gate

V1 secrets custody should be described as broadly rollout-ready only when:
- safe non-chat ingest remains in place
- secret payloads remain encrypted at rest with root custody outside repo/db/artifacts
- more than one real integration path uses brokered retrieval end to end under live acceptance
- redaction is proven across audit/log/artifact surfaces for those integrations
- rotation and revocation are demonstrated on the migrated bindings
