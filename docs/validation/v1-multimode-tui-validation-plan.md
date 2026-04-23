# AgentFirst V1 Multimode TUI Validation Plan

## Purpose
Validate the new multimode TUI without overstating what is implemented.

The validation must prove three things at once:
- the original trusted operator surface still behaves correctly
- the new multimode shell is structurally sound
- the new chat mode remains an honest scaffold rather than a fake messaging surface

## Validation scope

### In scope
- operator mode command compatibility
- operator read-only non-mutation guarantees
- operator admin approval resolution
- mode switching behavior
- chat home/help/status/compose scaffold behavior
- truthful result modes in returned command results
- plain-text readability of rendered output

### Out of scope
- live Telegram or BlueBubbles messaging
- real inbound history loading
- real assistant reply generation
- terminal color assertions
- pagination/search/filter behavior

## Test strategy

### 1. Code import and syntax
Run:

```bash
python3 -m compileall src/agentfirst_storage
```

Pass criteria:
- compile succeeds with no syntax errors

### 2. Existing chunk 10 operator guarantees
Use `scripts/validate_v1_chunk10_audit_tui.py` as the canonical functional validation surface and extend it rather than creating a detached parallel validator.

Pass criteria:
- operator inspection commands still return `READ-ONLY`
- read-only operator inspection does not mutate audit or event state
- operator failure disclosure remains present
- admin approval resolution still returns `ADMIN`
- approval resolution still mutates trusted local state correctly

### 3. Multimode shell behavior
Add validation assertions for:
- `mode chat`
- `chat status`
- `chat compose ...`
- `mode operator`

Pass criteria:
- chat mode returns `CHAT-SCAFFOLD`
- chat mode does not mutate audit or event counts
- chat status explicitly reports no live channel integration
- chat compose renders a local draft but reports `sent = false`
- switching back to operator mode still yields operator help/home rather than an error

### 4. Documentation alignment
Update the following so documentation does not lag the implementation:
- `docs/v1-chunk10-audit-tui.md`
- `docs/validation/v1-chunk10-audit-tui-validation.md`
- optionally any focused current operator test guide that references the TUI

Pass criteria:
- docs describe the multimode shell truthfully
- docs do not claim live chat integration
- docs mention the scaffold boundary explicitly

## Expected evidence
The validation should leave behind:
- successful compile output
- successful validation JSON from `scripts/validate_v1_chunk10_audit_tui.py`
- updated docs that align with the new implementation

## Failure conditions
Treat any of the following as a real failure:
- operator read-only commands begin mutating audit/event state
- chat mode implies real channel connectivity
- docs overclaim live chat support
- scripted `agentfirst tui --command ...` behavior regresses
- result modes stop reflecting actual command authority
