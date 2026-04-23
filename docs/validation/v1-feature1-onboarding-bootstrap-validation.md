# AgentFirst V1 Feature 1 Onboarding / Bootstrap Validation

## Command
Run from repo root:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature1_onboarding_bootstrap.py
```

## Result
Status: passed

Observed output summary:

```json
{
  "status": "ok",
  "counts": {
    "model_provider_preferences": 1,
    "onboarding_bootstraps": 2,
    "secret_records": 1,
    "users": 1
  },
  "latest_readiness": {
    "runnable": true,
    "runnable_scope": "bounded_local",
    "missing": [],
    "deferred": ["bluebubbles_channel"]
  }
}
```

## Checks Covered
- first-run onboarding invocation exists
- primary operator is persisted through canonical `users`
- root-key custody choice is recorded as `operator_passphrase`
- trusted local secret file ingest creates `secret_records` metadata
- plaintext secret is not present in command stdout/stderr
- plaintext secret is not present in canonical SQLite bytes, ordinary artifacts, or encrypted vault files
- provider/model choice persists in `model_provider_preferences`
- channel choices persist in `onboarding_bootstraps.channels_json`
- readiness first reports missing Telegram secret, then reports bounded-local readiness after secret ingest

## Validation Notes
The script deliberately creates two onboarding records:

1. incomplete: `telegram=enabled` without a bot token secret
2. ready: `telegram=enabled` with a trusted local bot-token file and `bluebubbles=deferred`

This proves the readiness result distinguishes missing prerequisites from deferred work instead of claiming readiness too early.

## Residual Risk
This validation does not exercise macOS Keychain custody because the portable automated path uses `operator_passphrase`. The secret broker phase validation separately covers macOS Keychain on Darwin hosts.
