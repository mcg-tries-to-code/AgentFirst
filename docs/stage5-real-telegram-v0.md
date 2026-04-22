# AgentFirst Stage 5 Real Telegram Proof and v0 Validation

## Scope

Stage 5 tightens the Stage 4 Telegram channel path from Telegram-shaped internal flow to a real Telegram-facing boundary.

The implementation still does not claim live Telegram delivery by default. The repo now supports a Telegram Bot API `sendMessage` request boundary that can either:
- prepare a durable Telegram-bound HTTPS request artifact without sending, or
- execute the real Bot API call when a bot token is supplied and `execute_live=True`.

The validation path uses the prepared-request mode because this environment does not provide a Telegram bot token or live network proof target.

## Implementation Shape

The Stage 5 transport boundary is in `src/agentfirst_storage/telegram.py`.

Primary additions:
- `TelegramBotApiTransport`
- optional `bot_api_transport` on `TelegramChannelService`
- outbound message provenance fields for `telegram_send_request_ref`, `transport_status`, and `live_transport`
- status values for prepared or live Telegram transport outcomes

When an outbound message is policy-allowed and a `TelegramBotApiTransport` is configured, the channel service creates a Telegram Bot API `sendMessage` request and writes it under the artifact store. If live execution is disabled, the message status becomes `telegram_request_prepared`. If live execution succeeds, the message status becomes `sent`. Approval-gated or denied messages do not reach the transport boundary.

## Real vs Stubbed

Actually real in Stage 5:
- Telegram webhook-shaped inbound payloads are accepted at the channel adapter boundary.
- Telegram user identity, bot identity, thread, inbound message, commitment, attention, progress, policy, audit, and event rows are persisted in the canonical store.
- Policy-allowed outbound Telegram messages produce a concrete Telegram Bot API `sendMessage` request artifact with HTTP method, URL template, headers, and JSON body.
- Policy-gated private outbound messages create policy decisions, approval records, audit events, and blocked transport progression.
- Sub-agent delegation/reconciliation now runs through task-engine methods instead of direct status mutation.

Still stubbed or not exercised:
- No live Telegram HTTPS send is performed in validation.
- No Telegram bot token is configured in validation.
- No webhook server endpoint is started in this repo; validation calls the adapter boundary directly with a real Telegram update shape.
- Live search/research provider work is not part of the Telegram validation; it is covered by `scripts/validate_research_provider.py`.

## v0 Scenario Coverage

The Stage 5 validation script covers these v0 scenarios:
- inbound Telegram request becomes durable task
- policy-gated outbound Telegram action
- delegated sub-agent work and reconciliation
- waiting vs blocked distinction
- generic additional-user creation path
- lightweight project linkage to avoid orphaned work
- completion proof attached before final task completion
- governed tool invocation record for the Telegram send capability

## Completion Assessment

The v0 architecture proof is now substantially complete: the canonical object model, policy layer, task engine, Telegram channel layer, sub-agent delegation, project linkage, and audit/provenance path all participate in one inspectable vertical slice.

Operational v0 in this repo should still not claim live Telegram delivery from this script. The non-fixture research/provider path is now implemented separately in `agentfirst_storage.research` and validated by `scripts/validate_research_provider.py`; confirmed live Telegram delivery remains the external proof item.

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_stage5.py
```
