# AgentFirst V1 Secret Broker Operator Usage

## Principle
Do not paste secrets into ordinary chat or commit them into repo files.
Use the trusted local CLI.

## Default provider choices
- macOS local machine: `--root-provider macos-keychain`
- Linux or headless baseline: default `operator-passphrase`

## Initialize store
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db var/agentfirst.sqlite3 \
  init
```

## Ingest a secret from stdin
```bash
printf '%s' "$TELEGRAM_BOT_TOKEN" | \
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE='choose-a-strong-passphrase' \
python3 -m agentfirst_storage.cli \
  --db var/agentfirst.sqlite3 \
  --secret-root var/secure-secrets \
  secret put \
  --stdin \
  --handle telegram.bot.primary \
  --kind bot_token \
  --integration telegram \
  --owner-type system \
  --owner-ref operator
```

## Ingest from a non-echo prompt
```bash
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE='choose-a-strong-passphrase' \
python3 -m agentfirst_storage.cli \
  --db var/agentfirst.sqlite3 \
  --secret-root var/secure-secrets \
  secret put \
  --handle telegram.bot.primary \
  --kind bot_token \
  --integration telegram \
  --owner-type system \
  --owner-ref operator
```

## macOS Keychain-backed ingest
```bash
printf '%s' "$TELEGRAM_BOT_TOKEN" | \
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db var/agentfirst.sqlite3 \
  --secret-root var/secure-secrets \
  --root-provider macos-keychain \
  --keychain-service agentfirst.v1.secret-root \
  secret put \
  --stdin \
  --handle telegram.bot.primary \
  --kind bot_token \
  --integration telegram \
  --owner-type system \
  --owner-ref operator
```

## List metadata only
```bash
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE='choose-a-strong-passphrase' \
python3 -m agentfirst_storage.cli \
  --db var/agentfirst.sqlite3 \
  --secret-root var/secure-secrets \
  secret list
```

## Rotate
```bash
printf '%s' "$NEW_TELEGRAM_BOT_TOKEN" | \
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE='choose-a-strong-passphrase' \
python3 -m agentfirst_storage.cli \
  --db var/agentfirst.sqlite3 \
  --secret-root var/secure-secrets \
  secret rotate sec_xxx --stdin --reason routine_rotation
```

## Revoke
```bash
PYTHONPATH=src AGENTFIRST_SECRET_PASSPHRASE='choose-a-strong-passphrase' \
python3 -m agentfirst_storage.cli \
  --db var/agentfirst.sqlite3 \
  --secret-root var/secure-secrets \
  secret revoke sec_xxx --reason compromise_response
```

## Operational notes
- CLI output is metadata only.
- Secret plaintext is stored in the dedicated vault, not ordinary artifacts.
- Prefer stdin or prompt over inline shell arguments.
- If using the passphrase provider, protect the passphrase with the same care as any root secret.
