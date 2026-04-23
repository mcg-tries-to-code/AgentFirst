# AgentFirst V1 Chunk 7 Governed Model and Provider Routing

## Scope

V1 Chunk 7 started as a bounded model/provider routing layer and now includes the first governed execution layer.

The implementation covers:
- explicit `model_provider_preferences` for user, agent, and task scopes
- bounded V1 provider/model pairs in `V1_MODEL_PROVIDERS`
- route decisions recorded as `model_route_decisions`
- execution attempts recorded as `model_executions`
- policy evaluation for `query_model` provider use
- explicit fallback disclosure in route decision provenance
- validation for preferred, fallback, approval-gated, executed, and unavailable provider routes

It intentionally does not implement dynamic provider discovery, cost optimization heuristics, broad memory/retrieval work, or UI routing controls.

## Bounded Provider Model

The bounded V1 provider list is now generated from a provider catalog snapshot in `agentfirst_storage.provider_catalog`.

The snapshot is explicitly point-in-time, currently marked `2026-04-22`, and includes multiple models for:
- OpenAI: GPT-5/GPT-4.1/reasoning line entries, including the repo's configured `openai:gpt-5.4`
- Anthropic: current Claude line entries
- Google: current Gemini line entries
- Local: existing `local:llama.cpp-default` governance fallback placeholder

The catalog is not a claim that every current or future provider model is available to every account. Operators should refresh it against provider docs and account entitlements before treating it as current.

`ModelRoutingService.ensure_v1_provider_destinations` materializes these providers as `destination_trust_tiers` rows with `destination_type = model_provider`.

This keeps provider use policy-addressable without creating an open-ended provider marketplace.

## Preference Model

`model_provider_preferences` records:
- `scope_type`: `user`, `agent`, or `task`
- `scope_ref`: the user, agent, or task identifier being governed
- `purpose`: a bounded purpose such as `general`, `drafting`, or `sensitive_summary`
- preferred `provider` and `model`
- ordered fallback routes
- constraints and rationale
- creator attribution

Preferences are first-class records rather than ambient defaults. A route request with no matching active preference is recorded as failed instead of silently drifting to a provider.

## Routing Decisions

`ModelRoutingService.route` resolves preferences in this order:
- the request scope
- the requesting agent, when present
- the sponsoring user

The selected route is then evaluated through `PolicyEngine.evaluate_and_record` with `action_type = query_model`.

`model_route_decisions` records:
- actor and sponsor
- requesting agent when present
- request scope and preference scope provenance
- preferred provider/model
- selected provider/model
- fallback use and fallback reason
- disclosure summary
- policy decision and approval record links
- outcome status

Statuses are:
- `selected`
- `awaiting_approval`
- `denied`
- `failed`

## Fallback Semantics

Fallback is only used for explicit unavailability in the bounded route request. It is not used to bypass a policy denial or approval gate.

When fallback occurs, the route decision records:
- `fallback_used = 1`
- `fallback_reason`
- selected fallback provider/model
- a disclosure summary that names the preferred route and fallback route
- provenance flag `fallback_disclosed = true`

Honest fallback disclosure is mandatory for V1 route decisions.

## Execution Layer

`ModelExecutionService` performs the next step after routing:
- calls `ModelRoutingService.route`
- refuses execution unless the route is selected by policy
- resolves a provider lane
- executes only lanes that are locally ready and implemented
- records `model_executions`, audit events, and event-log evidence
- returns a disclosure that says whether execution was real or unavailable

Prompt custody is intentionally narrow. Execution evidence stores `prompt_sha256`, a short `prompt_preview`, output hash/preview, route linkage, lane, transport, and status. API keys are resolved through `SecretBroker` and are not printed or stored in repo artifacts.

Implemented live lanes:
- `openai:api`: OpenAI Responses API using a `model_provider/api_key` secret handle, default `secret://openai.api_key`
- `openai:codex_cli`: local Codex CLI subscription-backed execution when the `codex` binary and local configuration marker are present

Structurally ready but not live-implemented in this slice:
- `anthropic:api`
- `anthropic:claude_code_cli`
- `google:api`
- `google:antigravity_cli`

When those providers lack secrets, binaries, or implemented adapters, readiness and execution results report that plainly.

## Non-Goals

This chunk does not implement:
- model performance scoring
- token or cost optimization
- provider account/OAuth management
- memory/retrieval routing
- dynamic provider registration
