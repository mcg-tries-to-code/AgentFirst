# AgentFirst V1 Feature 5 Real Inbox

## Status
Implemented bounded local slice.

This is not a claim that AgentFirst has a live production inbox. The implementation is a truthful read-only surface over canonical local SQLite state.

## Purpose
Convert the multimode chat scaffold into a truthful inbox surface over canonical local state.

The immediate problem is not styling. The immediate problem is that AgentFirst already stores meaningful thread, message, approval, failure, and lane information, but the TUI chat surface still behaves like a conceptual mock-up.

Feature 5 closes that gap without pretending that local mirrored truth is the same as live provider synchronization.

## Core judgment
The inbox should be **real, bounded, and honest**.

That means:
- show actual stored thread/message state where it exists
- show derived review state explicitly as derived
- never fabricate live send or receive status
- keep transport/provider gaps visible

## Proposed bounded inbox model

### 1. Canonical sources
The inbox view should read from canonical or already-established bounded sources such as:
- `threads`
- `message_events`
- `commitments` when thread-linked work exists
- `approval_records` when a thread is awaiting approval-gated action
- lane metadata/checkpoint context where relevant to the viewed thread

### 2. Derived inbox state
The inbox may derive, but must label as derived:
- unread or review-needed state
- last activity summary
- blocked or unsendable badge state
- draft presence

### 3. Thread states that must be disclosed explicitly
- empty / no messages
- local-only mirrored history
- monitored but not sendable
- approval-gated outbound state
- enrollment-degraded or suspended participant state
- thread exists but user binding is incomplete

## Implemented UX shape

The trusted local TUI now exposes:

```bash
agentfirst tui --command inbox
agentfirst tui --command "inbox thread <thread_id>"
agentfirst tui --mode chat --command "chat inbox"
agentfirst tui --mode chat --command "chat thread <thread_id>"
```

`inbox` and thread detail commands report `READ-ONLY`. They do not write audit or event rows.

### Inbox list view
Shows, in bounded form:
- thread id or stable label
- owner scope
- channel/mode
- last activity timestamp
- derived review-needed marker
- blocked/approval/degraded badges
- compact summary line

### Thread detail view
Shows:
- thread metadata and lane identity
- message timeline with explicit role labels
- provenance/disclosure rows when policy, approval, or transport boundaries matter
- draft state if a local unsent draft exists

### Composer boundary
Chat compose remains a local draft scaffold and still does not imply transport delivery.

If send is absent, the UI should say so plainly.

## Implementation notes

The implementation reads existing tables and adds no schema migration:
- `threads`
- `messages`
- `commitments`
- `approval_records` joined through `policy_decisions`
- `channel_identities`
- `channel_enrollments`
- `conversation_lanes`

The inbox labels derived fields as derived:
- `review_needed`
- `sendable`
- `badges`
- `summary`

Every inbox result includes no-live-channel disclosure. Stored messages are treated as local mirrored/canonical state, not proof of current remote provider state.

## Non-goals
- full search and pagination
- live provider sync guarantees
- broad mailbox management semantics
- natural-language chat orchestration inside the inbox
- hiding degraded or partial state to look polished

## Validation plan summary
Validation should cover at minimum:
1. empty inbox
2. inbox with one active private thread
3. inbox with one shared or monitored thread that is not sendable
4. approval-gated thread with visible boundary disclosure
5. enrollment-degraded thread with explicit warning state
6. local draft state reported as unsent
7. proof that inbox reads do not mutate audit/event state unless a consequential admin action is explicitly invoked

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature5_real_inbox.py
```

The script prints JSON containing `ok`, scenario flags, `threads_seen`, degraded/approval/draft counts, and `read_only_audit_preserved`.

## Implementation expectations
- keep inbox truth layered over canonical state instead of adding a second hidden store
- preserve the distinction between canonical, mirrored, and derived state
- prefer read-first UX before send-first UX

## Delivered implementation artifacts
- `OperatorSurface.inbox_threads`
- `OperatorSurface.inbox_thread_detail`
- `TrustedOperatorTUI` commands for operator and chat-mode inbox inspection
- `scripts/validate_v1_feature5_real_inbox.py`
- updated validation documentation

## Next recommendation
After the inbox contract is frozen, proceed immediately to bounded user-management UX so thread participants, bindings, and operator actions can be governed from the same truthful local surface.
