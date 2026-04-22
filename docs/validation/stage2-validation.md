# Stage 2 Validation

Validation command:

```bash
PYTHONPATH=src python3 scripts/validate_stage2.py
```

The validation flow creates a temporary SQLite database and artifact root, then proves:

- policy evaluation collects system/global, primary-user, and per-user policy layers
- destination trust tiers are resolved for channel, export, model provider, and tool-provider destinations
- unknown or sensitive outbound paths default toward restraint
- `external_confidential` data is bound to `origin_entity_ref`
- entity-specific allowlists, blocklists, approval requirements, and provider restrictions affect outcomes
- allow, approval-required, and deny outcomes are all persisted as `policy_decisions`
- approval-required outcomes create `approval_records`
- each governed action emits a linked `audit_events` record and append-only `event_log` row
- an outbound message stores its policy decision reference
- a tool invocation stores its policy decision reference and policy-derived status

Expected proof shape:

- JSON output with `"ok": true`
- `decisions.allow_outbound_message: "allow"`
- `decisions.approval_external_confidential: "require_primary_user_approval"`
- `decisions.deny_external_model: "deny"`
- `decisions.owner_approval_export: "require_owner_approval"`
- non-empty `policy_decision_ids`, `approval_record_ids`, and `audit_event_ids`
- `linked_policy_event_count` of at least 5

Last local run:

```json
{
  "decisions": {
    "allow_outbound_message": "allow",
    "approval_external_confidential": "require_primary_user_approval",
    "deny_external_model": "deny",
    "owner_approval_export": "require_owner_approval",
    "tool_invocation": "allow"
  },
  "external_confidential_origin": "entity:acme-nda",
  "linked_policy_event_count": 5,
  "ok": true,
  "tool_invocation_status": "policy_allowed"
}
```

