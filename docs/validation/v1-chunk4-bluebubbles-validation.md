# AgentFirst V1 Chunk 4 BlueBubbles / iMessage Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk4_bluebubbles.py
```

## Result

Passed.

Observed validation output included:
- `ok: true`
- unknown inbound intent: `enrollment_required`
- unknown trusted tables unchanged: `true`
- pairing request entered `pairing_requested`
- pairing trusted tables unchanged: `true`
- unsupported group intent: `unsupported_thread_contained`
- direct thread mode: `direct`
- direct thread behavior: `direct_commitment_enabled`
- allowed outbound status: `bluebubbles_request_prepared`
- gated outbound status: `awaiting_policy_approval`
- suspended inbound contained: `true`
- suspended outbound blocked: `true`
- authority decision count: `4`
- policy decision count: `6`
- policy audit count: `2`

## Coverage

The script validates the V1 Chunk 4 gates:
- unknown BlueBubbles/iMessage first contact is contained and audit-linked
- pairing requests do not create trusted users, channel identities, threads, messages, or commitments
- enrollment-first trusted inbound routing is required
- inbound authority checks are recorded for enrolled sender identities
- direct 1:1 iMessage thread semantics are explicit
- group/multi-recipient iMessage input is suppressed and audit-linked
- outbound sends require thread authority and enrolled-recipient linkage before transport preparation
- policy-gated outbound behavior remains audit-linked
- suspended enrollment prevents both trusted inbound and outbound

## Adjacent Regression Commands

These were also run successfully after the Chunk 4 changes:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk3_telegram.py
```

## Residual Risk

The validation uses prepared BlueBubbles API request artifacts, not live BlueBubbles server delivery.

The implementation intentionally supports only direct 1:1 iMessage threads. Group/shared iMessage routing, deterministic lane binding from the external family manifests, and per-recipient group membership authority remain future work.
