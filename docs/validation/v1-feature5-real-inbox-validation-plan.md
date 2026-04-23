# AgentFirst V1 Feature 5 Real Inbox Validation Plan

## Status
Implemented validation artifact for the bounded local inbox slice.

## Purpose
Define the minimum local validation contract for the first truthful inbox slice before implementation begins.

## Validation posture
The inbox must be validated as a **bounded local truth surface**, not as a live production transport client.

Every test should preserve these distinctions:
- canonical stored thread/message state
- mirrored transport state
- derived inbox presentation state
- local draft state

## Required scenarios

### Scenario 1. Empty inbox
Create a fresh local store with no threads or message events.

Assert:
- inbox view renders honestly
- no fake conversations appear
- output discloses the empty state clearly

### Scenario 2. One active thread with stored messages
Create one durable thread with inbound and outbound message events.

Assert:
- inbox list shows the thread
- detail view shows the message timeline in order
- role labels distinguish inbound/outbound/system context

### Scenario 3. Approval-gated outbound boundary
Attach a requested approval to a thread-linked action.

Assert:
- inbox/thread views expose approval-gated state
- the UI does not imply the outbound action already occurred

### Scenario 4. Monitored or unsendable thread
Create a thread that is stored locally but is not sendable under current governance.

Assert:
- inbox marks the thread as monitored or unsendable
- the UI does not present send affordances as if they are active

### Scenario 5. Enrollment-degraded participant state
Attach a suspended or rebinding-required channel identity/enrollment.

Assert:
- degraded binding state is visible in inbox or thread detail
- the operator can tell the issue is trust/enrollment related rather than mysterious absence

### Scenario 6. Local draft state
Create or render a local draft tied to a thread.

Assert:
- draft is labeled unsent
- no delivery metadata is fabricated

### Scenario 7. Read-only integrity
Capture audit/event counts before and after inbox inspection.

Assert:
- read-only inbox commands do not mutate audit or event state
- only explicit consequential actions, if any are later introduced, may write audit/event records

## Expected implementation-time command shape
Validation runs through a single repo script:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature5_real_inbox.py
```

The script should print JSON with at least:
- `ok`
- `scenarios`
- `threads_seen`
- `degraded_states_seen`
- `approval_states_seen`
- `read_only_audit_preserved`

The implemented script also reports `drafts_seen`, `badges_seen`, and the seeded `approval_record_id`.

## Failure conditions
The feature fails validation if it:
- fabricates inbox contents
- blurs live provider truth with local mirrored state
- hides blocked or degraded thread status
- treats unsent drafts as delivered
- mutates audit/event state during read-only inspection
