# AgentFirst V1 Chunk 10 Auditability, Observability, Failure Handling, and Multimode Trusted TUI

## Scope

V1 Chunk 10 now represents a bounded **multimode** trusted local terminal shell.

The implementation covers:
- operator-mode status overview
- approvals review
- audit and event inspection
- user, channel identity, and enrollment inspection
- task, blocker, and project inspection
- explicit failure disclosure
- one consequential administrative action for approval resolution
- explicit shell mode switching between operator and chat scaffold surfaces
- a first visual-language overhaul for readability and role distinction

It intentionally does not implement remote dashboard collaboration, live notification routing, real channel-backed chat, or broad workflow administration.

## Shell model

The trusted local shell lives in `TrustedOperatorTUI` and reads canonical state through `OperatorSurface`.

The shell now has two explicit contexts:
- `operator`
- `chat`

These are shell contexts, not identical to command authority. Command results still report their actual outcome class:
- `READ-ONLY`
- `ADMIN`
- `CHAT-SCAFFOLD`
- `SHELL`

This distinction matters. Operator inspection stays truthful and non-mutating; chat remains an explicit scaffold and must not impersonate real channel behavior.

## Operator surface model

Read-only operator views remain pure inspection:
- `status`
- `approvals`
- `audit`
- `users`
- `tasks`
- `inbox`
- `failures`

These views query trusted local SQLite state and do not write audit or event rows. Validation checks this by comparing audit and event counts before and after scripted inspection.

Consequential administration remains explicit:
- `admin approval approve <approval_record_id> --actor <user_id> --confirm APPROVED`
- `admin approval deny <approval_record_id> --actor <user_id> --confirm DENIED`

Admin commands require an active local operator user, require the assigned approver or primary user, and require a confirmation token matching the target outcome. Successful resolution updates `approval_records`, writes `operator_approval_resolved` to `audit_events`, and appends the same action to `event_log`.

## Chat scaffold boundary

The new chat mode is intentionally honest and narrow.

It may render:
- chat home/help
- scaffold status
- local drafts
- visual roles such as user input, assistant reply, and system guidance

It does **not**:
- connect to Telegram, BlueBubbles, Google Chat, email, or any live channel
- read live conversation history
- fabricate inbound messages
- generate or send assistant replies through a provider
- imply real delivery or synchronization

Current scaffold commands:
- `mode chat`
- `chat help`
- `chat status`
- `chat inbox`
- `chat thread <thread_id>`
- `chat compose <text>`
- `mode operator`

`chat inbox` and `chat thread <thread_id>` are Feature 5 read-only local inbox commands. They inspect canonical local threads/messages and keep no-live-channel disclosure visible.

## Failure disclosure

Failure disclosure remains explicit in both `status` and `failures`.

The bounded V1 failure sources remain:
- audit outcomes such as `deny`, `denied`, `failed`, `policy_denied`, and `authority_denied`
- blocked or failed commitments
- denied or failed tool invocations
- denied or failed Google Workspace actions
- denied or failed model route decisions
- suspended, revoked, or rebinding-required channel identities and enrollments

The surface treats blocked work and suspended enrollment as operator-visible degraded state, not as missing or silent data.

## Visual language

The shell still uses only the Python standard library, but it is no longer intentionally austere.

The multimode refresh adds:
- boxed screens
- explicit shell/result headers
- section headers
- badges for trust or boundary disclosures
- clearer distinction between guidance, commands, user input, assistant reply, and system guidance

The goal is not decoration for its own sake. The goal is to make authority, boundaries, and message roles legible at a glance.

## TUI shape

Start the shell with:

```bash
agentfirst tui
```

Or explicitly choose a starting mode:

```bash
agentfirst tui --mode operator
agentfirst tui --mode chat
```

Scripted commands remain supported:

```bash
agentfirst tui --command status --command failures
agentfirst tui --mode chat --command status
agentfirst tui --command "mode chat" --command "chat compose Review this later"
```

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk10_audit_tui.py
```

The validation now proves:
- read-only operator commands remain available and non-mutating
- operator failure disclosure still exposes blocked work and suspended enrollment
- operator admin approval resolution still updates trusted local state and audit history
- shell mode switching works
- chat scaffold commands remain explicitly non-live
- chat scaffold commands do not mutate audit or event state
- local draft rendering remains a draft and reports `sent = false`

## Remaining boundaries

This chunk still does not implement a full terminal UI framework, search or filter pagination, portfolio analytics, real inbox synchronization, or remote multi-operator coordination.

Approval resolution remains the only consequential TUI administration path in this chunk. Additional admin paths should follow the same model: explicit `admin` command namespace, active local operator identity, authority check, confirmation token, audit event, and event-log linkage.
