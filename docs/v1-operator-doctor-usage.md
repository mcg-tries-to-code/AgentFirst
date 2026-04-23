# AgentFirst V1 Operator Doctor Usage

## Inspect
Run from the repo root:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli doctor
```

Use the same `--db`, `--artifact-root`, `--secret-root`, `--root-provider`, and custody-related flags you use for onboarding or secret operations.

## Repair Narrow Mechanical Drift
Run:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli doctor --fix
```

`--fix` is intentionally conservative. It can create missing local directories, initialize an absent local schema, relink already-existing equivalent model-preference metadata, and refresh stale onboarding readiness/status.

## Read The Output
Important top-level fields:

- `runnable`: whether doctor sees the installation as healthy enough for bounded local operation
- `counts.informational`: passed checks or operator context
- `counts.fixable`: pending mechanical issues that `--fix` may address
- `counts.fixed`: fixes applied during this run
- `counts.blocked`: issues requiring operator action or authority-sensitive setup
- `actions`: metadata repairs applied during this run
- `findings`: complete per-check detail

## What To Do With Blocked Findings
Blocked findings require an explicit operator action through the proper setup path. Examples:

- missing primary operator: run onboarding bootstrap
- missing required secret: ingest the secret through trusted local onboarding or `secret put`
- missing channel enrollment: complete that channel's trust/enrollment flow
- vault provider mismatch or missing active payload: inspect custody/vault state manually; doctor will not create a replacement trust relationship

Doctor output never contains secret plaintext.
