# AgentFirst V1 Operator Command Surface Usage

## Invocation
Run the minimal local command surface through the existing CLI:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /help
```

Use the same global state options as the rest of the CLI when needed:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db var/agentfirst-v0.sqlite3 \
  --artifact-root var/artifacts \
  --secret-root var/secure-secrets \
  command /status
```

## Common Commands
Show the bounded command set:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /help
```

Inspect local state:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /status
```

Run Feature 1 onboarding through the command surface:

```bash
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE='...' python3 -m agentfirst_storage.cli command /onboard bootstrap \
  --operator-display-name "Primary Operator" \
  --timezone America/New_York \
  --custody-mode operator-passphrase \
  --provider openai \
  --model gpt-5.4 \
  --channel local=enabled
```

Inspect onboarding:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /onboard status
```

Run Feature 2 doctor:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /doctor
PYTHONPATH=src python3 -m agentfirst_storage.cli command /doctor --fix
```

List approval records:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /approve list
```

Resolve an existing approval record:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /approve approve <approval_record_id> --actor <user_id> --confirm APPROVED
PYTHONPATH=src python3 -m agentfirst_storage.cli command /approve deny <approval_record_id> --actor <user_id> --confirm DENIED
```

## Explicit Placeholders
These commands are intentionally not implemented in Feature 3:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /new
PYTHONPATH=src python3 -m agentfirst_storage.cli command /restart
```

Both return JSON failures with `data.error` set to `not_implemented`.

`/lane` is read-only and returns a placeholder disclosure. It does not create, switch, reset, or persist lane state.
