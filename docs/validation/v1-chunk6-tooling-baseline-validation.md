# AgentFirst V1 Chunk 6 Tooling Baseline Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk6_tooling_baseline.py
```

## Coverage

The validation proves:
- the V1 baseline is explicitly registered as `tool_capabilities`
- every baseline capability requires authority, policy, audit, and provenance
- an allowed consequential local artifact action completes
- an unauthorized cross-user tool action is recorded as `authority_denied`
- a restricted-content action reaches policy and is recorded as `policy_denied`
- invocation provenance records capability, sponsor, scope, and outcome
- audit events exist for authority, policy, and tool invocation outcomes

## Expected Result

The script prints JSON with:
- `ok: true`
- baseline capability count and names
- completed allowed action details
- authority-denied action details
- policy-denied action details
- audit and policy-decision counts

The validation uses a temporary SQLite database and artifact root.
