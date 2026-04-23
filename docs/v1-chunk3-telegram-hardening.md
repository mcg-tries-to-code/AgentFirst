# AgentFirst V1 Chunk 3 Production Telegram Surface Hardening

## Scope

V1 Chunk 3 turns the existing Telegram proof surface into a bounded V1 enrolled channel.

The implementation stays limited to Telegram. It does not add BlueBubbles/iMessage, Google, provider routing, broad memory behavior, or dashboard work.

## Core Decisions

Telegram trusted processing remains enrollment-first:
- unknown Telegram inbound content is discovery or pairing only
- trusted inbound requires an active `channel_identities` row with `enrollment_state = enrolled`
- suspended, revoked, rebinding-required, or inactive bindings do not route into trusted messages, threads, or commitments
- inbound and outbound both record authority decisions where trusted channel access is evaluated

The Telegram adapter now stamps explicit bounded thread semantics:
- `private`: one enrolled sender and the AgentFirst Telegram agent in a private chat; commitment creation remains enabled
- `shared`: a Telegram group/supergroup explicitly bound to an active shared context; shared-context authority is checked and commitment creation remains enabled
- `monitored`: a Telegram group/supergroup/channel observed through an enrolled sender but not bound as a shared context; inbound messages are stored, but task activation and outbound sends are blocked

These semantics are stored in thread participant metadata as:
- `telegram_thread_mode`
- `telegram_thread_behavior`
- `telegram_chat_type`
- `destination_identity`

Thread ownership follows the mode:
- private and monitored threads are user-owned
- shared threads are shared-context-owned with `visibility_model = shared-members`

## Cross-Channel Trust Rule

Telegram is the first fully hardened external chat adapter, not a special exemption.

The V1 trust model should be replicable across newly onboarded channels where possible:
- provider-native trust signals are inputs, not automatic sufficiency
- the default posture is provider gate plus AgentFirst gate
- promotion into trusted users, identities, threads, or commitments requires AgentFirst enrollment, approval, and authority checks even when the provider already authenticated the sender

Any future channel that cannot meet this pattern must document the exception and the compensating controls explicitly.

## Pairing Shape

The adapter recognizes explicit `/pair`, `/pairing`, `/start pair`, and `/start pairing` messages from unknown Telegram users as pairing requests.

That path still does not create trusted users, channel identities, private threads, trusted messages, or commitments. It creates or advances contained enrollment state to `pairing_requested`, preserves the inbound text as an enrollment artifact, and records a `telegram_pairing_requested` audit/event path.

Challenge issuance, challenge verification, and owner approval remain explicit steps before a trusted channel identity is created.

## Outbound Governance

Telegram outbound now checks three gates before transport preparation:
1. the sponsoring user must have authority to read the Telegram thread
2. the thread must contain at least one active enrolled Telegram user channel identity
3. monitored threads are not sendable in V1 Chunk 3

Only after those gates pass does the existing `share_external` policy evaluation run. Policy decisions remain attached to outbound messages, and Telegram Bot API request artifacts are produced only for policy-allowed sends.

Outbound message provenance now records:
- Telegram thread mode and behavior
- authority policy-decision linkage
- enrolled recipient binding refs
- share-external policy decision linkage
- transport request and status metadata

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk3_telegram.py
```

The validation proves:
- `/pair` from an unknown Telegram user becomes contained `pairing_requested` enrollment state without changing trusted tables
- enrolled private inbound creates trusted work and stamps private thread semantics
- enrolled shared inbound routes through an explicit shared context and stamps shared thread semantics
- monitored group inbound stores a message but does not create a commitment
- public outbound to an enrolled private thread is authority-linked, policy-linked, and prepares a Telegram Bot API request
- private outbound is policy-gated
- monitored outbound is blocked
- suspended enrollment blocks both trusted inbound and outbound
- authority, policy, pairing, and transport-related audit/event rows are present

## Remaining Boundaries

This chunk does not prove live Telegram HTTPS delivery. Stage 5 still validates the prepared Telegram Bot API boundary without a bot token.

Shared Telegram thread enrollment remains bounded: the trusted sender must be enrolled and the thread must be explicitly associated with a shared context. Full group roster enrollment and Telegram admin/member synchronization are future work.

This chunk also does not yet define long-lived **lane-aware** Telegram conversation management. That follow-on should let independent Telegram chats remain context-separated while sharing canonical backend truth where appropriate. The intended next-step shape is:
- stable lane identity per long-lived chat or thread
- separate ephemeral conversational context per lane
- explicit lane role or behavior such as personal, project, monitored, admin, or support
- clean interoperability with `/new`, `/restart`, memory checkpointing, and later mid-term compaction
