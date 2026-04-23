# AgentFirst V1 Multimode TUI UX

## Scope

AgentFirst now has a first multimode terminal shell with two explicit modes:

- `operator`: trusted local administration and inspection over canonical SQLite state.
- `chat`: a future-facing conversational shell scaffold with no live channel integration.

The shell is implemented in `TrustedOperatorTUI` in `src/agentfirst_storage/operator_surface.py`. The data access layer remains `OperatorSurface`; it continues to own truthful operator/admin reads and the bounded approval-resolution admin action.

## Mode Model

The TUI tracks a shell mode separately from command result authority:

- Shell mode is the current terminal context: `operator` or `chat`.
- Result mode describes what a command did: `READ-ONLY`, `ADMIN`, `CHAT-SCAFFOLD`, or `SHELL`.

This preserves existing validation and scripted behavior. Operator inspection commands such as `status`, `approvals`, `users`, `tasks`, and `failures` still report `READ-ONLY`. Approval resolution still reports `ADMIN`.

Mode switching is explicit:

```bash
mode operator
mode chat
operator help
chat help
```

The CLI can also start in a mode:

```bash
agentfirst tui --mode operator
agentfirst tui --mode chat
```

Scripted use remains supported:

```bash
agentfirst tui --command status --command failures
agentfirst tui --mode chat --command status
agentfirst tui --command "mode chat" --command "chat compose Review this later"
```

## Operator Mode

Operator mode is the truthful local control surface. It shows:

- operator guidance
- read-only commands
- explicit admin commands
- trusted state counts
- approval status
- failure and degraded-state disclosures
- users, channel identities, enrollments, projects, commitments, blockers, audit events, and event log rows

Read-only views must not mutate audit or event state. Consequential admin actions must remain in the `admin` namespace and require active local operator identity plus confirmation tokens.

## Chat Mode

Chat mode is intentionally labeled `CHAT-SCAFFOLD`.

It is useful as a shape for future work, but it does not:

- connect to Telegram, BlueBubbles, Google Chat, email, or any other channel
- read live channel history
- show fabricated inbound messages
- generate or send assistant replies through a channel
- imply that remote messaging support exists

Current chat commands:

- `chat help`: show scaffold boundary and concepts.
- `chat status`: show scaffold boundaries plus a small truthful operator-state summary from local storage.
- `chat compose <text>`: render the text as a local draft panel only; it is not sent and does not generate a live assistant response.

Future live chat work must bind a real channel identity, policy decision, authority context, model-routing decision, audit trail, and event-log entry before showing actual conversation state.

## Visual Language

The first visual overhaul uses standard-library rendering only:

- boxed screens for clear command boundaries
- explicit result mode in every header
- section headers using `== SECTION ==`
- status badges such as `[TRUSTED LOCAL]`, `[NO LIVE CHANNEL]`, and `[FAILURE DISCLOSURE]`
- dedicated labels for `GUIDANCE`, `COMMAND`, `USER INPUT`, `ASSISTANT REPLY`, and `SYSTEM GUIDANCE`
- operator/admin output in the same structural grammar as chat scaffold output

ANSI color is optional and only enabled when stdout appears to be a real TTY and `NO_COLOR` is not set. Non-interactive command output remains plain text with the same structure.

## Immediate Boundaries

This change does not add a full-screen terminal framework, pagination, search, remote dashboard collaboration, or real chat integration.

The implementation keeps the code intentionally simple. The next likely additions should be narrow:

- mode-specific command aliases only when they clarify behavior
- pagination or filtering for high-volume local state
- a real channel-backed chat mode only after inbound identity, policy, routing, and audit contracts are implemented
