# AgentFirst V1 Cross-Platform Secrets Review Validation

## Validation objective

Validate that the cross-platform secrets decision is now reflected honestly in both the docs and the implementation, without regressing into a macOS-only story.

## Validation result

**Pass, with bounded implementation caveats.**

The repo now matches the intended V1 decision closely enough to call it implemented in phase-1 form:
- shared encrypted local vault logic exists in core
- root custody is adapter-based
- macOS is supported through Keychain
- Linux/headless is supported through operator-unlock passphrase custody
- external KMS remains optional and deferred

## Evidence reviewed

### Existing secrets docs
- `docs/v1-secrets-custody-architecture.md`
- `docs/v1-cross-platform-secrets-decision.md`
- `docs/v1-cross-platform-secrets-portability-review.md`
- `docs/validation/v1-secrets-custody-validation.md`
- `docs/validation/v1-secret-broker-slice-phase-1-validation.md`

### Source findings
- `src/agentfirst_storage/secret_broker.py`
  - implements `LocalEncryptedSecretVault`, `SecretBroker`, `MacOSKeychainRootKeyProvider`, and `OperatorPassphraseRootKeyProvider`
- `src/agentfirst_storage/schema.py`
  - contains `secret_records` and `secret_access_events`
  - includes `google_connections.credential_secret_id`
- `src/agentfirst_storage/telegram.py`
  - supports `bot_token_secret_id` plus `secret_broker`
  - still retains raw `bot_token` as compatibility fallback
- `src/agentfirst_storage/cli.py`
  - exposes trusted local `secret put`, `secret list`, `secret rotate`, and `secret revoke`
- `src/agentfirst_storage/store.py`
  - ordinary artifact storage remains plaintext and therefore must stay outside secret custody
- `src/agentfirst_storage/bluebubbles.py`
  - remains a platform-specific adapter, which is acceptable and should stay explicit

## Key validation conclusions

### 1. macOS Keychain is an adapter, not the architecture
Confirmed.
The implementation now keeps Keychain behind `MacOSKeychainRootKeyProvider` instead of making macOS-only custody the whole design.

### 2. Linux has an honest baseline
Confirmed.
`OperatorPassphraseRootKeyProvider` gives Linux/headless environments a real supported path without assuming desktop secret services.

### 3. Shared core versus adapter split is now real code
Confirmed.
Vault storage, broker logic, metadata, and audit are shared core. Root custody is the OS-specific adapter boundary.

### 4. Telegram proves the broker path, but migration is incomplete
Confirmed.
Telegram can now resolve secrets through the broker, but raw-token compatibility still exists and other integrations are not yet fully migrated.

### 5. Other portability drift remains explicit rather than hidden
Confirmed.
BlueBubbles is still Apple-stack oriented, and the overall repo still operates as a host-local SQLite plus artifact-root system. That is acceptable if documented honestly.

## Validation gates for the next follow-on package

The next package should be considered correct only if it:
1. expands broker-backed secret binding beyond Telegram where live credentials are introduced
2. keeps `credential_secret_id` as the preferred Google migration path
3. preserves Linux/headless viability without making desktop secret services mandatory
4. avoids leaking plaintext secrets into artifacts, logs, docs, or validation output
5. preserves the shared-core versus adapter-specific architecture boundary

## Fail conditions for the next code pass

Fail the next package if any of these happen:
- macOS Keychain becomes the only supported root custody path again
- Linux support depends only on desktop secret services
- new integrations bypass the broker and reintroduce ambient plaintext secret handling as the primary path
- secret payloads land in normal artifact storage
- OS-specific branching leaks into channel/provider business logic instead of staying behind root-custody adapters

## Overall validation judgment

The cross-platform review is now more than a design memo. It matches a bounded implemented phase-1 reality:
**shared local encrypted vault plus pluggable root custody, with macOS Keychain on macOS and operator-unlock custody as the Linux baseline.**
