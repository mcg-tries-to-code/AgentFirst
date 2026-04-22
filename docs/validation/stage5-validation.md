# Stage 5 Validation Note

## Command

```bash
PYTHONPATH=src python3 scripts/validate_stage5.py
```

## Recorded Result

```json
{
  "event_log_rows": 44,
  "ok": true,
  "policy": {
    "gated_audit_event_id": "aud_5eaf7d017da94e62a90ba5ffb61bc677",
    "gated_decision": "require_primary_user_approval",
    "gated_policy_decision_id": "pdec_1338dce3dd794cde9e93d79366c7e7d8",
    "tool_invocation_status": "policy_allowed"
  },
  "real_vs_stubbed": {
    "real": [
      "Actual Telegram webhook-shaped payload accepted at adapter boundary",
      "Canonical channel identity/thread/message/commitment/progress/policy/audit writes",
      "Telegram Bot API sendMessage request generated as durable artifact",
      "Policy-gated private outbound action created approval/audit records"
    ],
    "stubbed_or_not_exercised": [
      "No live Telegram HTTPS send was attempted",
      "No Telegram token is present in the validation run",
      "Live research/provider work is validated separately by scripts/validate_research_provider.py"
    ]
  },
  "recommendation": "Stage 5 remains the Telegram-boundary proof. Run scripts/validate_research_provider.py for the separate live non-fixture research/provider proof; live Telegram delivery is proven outside this repo.",
  "telegram": {
    "live_transport": false,
    "prepared_status": "telegram_request_prepared",
    "send_request_method": "sendMessage"
  },
  "v0_scenarios": {
    "delegated_sub_agent_work_reconciled": true,
    "generic_additional_user_creation": true,
    "inbound_request_becomes_durable_task": true,
    "lightweight_project_linkage": true,
    "policy_gated_outbound_action": true,
    "waiting_vs_blocked_distinction": true
  }
}
```

IDs in the recorded output are generated per run; the stable validation claims are the statuses, decisions, scenario booleans, and transport disclosure.

## Acceptance Mapping

- Real Telegram-facing proof path: passed at the prepared Bot API request boundary; live HTTPS send not exercised.
- End-to-end vertical slice: passed across inbound Telegram payload, identity/thread resolution, message persistence, commitment/task state, policy/audit, prepared outbound Telegram request, sub-agent delegation, waiting/blocking, project linkage, and completion proof.
- Required v0 scenario validation: passed for the six required scenario booleans in `scripts/validate_stage5.py`.
- v0 completion package: this note plus `docs/stage5-real-telegram-v0.md` explicitly state Telegram-boundary requirements. The final non-fixture research/provider proof is documented in `docs/validation/research-provider-validation.md`.

## Recommendation

Do not use this Stage 5 validation alone to claim live Telegram delivery. The non-fixture research/provider gap is covered by `scripts/validate_research_provider.py`; live Telegram send proof remains outside this repo.
