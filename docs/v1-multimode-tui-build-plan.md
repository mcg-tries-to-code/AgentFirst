# AgentFirst V1 Multimode TUI Build Plan

## Build posture
The first implementation slice is already present in code.

Therefore this build plan is a follow-through execution plan, not a blank-sheet implementation plan. Its job is to close the gap between landed code and surrounding validation/documentation surfaces.

## Build objective
Bring the repo into a coherent, validated multimode-TUI state by aligning:
- implementation
- chunk documentation
- validation documentation
- validation script coverage
- ToolFlow execution evidence

## Ordered work

### Step 1. Freeze the specification surface
Artifacts:
- `docs/v1-multimode-tui-spec.md`
- `docs/validation/v1-multimode-tui-validation-plan.md`

Purpose:
- prevent further drift between intended shell behavior and what is actually acceptable

### Step 2. Update chunk and validation docs
Targets:
- `docs/v1-chunk10-audit-tui.md`
- `docs/validation/v1-chunk10-audit-tui-validation.md`

Required changes:
- describe the shell as multimode
- preserve operator/admin truth model
- add explicit chat scaffold boundary language
- mention mode switching and the new visual language

### Step 3. Extend the existing validator
Target:
- `scripts/validate_v1_chunk10_audit_tui.py`

Required changes:
- keep all existing operator/admin assertions
- add chat scaffold assertions
- verify mode switching
- verify chat commands do not mutate audit/event state
- verify chat scaffold outputs remain explicitly non-live

### Step 4. Execute in ToolFlow
Use a bounded local ToolFlow workflow with elevated steps to:
1. apply the repo follow-through edits
2. run compile and validation
3. produce a ToolFlow ledgered run as execution evidence

### Step 5. Review outputs
Confirm:
- ToolFlow run reached `succeeded`
- compile succeeded
- chunk 10 validation succeeded
- repo docs and validator are aligned with the already-landed code

## ToolFlow execution shape
The workflow should remain narrow and local-development only.

Planned elevated steps:
1. `apply_multimode_tui_followthrough`
2. `validate_multimode_tui_followthrough`

The workflow must not claim broader chat/channel support than exists.

## Completion definition
This build is done when:
- the spec and plans exist in the repo
- ToolFlow executes the follow-through workflow successfully
- the validation script passes after being extended
- the chunk and validation docs match the multimode implementation
