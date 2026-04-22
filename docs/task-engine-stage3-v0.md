# AgentFirst Stage 3 Task Engine v0

## Scope

Stage 3 adds a narrow but real commitment-first task ownership layer over the Stage 1 canonical store and Stage 2 policy engine.

Implemented in `src/agentfirst_storage/task_engine.py`, the engine supports:

- commitment creation from durable origins such as message events
- explicit lifecycle transitions across `captured`, `active`, `waiting`, `blocked`, `delegated`, `completed`, `failed`, and `canceled`
- active task attention records with next review and last meaningful activity fields
- distinct waiting conditions and blocker records
- meaningful progress updates with internal or user-visible visibility metadata
- proof-gated completion for consequential commitments
- review-driven continuation, staleness detection, and escalation representation
- approval-stall escalation when Stage 2 policy decisions create pending approval records for commitments

## Lifecycle Behavior

The task engine enforces a state machine in code. Callers do not mutate commitment status directly through conversation state. The implemented transition map permits normal flow from capture to active work, waiting, blocked, delegated, completion, failure, or cancellation, while terminal states cannot transition further.

Consequential commitment types require verified completion proof. The current proof-required types are:

- `consequential`
- `external_action`
- `tool_execution`
- `research`
- `delivery`

Callers can also set `completion_criteria["proof_required"]` explicitly.

## Attention Model

Active commitments get task attention records through `activate_commitment`. Attention records carry:

- current owner
- attention state
- next review time
- last meaningful activity time
- urgency score
- escalation state

`review_due_commitments` implements the v0 review path. It detects:

- active commitments whose review time has arrived
- stale active or delegated commitments
- waiting conditions whose review or expected resolution horizon has arrived
- approval records tied to commitments that are still requested

## Waiting vs Blocked

Waiting and blocked are intentionally separate.

Waiting uses `waiting_conditions` with waiting type, optional reference, expected resolution time, review time, timeout policy reference, and active/expired/canceled status semantics.

Blocked uses `blocker_records` with blocker type, evidence refs, resolution options, and `requires_human_decision`. A human-decision blocker immediately creates an escalation representation.

## Escalation Representation

Stage 3 does not add a new escalation table. Escalation is represented through existing v0 objects:

- `audit_events` with `event_type = "task_escalation"`
- `event_log` entries with `event_type = "task_escalation_recorded"`
- user-visible `progress_updates`
- updated attention `escalation_state`

This keeps the package inside the v0 object model while creating a real path for the later channel stage to surface escalations.

## Policy Integration

The task engine does not reimplement policy. It recognizes approval stalls from Stage 2 by joining `approval_records` to `policy_decisions` where the decision object is a commitment. Pending approvals become task escalations during review.

This gives later channel and tool packages a direct path:

1. evaluate consequential work through `PolicyEngine`
2. attach the policy decision to a commitment
3. let task review surface stalled approvals as commitment escalations

## Out of Scope

Stage 3 intentionally does not implement:

- Telegram-first channel routing
- outbound channel delivery
- broad workflow orchestration
- rich project management
- full scheduler daemon

Those belong to later packages. The current layer is the durable task machinery those packages will drive.
