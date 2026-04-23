# AgentFirst V1 Feature 3 Minimal Command Surface Validation

## Commands Run
Syntax and Feature 3 validation:

```bash
python3 -m py_compile src/agentfirst_storage/command_surface.py src/agentfirst_storage/cli.py scripts/validate_v1_feature3_minimal_command_surface.py
python3 scripts/validate_v1_feature3_minimal_command_surface.py
```

Regression checks for canonical delegated surfaces:

```bash
python3 scripts/validate_v1_feature1_onboarding_bootstrap.py
python3 scripts/validate_v1_feature2_doctor_bounded_repair.py
```

Manual smoke checks during implementation:

```bash
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE=test-pass python3 -m agentfirst_storage.cli --db /tmp/af-f3-smoke.sqlite3 --artifact-root /tmp/af-f3-artifacts --secret-root /tmp/af-f3-secrets command /help
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE=test-pass python3 -m agentfirst_storage.cli --db <tmp>/agentfirst.sqlite3 --artifact-root <tmp>/artifacts --secret-root <tmp>/secure-secrets command /onboard bootstrap --operator-display-name 'Feature 3 Primary' --timezone America/New_York --custody-mode operator-passphrase --provider openai --model gpt-5.4 --channel local=enabled --channel telegram=enabled --secret-file telegram.bot.primary bot_token telegram <tmp>/telegram.txt
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE=test-pass python3 -m agentfirst_storage.cli --db <tmp>/agentfirst.sqlite3 --artifact-root <tmp>/artifacts --secret-root <tmp>/secure-secrets command /status
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE=test-pass python3 -m agentfirst_storage.cli --db <tmp>/agentfirst.sqlite3 --artifact-root <tmp>/artifacts --secret-root <tmp>/secure-secrets command /doctor
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE=test-pass python3 -m agentfirst_storage.cli --db /tmp/af-f3-fail.sqlite3 --artifact-root /tmp/af-f3-fail-artifacts --secret-root /tmp/af-f3-fail-secrets command /new
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE=test-pass python3 -m agentfirst_storage.cli --db /tmp/af-f3-fail.sqlite3 --artifact-root /tmp/af-f3-fail-artifacts --secret-root /tmp/af-f3-fail-secrets command /unknown
```

## Results
`python3 scripts/validate_v1_feature3_minimal_command_surface.py` passed:

```json
{
  "status": "ok",
  "command_set": [
    "/approve",
    "/doctor",
    "/help",
    "/lane",
    "/new",
    "/onboard",
    "/restart",
    "/status"
  ],
  "checks": {
    "approve_list_is_bounded_read_only": true,
    "bounded_help_command_set": true,
    "doctor_delegates_to_feature2": true,
    "lane_placeholder_has_no_state_mutation": true,
    "onboard_delegates_to_feature1": true,
    "plaintext_secret_not_printed": true,
    "reserved_commands_fail_explicitly": true,
    "status_reflects_real_state": true,
    "unsupported_commands_fail_explicitly": true
  }
}
```

The validator also confirmed:

- latest onboarding readiness was `runnable: true` with `runnable_scope: bounded_local`
- doctor counts were `blocked: 0`, `fixable: 0`, `informational: 12`
- status output included real operator-store counts, including `users: 1`

Feature 1 regression passed:

```json
{
  "status": "ok",
  "checks": {
    "first_run_invocation": true,
    "primary_operator_persisted": true,
    "custody_choice_recorded": true,
    "trusted_local_secret_ingest_no_plaintext_output": true,
    "provider_model_persisted": true,
    "channel_choices_persisted": true,
    "readiness_missing_then_ready": true
  }
}
```

Feature 2 regression passed:

```json
{
  "status": "ok",
  "checks": {
    "blocked_secret_not_fixed": true,
    "bounded_fix_applied": true,
    "doctor_fix_audited": true,
    "fixable_drift_classified": true,
    "healthy_state_runnable": true
  }
}
```

## Validation Coverage
Covered behavior:

- `/help` exposes a small documented command set and authority boundary.
- `/onboard bootstrap` delegates to Feature 1 canonical onboarding and writes a canonical `onboarding_bootstraps` record.
- `/onboard status` reads canonical onboarding state.
- `/doctor` delegates to Feature 2 doctor inspection and includes onboarding checks.
- `/status` reflects real onboarding, doctor, and operator-store state.
- `/approve list` is bounded read-only when no approval action is requested.
- `/lane` remains a read-only placeholder and does not persist lane state.
- `/new` fails explicitly as `not_implemented`.
- Unsupported commands fail explicitly as `unsupported_command`.
- Trusted local secret plaintext is not printed by command-surface onboarding.

## Residual Limits
Feature 3 intentionally does not validate or implement:

- remote chat command routing
- lane creation, switching, reset, or persistence
- `/new` checkpoint behavior
- `/restart` reload/reset behavior
- broader memory lifecycle state
- live approval scenarios beyond routing to the existing canonical `OperatorSurface.resolve_approval`
