# Research Provider Validation Note

## Command

```bash
PYTHONPATH=src python3 scripts/validate_research_provider.py
```

## Expected Live Result

In a networked environment, the validation creates a temporary SQLite database and artifact root, then proves:
- a research commitment is created, activated, and completed with proof
- the research run is attached to both a project and commitment
- public external provider use is evaluated through policy before the HTTP request
- the tool invocation links to the policy decision
- the live Wikipedia API response is stored as a `search_runs` row and result artifact
- research output, citations, audit event, progress update, and append-only event records are linked

The stable success fields are:

```json
{
  "ok": true,
  "live_external_provider": true,
  "provider": {
    "name": "wikipedia-api",
    "http_status": 200
  },
  "linkage": {
    "research_attached_to_project": true,
    "research_attached_to_commitment": true,
    "search_links_policy_decision": true,
    "tool_links_policy_decision": true,
    "audit_links_policy_decision": true,
    "commitment_completed_with_research_proof": true
  }
}
```

IDs and the first result title vary by run.

## Local Sandbox Result

This execution environment blocked live DNS/network access. The script reached the live-provider boundary and failed honestly without fixture substitution:

```json
{
  "failure": "Live external provider validation could not reach wikipedia-api. This script is intentionally live-by-default and does not fall back to fixtures.",
  "fixture_fallback_used": false,
  "live_external_provider": false,
  "ok": false,
  "provider": "wikipedia-api"
}
```

## Acceptance Mapping

- Governed external provider path: implemented in `agentfirst_storage.research`.
- First-class search/research objects: `research_runs` and `search_runs` are written during validation.
- Policy before external use: `PolicyEngine.record_tool_invocation` runs before `WikipediaSearchProvider.search`.
- Tool/audit/policy linkage: `tool_invocations`, `policy_decisions`, `audit_events`, and `event_log` are linked.
- Commitment/project attachment: validation scope includes both IDs and records commitment progress.
- Honest disclosure: no fixture fallback is used; network unavailability is reported as validation failure.
