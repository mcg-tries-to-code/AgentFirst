# Stage 1 Validation

Validation command:

```bash
PYTHONPATH=src python3 scripts/validate_stage1.py
```

The validation flow creates a temporary SQLite database and artifact root, then proves:

- administrator bootstrap creates or returns a single primary administrator user
- the first additional user is created through the generic `create_user` path
- representative records can be created, stored, and retrieved for every required Stage 1 object family
- a shared context can contain both the administrator and a generic additional user
- policy decision and audit records can be linked to a tool invocation
- append-only events are emitted for representative object creation and consequential action completion
- filesystem artifacts can be written and referenced from canonical rows

Expected proof shape:

- JSON output with `"ok": true`
- `created_and_retrieved` listing the representative object labels
- nonzero `event_log_rows`
- `generic_user_path_reused: true`
- `shared_context_member_count: 2`
- a policy decision such as `allow_with_logging`

Last local run:

```json
{
  "created_and_retrieved": [
    "admin",
    "agent",
    "artifact",
    "attention",
    "audit_event",
    "authority_grant",
    "blocker",
    "channel_identity",
    "classification_rule",
    "commitment",
    "completion_proof",
    "corpus",
    "extra_user",
    "memory",
    "message",
    "policy",
    "policy_decision",
    "progress_update",
    "project",
    "research",
    "search",
    "shared_context",
    "sub_agent_run",
    "thread",
    "tool_capability",
    "tool_invocation",
    "waiting_condition"
  ],
  "event_log_rows": 33,
  "generic_user_path_reused": true,
  "ok": true,
  "policy_decision": "allow_with_logging",
  "shared_context_member_count": 2
}
```
