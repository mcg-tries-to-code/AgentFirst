# AgentFirst V1 Chunk 6 Tooling Baseline

## Scope

V1 Chunk 6 makes the practical tool surface explicit and governed.

The implementation covers:
- a bounded V1 baseline registered as `tool_capabilities`
- an invocation service that checks authority before policy
- policy-linked tool invocation records for consequential actions
- invocation provenance that records capability, sponsor, scope, and outcome
- validation of allowed, authority-denied, and policy-denied tool paths

It intentionally does not implement provider routing, broad memory/retrieval work, dynamic plugin loading, marketplace behavior, or live provider expansion.

## Baseline Model

The bounded baseline lives in `V1_TOOL_BASELINE` and is materialized by `ToolingService.ensure_v1_baseline`.

The V1 baseline capabilities are:
- `local.artifact_write` through `agentfirst_core`
- `local.commitment_progress` through `agentfirst_core`
- `research.wikipedia_search` through `wikipedia-api`
- `channel.telegram_send_message` through `telegram-bot-api`
- `channel.bluebubbles_send_message` through `bluebubbles-api`
- `google.gmail` through `google_workspace`
- `google.calendar` through `google_workspace`
- `google.contacts` through `google_workspace`
- `google.drive` through `google_workspace`

Each baseline capability records:
- provider
- risk class
- bounded scope
- whether it is consequential
- authority, policy, audit, and provenance requirements

This keeps V1 useful without creating open-ended plugin or provider routing semantics.

## Invocation Governance

`ToolingService.invoke` requires a `ToolInvocationRequest` with:
- actor user
- sponsoring user
- capability and provider
- operation
- explicit authority scope
- destination and content classification
- input payload

Invocation flow:
1. ensure the capability is in the V1 baseline and enabled
2. verify actor and sponsor are active users
3. evaluate authority for `intervene` against the named scope
4. if authority is denied, record a `tool_invocations` row with `status = authority_denied`
5. if authority is allowed, evaluate policy through `PolicyEngine.record_tool_invocation`
6. execute only bounded local actions for this chunk, or record policy-gated outcome
7. write an audit event and event-log entry for the invocation outcome

The authority check is deliberately separate from policy. Authority answers whether the actor may act in the scope; policy answers whether this consequential tool action may proceed to the destination with the specified classification.

## Provenance Model

`tool_invocations` now records:
- `authority_policy_decision_id`
- `operation`
- `scope_json`
- `provenance_json`
- `outcome_json`

The provenance record includes:
- `tool_capability_id`
- capability name and provider
- sponsoring user
- actor user
- authority decision
- policy decision when policy is reached
- scope
- outcome

Denied invocations are still recorded. This is important because a blocked tool request is operational evidence, not an absence of action.

## Non-Goals

This chunk does not implement:
- new live Google behavior beyond the Chunk 5 model
- live Telegram or BlueBubbles sends beyond existing governed channel surfaces
- model/provider routing
- dynamic plugin manifests or marketplace discovery
- broad memory, retrieval, search, or research expansion
