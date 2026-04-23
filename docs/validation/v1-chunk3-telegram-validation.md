# AgentFirst V1 Chunk 3 Telegram Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk3_telegram.py
```

## Result

Passed.

Observed validation output included:
- `ok: true`
- pairing request entered `pairing_requested`
- trusted tables remained unchanged before enrollment
- private thread mode: `private`
- shared thread mode: `shared`
- monitored thread mode: `monitored`
- monitored inbound intent: `monitored_message_stored`
- allowed outbound status: `telegram_request_prepared`
- gated outbound status: `awaiting_policy_approval`
- monitored outbound blocked: `true`
- suspended inbound contained: `true`
- suspended outbound blocked: `true`
- authority decision count: `9`
- policy decision count: `11`
- policy audit count: `2`

## Coverage

The script validates the V1 Chunk 3 gates:
- unknown Telegram pairing request is contained and audit-linked
- enrollment-first trusted inbound routing is preserved
- inbound authority checks are recorded for enrolled sender identities
- private, shared, and monitored Telegram thread semantics are explicit
- shared Telegram routing requires an active shared context and membership authority
- monitored Telegram routing does not create trusted work
- outbound sends require thread authority and enrolled-recipient linkage before transport preparation
- policy-gated outbound behavior remains audit-linked
- suspended enrollment prevents both trusted inbound and outbound

## Adjacent Regression Commands

These were also run successfully after the Chunk 3 changes:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk1_enrollment.py
PYTHONPATH=src python3 scripts/validate_v1_chunk2_authority.py
PYTHONPATH=src python3 scripts/validate_stage4.py
PYTHONPATH=src python3 scripts/validate_stage5.py
```

## Residual Risk

The validation uses prepared Telegram Bot API request artifacts, not live Telegram HTTPS delivery. Group/shared thread semantics are explicit and governed, but they do not yet synchronize Telegram group membership or enroll every group participant.
