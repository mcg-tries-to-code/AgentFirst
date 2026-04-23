# AgentFirst V1 Operator Onboarding Usage

## Simple human-first commands
Preferred operator UX:

```bash
agentfirst tui
agentfirst onboarding
agentfirst doctor
agentfirst model readiness --provider openai
```

`agentfirst onboarding` is now the guided path. It asks a few simple questions instead of requiring a wall of flags.

Default local state path when no overrides are supplied:
- `~/.agentfirst/agentfirst.sqlite3`
- `~/.agentfirst/artifacts`
- `~/.agentfirst/secure-secrets`

Optional overrides still work through:
- `AGENTFIRST_HOME`
- `AF_DB`
- `AF_ARTIFACTS`
- `AF_SECRETS`

## Bootstrap Command
If you want the fully explicit non-interactive form, run:

```bash
export AGENTFIRST_SECRET_PASSPHRASE='use-a-real-local-passphrase'

agentfirst onboarding bootstrap \
  --operator-display-name "Primary Operator" \
  --timezone America/New_York \
  --custody-mode operator-passphrase \
  --provider openai \
  --model gpt-5.4 \
  --channel local=enabled \
  --channel telegram=deferred
```

For macOS Keychain custody, use:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db var/agentfirst-v0.sqlite3 \
  --artifact-root var/artifacts \
  --secret-root var/secure-secrets \
  onboarding bootstrap \
  --operator-display-name "Primary Operator" \
  --timezone America/New_York \
  --custody-mode macos-keychain \
  --provider openai \
  --model gpt-5.4 \
  --channel local=enabled
```

## Trusted Local Secret Ingest
To enable Telegram during onboarding, provide the bot token through a local file:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db var/agentfirst-v0.sqlite3 \
  --artifact-root var/artifacts \
  --secret-root var/secure-secrets \
  onboarding bootstrap \
  --operator-display-name "Primary Operator" \
  --timezone America/New_York \
  --custody-mode operator-passphrase \
  --provider openai \
  --model gpt-5.4 \
  --channel local=enabled \
  --channel telegram=enabled \
  --secret-file telegram.bot.primary bot_token telegram /path/to/local/token-file
```

The token file is read locally. The command prints only metadata and readiness, not the token value.

## Inspect Readiness
Use:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db var/agentfirst-v0.sqlite3 \
  --artifact-root var/artifacts \
  --secret-root var/secure-secrets \
  onboarding status
```

The readiness result reports passed checks, missing prerequisites, deferred items, and whether AgentFirst is runnable in bounded local form.

## Important Boundaries
- `telegram=enabled` records intent and verifies the minimum bot-token secret exists; Telegram contact enrollment still uses its own trust flow.
- Deferred channels are recorded but not configured.
- Re-running onboarding returns the existing primary operator and records a new onboarding run.
- Use Feature 2 doctor later for drift inspection and bounded repair.
