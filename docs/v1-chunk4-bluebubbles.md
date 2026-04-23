# AgentFirst V1 Chunk 4 BlueBubbles / iMessage First-Class Surface

## Scope

V1 Chunk 4 adds BlueBubbles/iMessage as the second governed external channel.

The implementation is deliberately bounded to direct 1:1 iMessage handling. It does not add broad family policy complexity, Google integrations, provider routing, dashboard work, live BlueBubbles delivery, or group/shared iMessage semantics.

## Core Decisions

BlueBubbles trusted processing is enrollment-first:
- unknown iMessage inbound content is discovery or pairing only
- trusted inbound requires an active `channel_identities` row with `channel_type = bluebubbles` and `enrollment_state = enrolled`
- suspended, revoked, rebinding-required, or inactive bindings do not route into trusted messages, threads, or commitments
- inbound and outbound both record authority decisions when trusted channel access is evaluated

BlueBubbles addresses are normalized into channel addresses before trust checks:
- phone handles become `bluebubbles:phone:<normalized-address>`
- email handles become `bluebubbles:email:<normalized-address>`

Unknown inbound never creates:
- canonical users
- trusted channel identities
- active threads
- trusted message rows
- commitments

Contained inbound text is preserved as an enrollment artifact and linked to audit/event rows.

## Direct Thread Semantics

Chunk 4 implements only bounded V1 direct-thread handling:
- `thread_class = direct_1to1`
- thread ownership is the enrolled user
- `visibility_model = private`
- task activation is enabled for direct enrolled inbound messages
- outbound sends are allowed only for direct threads with active enrolled recipients

The thread participant metadata stamps:
- `imessage_chat_guid`
- `imessage_thread_class`
- `bluebubbles_thread_mode = direct`
- `bluebubbles_thread_behavior = direct_commitment_enabled`
- `destination_identity = bluebubbles:chat:<chat_guid>`

Group or multi-recipient iMessage input is explicitly contained with `bluebubbles_unsupported_thread_contained`. It does not create trusted work in Chunk 4.

## Family Routing Boundary

The implementation follows the family text router doctrine in bounded form:
- sender identity must be deterministic and enrolled before any assistant lane can respond
- direct 1:1 thread class is the only active iMessage thread class
- group routing is suppressed until explicit shared/group policy and membership semantics exist
- absence of certainty results in containment, not a clever reply

This chunk does not import the full family manifest policy engine into AgentFirst storage. The manifests remain the control-plane reference for future lane binding work, while Chunk 4 establishes the channel trust boundary and direct-thread object model.

## Cross-Channel Trust Rule

BlueBubbles follows the same default trust posture as Telegram and future channels should, where possible, inherit the same model:
- provider-native identity or transport trust is an input, not automatic sufficiency
- the default posture is provider gate plus AgentFirst gate
- trusted work begins only after AgentFirst enrollment, approval, identity binding, and authority checks succeed

That keeps iMessage from becoming a privileged bypass just because the provider surface feels more personal or device-linked.

## Pairing Shape

The adapter recognizes `pair`, `/pair`, `pairing`, `/pairing`, `start pair`, and `/start pair` from unknown BlueBubbles senders as pairing requests.

That path still does not create trusted users, channel identities, private threads, trusted messages, or commitments. It creates or advances contained enrollment state to `pairing_requested`, preserves the inbound text as an enrollment artifact, and records a `bluebubbles_pairing_requested` audit/event path.

Challenge issuance, challenge verification, and owner approval remain explicit before a trusted BlueBubbles channel identity is created.

## Outbound Governance

BlueBubbles outbound checks three gates before transport preparation:
1. the sponsoring user must have authority to read the BlueBubbles thread
2. the thread must contain at least one active enrolled BlueBubbles user channel identity
3. the thread mode must be direct

Only after those gates pass does the existing `share_external` policy evaluation run. Policy decisions remain attached to outbound messages, and BlueBubbles API request artifacts are produced only for policy-allowed sends.

Outbound message provenance records:
- direct thread mode and behavior
- authority policy-decision linkage
- enrolled recipient binding refs
- share-external policy decision linkage
- transport request and status metadata

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk4_bluebubbles.py
```

The validation proves:
- unknown BlueBubbles inbound becomes contained enrollment state without changing trusted tables
- `/pair` from an unknown sender becomes contained `pairing_requested` enrollment state
- enrolled direct inbound creates trusted work and stamps direct thread semantics
- group iMessage input is contained and does not create a commitment
- public outbound to an enrolled direct thread is authority-linked, policy-linked, and prepares a BlueBubbles API request
- private outbound is policy-gated
- suspended enrollment blocks both trusted inbound and outbound
- authority, policy, pairing, containment, unsupported-thread, and transport-related audit/event rows are present

## Remaining Boundaries

This chunk does not prove live BlueBubbles HTTP delivery. It prepares request artifacts through the transport boundary.

Group/shared iMessage semantics remain intentionally unavailable. Future work must define membership authority, shared-context ownership, lane binding, and outbound allowlists before group texts can become trusted operational threads.
