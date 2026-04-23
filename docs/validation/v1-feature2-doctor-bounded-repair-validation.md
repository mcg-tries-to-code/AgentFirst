# AgentFirst V1 Feature 2 Doctor / Bounded Repair Validation

## Command
Run from repo root:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature2_doctor_bounded_repair.py
```

## Result
Status: passed

Observed output:

```json
{
  "checks": {
    "blocked_secret_not_fixed": true,
    "bounded_fix_applied": true,
    "doctor_fix_audited": true,
    "fixable_drift_classified": true,
    "healthy_state_runnable": true
  },
  "status": "ok"
}
```

## Checks Covered
- healthy onboarding/bootstrap state reports `runnable: true`
- healthy state has no blocked or pending-fixable findings
- missing artifact directory is classified as fixable local drift
- stale bootstrap model-preference linkage is classified as fixable when an equivalent active preference already exists
- stale onboarding readiness/status metadata is repairable by `doctor --fix`
- `doctor --fix` restores the mechanically drifted state to runnable
- `doctor --fix` records a `doctor_fix_applied` audit event
- Telegram enabled without its required bot-token secret is classified as blocked
- `doctor --fix` does not fabricate a missing secret record

## Validation Notes
The validation creates separate temporary installations for:

1. a healthy bounded-local setup with a trusted local Telegram bot-token file
2. a healthy setup intentionally drifted by deleting the artifact root and corrupting bootstrap metadata
3. an incomplete setup with Telegram enabled but no required secret

The script uses the real CLI and inspects canonical SQLite state after repair.

## Residual Risk
This validation uses `operator_passphrase` custody for portability. It does not exercise live macOS Keychain access, live Telegram enrollment, or recovery from missing encrypted vault payloads. Those remain blocked or separately validated areas.
