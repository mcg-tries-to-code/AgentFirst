# AgentFirst V1 Chunk 1 Enrollment and Channel-Binding Foundation

## Scope

V1 Chunk 1 changes the external-channel trust boundary from message-first to enrollment-first.

The implemented security foundation covers the current external inbound surface: Telegram. The storage model is channel-neutral enough to apply to BlueBubbles/iMessage and future external channels without treating passive discovery as proof of identity.

## Core Decision

Unknown external inbound contact is discovery only.

It must not create:
- canonical user rows
- trusted `channel_identities`
- active private threads
- canonical trusted messages
- commitments or progress updates

Unauthorized inbound content is preserved only as a contained enrollment artifact with audit/event linkage.

## State Model

Discovery is represented separately from trusted binding:
- `external_channel_discoveries` records observed channel reachability.
- `channel_enrollments` records the authorization lifecycle.
- `channel_identities` remains the trusted binding surface and now carries `enrollment_id`, `enrollment_state`, and `binding_generation`.

Bounded V1 enrollment states:
- `discovered`
- `pairing_requested`
- `challenge_issued`
- `challenge_verified`
- `awaiting_owner_approval`
- `enrolled`
- `suspended`
- `rebinding_required`
- `recovery_requested`
- `revoked`
- `denied`
- `expired`

Trusted inbound activation requires an active Telegram `channel_identities` row with `enrollment_state = enrolled`.

## Pairing and Approval

The V1 Chunk 1 Telegram flow is:
1. observe inbound identity as discovery only
2. issue an enrollment challenge
3. verify the challenge out of band
4. require owner approval
5. create the trusted channel identity and allow trusted thread activation

The challenge artifact intentionally does not store a reusable secret in canonical structured state. Full UX and live code exchange are left to the production Telegram hardening chunk.

## Rebinding, Recovery, Suspension, and Revocation

The bounded V1 semantics are:
- suspension disables trusted inbound activation while preserving audit history
- revocation marks the binding revoked and makes the channel identity inactive
- rebinding marks the old binding as requiring a new challenge and owner approval
- recovery records a recovery request and requires owner approval before trust is restored

These are implemented as explicit enrollment/channel-identity state transitions with audit events.

## Telegram Boundary

`TelegramChannelService.ingest_message(update)` now gates before trusted object creation.

If the sender is not enrolled:
- discovery/enrollment records are created or updated
- inbound text is written under `enrollment/telegram/contained-inbound-...`
- an audit event records `telegram_unauthorized_inbound_contained`
- the result returns `intent = enrollment_required`
- no task intent parsing is applied

If the sender is enrolled:
- the existing Stage 4/5 trusted Telegram path is used
- user agent, bot identity, thread, message, and commitment behavior remain policy-governed

## Non-Goals

This chunk does not implement:
- full Telegram pairing UX
- live challenge delivery
- BlueBubbles/iMessage adapter behavior
- broad multi-user supervisory isolation
- Google/tool/model/memory V1 work

Those belong in later V1 chunks.
