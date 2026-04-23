# AgentFirst V1 Multimode TUI Specification

## Status
This specification is written after the first multimode TUI implementation slice already landed in the repo.

That means this document is not a speculative greenfield brief. It is the authoritative specification and tightening pass for the implementation that now exists in `TrustedOperatorTUI`.

## Objective
Turn the original trusted local operator console into a clearer multimode terminal shell that:
- preserves truthful operator and admin behavior
- adds an explicit future-facing chat mode without pretending live messaging exists
- materially improves readability and visual separation between guidance, commands, input, replies, and system disclosures
- keeps scripted validation and non-interactive command execution intact

## Core product judgment
AgentFirst should not split prematurely into separate terminal products for operator/admin versus chat.

The correct near-term shape is one shell with explicit modes:
- `operator`
- `chat`

The shell must keep authority boundaries visible rather than implicit.

## Required behavior

### 1. Explicit multimode shell
The TUI must support:
- startup in operator mode
- startup in chat mode
- explicit mode switching inside the shell

Minimum commands:
- `mode operator`
- `mode chat`
- `operator help`
- `chat help`

### 2. Truthful operator mode
Operator mode remains the canonical trusted local inspection and admin surface.

It must continue to provide:
- `status`
- `approvals`
- `audit`
- `users`
- `tasks`
- `failures`
- `admin approval approve ...`
- `admin approval deny ...`

Read-only commands must remain non-mutating.
Consequential admin commands must continue to require the existing confirmation and authority checks.

### 3. Honest chat scaffold mode
Chat mode includes an explicit scaffold plus read-only access to the real local inbox.

It must not:
- imply that Telegram, BlueBubbles, Google Chat, email, or any other live channel is connected
- show fabricated history
- invent assistant outputs
- send messages
- blur draft rendering with actual delivery

It may provide:
- mode-specific home/help
- scaffold status view
- read-only inspection of stored local inbox threads and thread detail
- local draft rendering
- visual grammar for future input/reply/system panels

The inbox commands are local inspection commands. They do not claim live provider history, receive status, send status, or synchronization freshness.

### 4. Visual overhaul
The TUI must be more readable and more legible as an interface.

The visual language must include:
- boxed screen or panel boundaries
- an always-visible header that distinguishes shell mode from command/result mode
- clear section headers
- badges or status markers for important state disclosures
- explicit labels for:
  - guidance
  - commands
  - user input
  - assistant reply
  - system guidance

ANSI color may be used only when safe for a real TTY and must not be required for comprehension.
Plain-text non-interactive output must remain readable.

### 5. Script compatibility
Existing scripted use through `agentfirst tui --command ...` must continue working.

Compatibility constraints:
- operator inspection results still report `READ-ONLY`
- operator admin resolution still reports `ADMIN`
- chat scaffold results may report `CHAT-SCAFFOLD`
- shell-level parsing/mode-selection results may report `SHELL`

## CLI expectations
The human-facing CLI must keep the simple entrypoint:

```bash
agentfirst tui
```

Additional acceptable entrypoints:

```bash
agentfirst tui --mode operator
agentfirst tui --mode chat
```

## Out of scope
This slice does not promise:
- a full-screen terminal framework
- search/filter pagination
- live channel transport
- real inbox synchronization
- real thread selection
- real message sending
- remote multi-operator collaboration

## Observable completion criteria
This slice is complete when:
1. multimode shell behavior exists in code
2. operator mode remains truthful and compatible
3. chat mode is visibly scaffolded and non-deceptive
4. visual readability is materially improved in plain terminal output
5. validation covers both operator and chat scaffold behavior
6. usage and chunk documentation are updated to reflect the new shell shape
