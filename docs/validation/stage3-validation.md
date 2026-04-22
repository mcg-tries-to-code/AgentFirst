# Stage 3 Validation

## Command

Run from the repository root:

```bash
PYTHONPATH=src python3 scripts/validate_stage3.py
```

## What It Proves

The validation script creates a temporary AgentFirst store and exercises the Stage 3 task-engine path:

- creates a commitment from a stored inbound message event
- transitions the commitment through `captured -> active -> waiting -> blocked -> completed`
- opens an attention record for active work
- records internal and user-visible progress updates
- creates a waiting condition with review and expected-resolution metadata
- detects a waiting-condition review/timeout horizon and records escalation
- creates a blocker record with evidence, resolution options, and human-decision signaling
- rejects completion of a consequential task without completion proof
- records verified completion proof and completes the commitment
- creates a separate review-due/stale commitment and detects both continuation and staleness signals
- creates a Stage 2 approval-gated policy decision against a commitment and detects the stalled approval path

## Passing Output Shape

The script prints JSON with `ok: true`. A representative passing run produced:

```json
{
  "approval_policy_decision": "require_primary_user_approval",
  "commitment_lifecycle": [
    "captured",
    "active",
    "waiting",
    "blocked",
    "completed"
  ],
  "internal_progress_count": 3,
  "ok": true,
  "proof_gate_rejected_without_proof": true,
  "signal_types": [
    "approval_gated_policy_decision_stalled",
    "blocker_requires_human_decision",
    "commitment_stale",
    "review_due",
    "waiting_condition_expired"
  ],
  "task_escalation_event_count": 5,
  "user_visible_progress_count": 5
}
```

## Acceptance Mapping

Stage 3 acceptance item 1 is covered by `TaskEngine.create_commitment`, `activate_commitment`, `enter_waiting`, `open_blocker`, `complete_commitment`, and `mark_failed_or_canceled`.

Stage 3 acceptance item 2 is covered by persisted attention, waiting, blocker, progress, and completion-proof records.

Stage 3 acceptance item 3 is covered by separate `waiting_conditions` and `blocker_records` rows with distinct commitment states and behaviors.

Stage 3 acceptance item 4 is covered by `review_due_commitments`, which emits review-due, waiting-expired, stale, blocker, and approval-stall signals.

Stage 3 acceptance item 5 is covered by this validation script and the passing output shape above.

Stage 3 acceptance item 6 is supported by the commitment-first API and policy-linked approval-stall path, without introducing Telegram-first channel behavior in this package.
