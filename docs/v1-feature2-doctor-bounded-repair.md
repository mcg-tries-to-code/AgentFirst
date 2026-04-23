# AgentFirst V1 Feature 2 Doctor / Bounded Repair

## Scope Delivered
Feature 2 adds a bounded local doctor surface under:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli doctor
PYTHONPATH=src python3 -m agentfirst_storage.cli doctor --fix
```

The doctor inspects Feature 1 onboarding/bootstrap state, local runtime paths, vault metadata, active secret payload references, provider/model preference linkage, and enabled-channel minimum prerequisites.

## Finding Classes
Doctor output is JSON and separates findings into:

- `informational`: state is present, intentionally deferred, or useful context for the operator
- `fixable`: narrow mechanical drift that can be repaired with `--fix`
- `blocked`: missing authority, missing secret material, inconsistent custody, or incomplete bootstrap state that doctor must not improvise

The top-level response includes `runnable`, `counts`, `actions`, and `findings` so an operator can tell whether the local installation is healthy enough for bounded local operation.

## Checks Implemented
The doctor currently checks:

- SQLite database presence and schema initialization
- artifact root directory presence
- encrypted secret vault root and records directory presence
- primary operator presence
- latest `onboarding_bootstraps` record presence
- active model/provider preference linked to latest onboarding state
- recorded channel choices
- minimum secret-handle requirements for enabled channels
- vault metadata presence and provider consistency
- active secret records pointing at existing vault payload files
- stored onboarding readiness/status freshness relative to current canonical state

## Bounded `--fix` Behavior
`doctor --fix` may repair only mechanical local drift:

- initialize the local schema when the database is absent
- create missing local artifact/vault directories
- relink a bootstrap record to an equivalent active model/provider preference that already exists
- refresh stale `onboarding_bootstraps.readiness_json` and `status`

Applied metadata repairs are recorded in `audit_events` and `event_log` with `doctor_fix_applied`.

## Explicit Non-Fixes
Doctor does not:

- fabricate secrets or secret records
- read or print secret plaintext
- create a root-key trust relationship to recover missing existing vault metadata
- choose a primary operator
- choose provider/model authority
- invent channel enablement choices
- approve enrollment, bypass trust controls, or widen permissions
- repair missing vault payload files for active secrets

Those remain blocked findings with explicit operator-facing detail.

## Current Boundary
This is still a local trusted-operator CLI surface. It does not implement the Feature 3 slash/admin command surface, remote repair orchestration, or lane/reset/memory lifecycle behavior.
