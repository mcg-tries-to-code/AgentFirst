# AgentFirst V1 Chunk 7 Model Routing Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk7_model_routing.py
```

## Coverage

The validation proves:
- bounded V1 model providers are registered as policy destinations
- user, agent, and task model preferences are explicit records
- a user-scoped preferred route selects the preferred provider
- an agent-scoped route falls back explicitly when the preferred provider/model is unavailable
- fallback disclosure is stored in the route decision and provenance
- a task-scoped private provider route is approval-gated through policy
- route decisions link to policy decisions and approval records where applicable
- audit events exist for preferences, policy evaluation, and route decisions

## Expected Result

The script prints JSON with:
- `ok: true`
- bounded provider/model list
- preference identifiers for user, agent, and task scopes
- selected preferred-route details
- selected fallback-route details and disclosure text
- approval-gated provider-route details
- audit, approval, preference, and route-decision counts

The validation uses a temporary SQLite database and artifact root.
