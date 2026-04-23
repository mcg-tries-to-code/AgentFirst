# AgentFirst Stage 4 Telegram-First Channel Integration v0

## Scope

Stage 4 adds a narrow but real Telegram-first channel adapter over the existing canonical store, policy engine, and task engine.

The adapter keeps Telegram details in channel-facing provenance, channel identities, and thread participant metadata. Canonical commitments, progress updates, policy decisions, audit events, and message events remain transport-neutral.

## Implementation Shape

The implementation lives in `src/agentfirst_storage/telegram.py`.

Primary entry points:
- `TelegramChannelService.ingest_message(update)`
- `TelegramChannelService.create_outbound_message(...)`
- `TelegramChannelService.surface_progress_update(...)`

## Inbound Flow

`ingest_message` accepts Telegram-shaped update dictionaries and:
1. normalizes Telegram message fields
2. requires an enrolled Telegram user channel identity
3. resolves or creates the user's Telegram-facing AgentFirst agent
4. resolves or creates a Telegram thread using the Telegram chat id
5. persists the inbound message as a canonical `messages` row
6. applies an explicit message-to-commitment intent path

Unknown Telegram first contact is no longer trusted by this path. It is contained as external-channel discovery/enrollment state and does not create a canonical user, trusted channel identity, active thread, canonical message, or commitment.

Supported v0 task intents:
- `/commit ...`, `commit: ...`, `todo: ...`, or `task: ...` creates and activates a commitment
- `please ...`, `remind me ...`, or `can you ...` creates and activates a commitment
- `/update ...`, `update: ...`, or `progress: ...` records progress against an explicit or latest active thread commitment

## Commitment Behavior

Created commitments:
- use `commitment_type = telegram_request`
- are owned by the user's Telegram-facing agent
- retain the inbound message as `origin_ref`
- link back to the Telegram thread through `linked_commitment_ids_json`
- are activated immediately, producing a task attention record and internal progress update through the Stage 3 task engine

Updates are recorded as canonical `progress_updates` and linked back through message provenance.

## Outbound Flow

`create_outbound_message` persists a draft outbound canonical message, evaluates `share_external` policy through `PolicyEngine`, then updates the message with:
- policy decision refs
- status derived from policy outcome
- transport status metadata
- event-log linkage

Allowed outcomes become `send_stubbed`, which means the canonical send path is ready but no real Telegram API call is attempted in Stage 4.

Approval or denial outcomes are persisted as `awaiting_policy_approval` or `blocked_by_policy`; the message is not marked as sent.

## Progress Surfacing

`surface_progress_update` turns a user-visible commitment progress update into a Telegram-ready outbound message. It resolves the originating Telegram thread from the commitment/message lineage or linked thread, then sends the update through the same policy-gated outbound path.

By default it refuses to surface internal-only progress updates.

## Tradeoffs

- Telegram chat identity is represented in thread participant metadata instead of adding Telegram-specific schema columns.
- Transport send remains stubbed, but the canonical policy/audit/message path is real.
- Intent parsing is deliberately explicit and narrow; broader language understanding can be added later without changing the canonical task path.
- Unknown inbound Telegram users are not auto-created. Explicit enrollment must bind a discovered Telegram identity to a canonical user before trusted activation.

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_stage4.py
```

The validation proves:
- explicitly enrolled inbound Telegram-shaped message becomes a durable active commitment
- a second inbound Telegram-shaped message updates that commitment
- outbound Telegram-shaped message is policy-evaluated and auditable
- user-visible progress update is surfaced through the Telegram outbound path
