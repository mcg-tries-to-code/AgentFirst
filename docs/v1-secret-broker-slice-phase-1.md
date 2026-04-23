# AgentFirst V1 Secret Broker Slice, Phase 1

## Scope delivered
This phase adds the smallest reversible secrets substrate that makes V1 custody real instead of aspirational.

Delivered components:
- `secret_records` metadata in canonical SQLite state
- `secret_access_events` explicit audit trail for ingest, access, rotate, revoke, and denied access
- shared encrypted local vault under a dedicated `secure-secrets/` root, separate from ordinary artifacts
- `RootKeyProvider` abstraction
- `MacOSKeychainRootKeyProvider`
- `OperatorPassphraseRootKeyProvider`
- minimal `SecretBroker` / `SecretService`
- trusted local CLI ingest path
- Telegram bot token brokered retrieval path
- Google connection metadata migration hook via `credential_secret_id`

## Code shape
Primary implementation files:
- `src/agentfirst_storage/secret_broker.py`
- `src/agentfirst_storage/schema.py`
- `src/agentfirst_storage/store.py`
- `src/agentfirst_storage/cli.py`
- `src/agentfirst_storage/telegram.py`
- `src/agentfirst_storage/google_workspace.py`

## Data model
### `secret_records`
Canonical metadata only. Stores:
- secret handle URI
- owner and optional scope
- integration type and secret kind
- status and current version
- masked display hint and fingerprint
- vault backend and root-key provider name
- rotation / revocation timestamps
- metadata JSON

It does not store the payload plaintext.

### `secret_access_events`
Explicit audit records for:
- ingest
- access
- rotate
- revoke
- denied access to inactive secrets

Each event records actor, purpose, integration, version, and outcome.

## Vault design
Phase 1 uses a dedicated local vault directory, not ordinary `write_artifact()` storage.

Current format:
- one encrypted JSON payload file per secret version under `secure-secrets/records/<secret_id>/v<version>.json`
- vault metadata in `secure-secrets/vault.json`
- payload encryption via OpenSSL AES-256-CBC
- integrity protection via HMAC-SHA256
- per-version salt and IV
- subkeys derived from the root key at read/write time

This is intentionally bounded. It is not yet a remote KMS or a large vault platform.

## Root key providers
### macOS
`MacOSKeychainRootKeyProvider`
- stores a 32-byte base64-encoded root key in macOS Keychain
- keyed by service name plus vault account
- keeps root custody outside repo and canonical DB

### cross-platform baseline
`OperatorPassphraseRootKeyProvider`
- derives the root key from an operator passphrase plus persisted salt
- works on Linux and headless hosts without assuming desktop secret services
- passphrase can come from a non-echo prompt or environment variable for bounded automation

## Telegram proving integration
`TelegramBotApiTransport` now supports:
- `bot_token_secret_id`
- `secret_broker`

At send time the transport resolves the token through the broker instead of assuming a raw constructor token as the primary model. The retrieval is audited through `secret_access_events` and mirrored into `audit_events` / `event_log`.

Raw `bot_token` is still supported as a compatibility fallback, but brokered retrieval is now the intended V1 path.

## Trusted local ingest path
CLI commands were added under `agentfirst-store secret ...`.

Supported operations:
- `secret put`
- `secret list`
- `secret rotate`
- `secret revoke`

Input can come from:
- non-echo prompt
- stdin pipe
- local file

The CLI prints metadata only, not secret plaintext.

## Migration posture
Phase 1 is deliberately narrow.

What is migrated now:
- Telegram token retrieval path
- Google connection schema hook for `credential_secret_id`

What is intentionally left for later:
- broad integration-by-integration migration
- remote KMS
- richer secret policies or leases
- automatic artifact redaction across every future adapter

## Bounded deviations and follow-ups
Phase 1 uses direct per-version encryption under a root-key-derived scheme instead of a fuller KEK/DEK hierarchy. That keeps the slice small and auditable, but later hardening should consider:
- explicit wrapped DEKs per secret version
- AEAD-native payload format
- memory-zeroing / process-hardening beyond normal Python limits
- more formal authorization policy around broker access
