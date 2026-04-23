# AgentFirst V1 Chunk 2 Authority Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk2_authority.py
```

## Result

Passes.

The validation proves:
- ten canonical users can exist without a hardcoded single-user assumption
- supervision is represented by an explicit `authority_grants` row
- a supervisor can read the target user's private memory and channel identity only when the grant matches
- the same supervisor is denied access to an unrelated user's private memory and channel identity
- active shared-context members can read shared-context memory
- non-members are denied shared-context memory visibility
- authority decisions create policy-decision and audit records

## Representative Output

```json
{
  "ok": true,
  "multi_user": {
    "ordinary_user_count": 9,
    "user_count": 10
  },
  "allowed_supervision": {
    "channel_allowed": true,
    "memory_allowed": true
  },
  "denied_overreach": {
    "channel_allowed": false,
    "memory_allowed": false
  },
  "shared_context_visibility": {
    "active_member_allowed": true,
    "member_count": 3,
    "non_member_allowed": false
  }
}
```

## Related Regression Checks

```bash
PYTHONPATH=src python3 scripts/validate_stage1.py
PYTHONPATH=src python3 scripts/validate_v1_chunk1_enrollment.py
```

Both should continue to pass because Chunk 2 uses existing storage tables and does not change trusted Telegram enrollment semantics.
