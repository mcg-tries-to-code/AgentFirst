# AgentFirst V1 Chunk 10 Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk10_audit_tui.py
```

## Scenario

The validation creates trusted local state in a temporary SQLite store:
- primary user
- local operator user
- worker user
- active project
- blocked project commitment
- active blocker requiring human decision
- suspended Telegram enrollment and channel identity
- policy decision requiring approval

It then drives `TrustedOperatorTUI` through both shell contexts.

Operator commands exercised:
- `status`
- `approvals`
- `audit`
- `users`
- `tasks`
- `failures`
- `admin approval approve ... --confirm APPROVED`

Chat scaffold commands exercised:
- `mode chat`
- `chat status`
- `chat compose ...`
- `mode operator`

## Assertions

The validation asserts:
- all operator inspection commands report `READ-ONLY`
- read-only operator inspection does not change audit or event counts
- status and failure views disclose blocked work and suspended enrollment
- approvals view exposes the pending approval
- admin approval resolution reports `ADMIN`
- the approval is updated to `approved`
- `operator_approval_resolved` is written to audit history
- chat scaffold commands report truthful non-live metadata
- chat scaffold commands do not mutate audit or event counts
- chat draft rendering reports `sent = false`
- returning to operator mode yields the operator home surface rather than an error

## Expected result

The script prints JSON with `"ok": true`, the operator commands exercised, the chat commands exercised, the resolved approval id, failure-disclosure sources, and trusted-state counts.

## Boundary note

A passing validation here does **not** mean AgentFirst has live inbox or messaging support in the TUI. It means the multimode shell is truthful, visually structured, and functionally safe within the current bounded local implementation.
