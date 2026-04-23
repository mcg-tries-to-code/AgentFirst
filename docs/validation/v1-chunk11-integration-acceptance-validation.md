# AgentFirst V1 Chunk 11 Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk11_integration_acceptance.py
```

## Scenario

The validation creates trusted local state in one temporary SQLite store:
- primary user
- two standard users with different roles in the scenario
- one outsider user
- enrolled Telegram and BlueBubbles channel bindings
- per-user Google Workspace connections
- an explicit supervisory authority grant
- one operational project with participant, artifact, policy, and commitment linkage
- private and project-scoped memory records
- baseline tool capabilities and tool invocations
- model provider preference with fallback
- blocked work, failure records, and a pending approval for trusted TUI review

## Assertions

The validation asserts:
- unknown Telegram first contact is contained outside trusted canonical state
- enrolled Telegram inbound creates trusted work
- enrolled BlueBubbles/iMessage inbound creates trusted work
- cross-user Google access is denied without an authority grant
- explicit supervisory grant allows bounded cross-user Google calendar access
- project outsider read is denied
- private memory retrieval by an unauthorized user is denied
- project memory retrieval by a participant returns provenance-bearing results
- authorized project tool invocation completes
- unauthorized project tool invocation records authority denial
- model-provider fallback is selected and disclosed
- exhausted model route records an honest failure
- read-only trusted TUI commands do not mutate audit or event state
- trusted TUI admin approval resolution updates approval state
- integrated audit history contains representative events across channels, authority, Google, projects, memory, tools, model routing, and operator approval

## Expected Result

The script prints JSON with:
- `"ok": true`
- acceptance decision booleans
- trusted-state counts
- representative object ids
- residual risks
- final judgment: `CONDITIONAL GO for bounded V1 local acceptance; NO-GO for unqualified production launch`

## Latest Local Result

On the Chunk 11 implementation pass, the command completed successfully.

Observed high-level result:
- `ok`: `true`
- `judgment`: `CONDITIONAL GO for bounded V1 local acceptance; NO-GO for unqualified production launch`
- acceptance decisions: all integrated checks returned `true`
- representative counts: 4 users, 3 channel enrollments, 4 channel identities, 2 messages, 3 commitments, 3 Google Workspace actions, 4 tool invocations, 2 model route decisions, 2 memory retrievals, 18 policy decisions, 1 approval record, 60 audit events, 108 event-log rows

## Caveats

This validation is intentionally bounded. It does not validate live Telegram delivery, live BlueBubbles delivery, Google OAuth/API execution, live model-provider execution, deployment supervision, backup/restore, or long-running operational behavior.
