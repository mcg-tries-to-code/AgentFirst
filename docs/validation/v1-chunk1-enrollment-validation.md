# AgentFirst V1 Chunk 1 Enrollment Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk1_enrollment.py
```

## Result

Passes.

The validation proves:
- unknown Telegram first contact is contained
- no canonical user is created from unauthorized first contact
- no trusted channel identity is created from unauthorized first contact
- no trusted thread, canonical message, or commitment is created before enrollment
- discovery and enrollment records are created for reviewable pairing
- challenge verification and owner approval create an enrolled channel identity
- trusted thread and commitment activation work after enrollment
- suspension blocks the trusted inbound path again
- containment and owner approval audit events are reconstructible

## Representative Output

```json
{
  "ok": true,
  "unauthorized_first_contact": {
    "contained": true,
    "canonical_user_created": false,
    "trusted_channel_identity_created": false,
    "trusted_thread_created": false,
    "trusted_message_created": false,
    "commitment_created": false,
    "enrollment_state": "discovered"
  },
  "enrollment_flow": {
    "challenge_state": "challenge_issued",
    "verified_state": "awaiting_owner_approval",
    "approved_state": "enrolled",
    "binding_generation": 1
  },
  "suspension": {
    "state": "suspended",
    "post_suspension_inbound_contained": true
  }
}
```

## Related Regression Checks

```bash
PYTHONPATH=src python3 scripts/validate_stage4.py
PYTHONPATH=src python3 scripts/validate_stage5.py
```

Both pass after adding explicit enrollment setup to the existing Telegram validations.
