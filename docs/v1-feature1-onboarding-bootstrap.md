# AgentFirst V1 Feature 1 Onboarding / Bootstrap

## Scope Delivered
Feature 1 adds a bounded local onboarding path under:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli onboarding bootstrap ...
```

The flow is intentionally local and operator-driven. It does not accept secrets through ordinary chat, does not implement doctor/repair, and does not enroll external channels by itself.

## Canonical State Written
Onboarding writes through existing canonical subsystems first:

- `users`: establishes or returns the single primary operator via `bootstrap_admin`.
- `secret_records` and `secret_access_events`: records trusted-local secret ingest metadata and audit events.
- encrypted local vault under `secure-secrets/`: stores secret payloads outside ordinary artifacts.
- `model_provider_preferences`: records the initial bounded provider/model preference.
- `onboarding_bootstraps`: records the onboarding run, custody selection, channel choices, secret metadata references, and readiness result.
- `audit_events` and `event_log`: records onboarding completion.

The new `onboarding_bootstraps` table is the Feature 1 handoff point for Feature 2 doctor work.

## Flow Shape
1. Initialize schema and artifact/vault roots.
2. Establish or return the primary operator user.
3. Initialize the selected root-key custody mode:
   - `operator_passphrase`
   - `macos_keychain`
4. Ingest any provided minimum secrets from trusted local files.
5. Record the initial provider/model preference using the bounded V1 model set.
6. Record channel choices as `enabled`, `disabled`, or `deferred`.
7. Evaluate readiness and persist the honest result.

## Readiness Rules
Readiness is `bounded_local` only when all required checks pass:

- primary operator exists
- root-key custody mode is selected and initialized
- model/provider preference exists
- channel choices are recorded
- every enabled channel's known minimum secret requirements are satisfied

Current channel-specific minimum:

- `telegram=enabled` requires an active `telegram` / `bot_token` secret record.

Enabled channels still depend on their own enrollment and trust rules. Onboarding does not bypass Telegram, BlueBubbles, or Google enrollment.

## Secret Safety
The onboarding command only supports trusted local secret files for Feature 1. CLI output includes metadata such as secret id, handle URI, status, and display hint, but never prints the secret payload.

Validation checks that the test plaintext secret is absent from:

- command stdout/stderr
- canonical SQLite database bytes
- ordinary artifact root
- encrypted vault files

## Deferred By Design
Feature 1 does not implement:

- doctor or repair mode
- slash/admin command surface
- remote or GUI onboarding
- broad provider/channel setup
- channel enrollment bypasses
- lane/reset/memory lifecycle behavior

Those remain later operational features.
