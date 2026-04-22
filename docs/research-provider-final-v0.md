# AgentFirst Final v0 Governed Research Provider Proof

## Scope

This package adds one narrow, real external provider path for public research.

The implementation lives in `agentfirst_storage.research` and uses the public Wikipedia API as a no-secret live provider. It does not introduce a general web-browsing platform, crawler, model provider, or provider-owned state model.

## Implementation Shape

Primary additions:
- `WikipediaSearchProvider`: a small HTTPS provider client over the public Wikipedia search API.
- `ResearchService`: a governed service that creates a `research_runs` row before external use, records a policy-gated tool invocation, performs the external request only after policy allows it, then persists `search_runs`, artifacts, audit, progress, and research completion records.
- `scripts/validate_research_provider.py`: a live-by-default validation path. It uses no secrets and does not fall back to fixtures.

## Governance Path

The validation registers `tool_provider:wikipedia-api` as a tier 1 destination and adds policy rules for public provider use.

The service then:
1. creates a first-class `research_runs` record attached to a project and commitment
2. writes a provider request artifact
3. evaluates `invoke_tool` policy for the external provider before HTTP use
4. records a `tool_invocations` row linked to the policy decision
5. calls the live provider only when the invocation is policy-allowed
6. persists provider results in `search_runs` and artifacts with request/provenance metadata
7. records a linked `audit_events` row and append-only event
8. posts a progress update against the commitment

If the provider is unavailable after policy approval, the service marks the tool invocation and research run failed, records an `external_research_failed` audit event linked to the policy decision, appends an event-log row, and re-raises the provider error.

## Real vs Stubbed

Actually real:
- policy evaluation happens before the external HTTP request
- the provider call is a real HTTPS request to `https://en.wikipedia.org/w/api.php`
- `search_runs` and `research_runs` are first-class canonical records
- provider request URL, status code, result artifacts, policy decision, tool invocation, audit event, project, and commitment linkage are persisted

Still not claimed:
- private or confidential data is not sent in validation
- no secret-bearing provider is used
- this path does not exercise live Telegram delivery
- provider availability depends on live DNS/network access

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_research_provider.py
```

The validation should return `ok: true` in a networked environment. In a network-blocked environment it exits nonzero with `fixture_fallback_used: false`.
