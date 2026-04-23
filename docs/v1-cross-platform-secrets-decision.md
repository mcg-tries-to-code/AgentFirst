# AgentFirst V1 Cross-Platform Secrets Decision

## Decision

AgentFirst V1 will use a **hybrid secrets architecture**.

### Chosen model
- **Payload custody:** shared local encrypted vault
- **Root custody:** pluggable `RootKeyProvider`
- **macOS provider:** native Keychain-backed root key custody
- **Linux baseline provider:** operator-unlock root key custody
- **External KMS/vault:** not required for V1, optional later

## Why this decision wins

### Rejected: native OS key stores only
Rejected as the sole architecture because Linux does not offer one reliable universal secret-store story across:
- desktop sessions
- headless servers
- VPS hosts
- systemd and non-systemd environments

macOS Keychain is good. Linux is fragmented.
So OS-store-only is too optimistic for V1.

### Rejected: external KMS/vault first
Rejected for V1 because it adds operational and product scope that the repo does not need yet.
It is a hosted deployment option, not the minimum sane local architecture.

### Rejected: operator-material-only everywhere
Rejected as the only answer because it would underuse a strong native platform custody surface on macOS.

### Chosen: hybrid
Chosen because it:
- keeps one shared secret model
- supports macOS well
- supports Linux honestly
- works on headless Linux
- avoids large external dependencies
- keeps platform branching narrow

## Root custody policy

### macOS posture
Default to:
- `MacOSKeychainRootKeyProvider`

### Linux posture
Default to:
- `OperatorPassphraseRootKeyProvider`

Optional future Linux adapters:
- Secret Service / libsecret provider when a real desktop session exists
- systemd-creds or other host-specific providers where explicitly supported

These are optional adapters, not the V1 baseline requirement.

## Shared core contract

### Shared components
- `SecretRecord`
- `SecretAccessEvent`
- `EncryptedSecretVault`
- `SecretBroker`
- `SecretHandle`
- secret versioning and status transitions
- brokered retrieval and injection APIs
- redaction rules
- audit rules

### Platform-specific components
- root-key acquisition and unwrap
- unlock UX
- host path conventions
- later service-manager packaging

## Architecture rules

1. Secret payloads never go in normal artifacts, docs, or canonical plaintext rows.
2. Canonical state stores metadata and bindings only.
3. Integrations bind to `secret_id`, not raw credential text.
4. Runtime secret use goes through the broker.
5. Injected use is preferred over broad plaintext retrieval.
6. Secret access is audited.
7. Rotation is versioned, not in-place.
8. Root custody is outside repo, DB, and ordinary artifacts.

## Immediate implications for the repo

### Telegram
Replace raw `bot_token` operational wiring with:
- `telegram_bot_secret_id`
- broker-mediated runtime injection

### Google Workspace
Replace placeholder opaque `credential_ref` practice with:
- governed `secret_id` or `credential_secret_id`
- explicit secret kind and version metadata

### Artifacts
`write_artifact()` remains for normal artifacts only.
It must not become a secret payload store.

### BlueBubbles
Treat as a platform-specific adapter, not a universal local transport capability.

## Support posture

### macOS
First-class in V1 via native Keychain root custody.

### Linux
First-class in V1 via operator-unlock root custody.

This is a real support posture, not a placeholder.
It means Linux does not depend on desktop secret services to be usable.

## Implementation status

That initial proving slice is now implemented in the repo:
1. `secret_records`
2. `secret_access_events`
3. shared encrypted vault + broker
4. `MacOSKeychainRootKeyProvider`
5. `OperatorPassphraseRootKeyProvider`
6. Telegram bot token broker path end to end

The implementation is intentionally phase-1 in shape. It proves the cross-platform decision in running code, but it does not yet migrate every integration.

## Next bounded follow-on step

Continue migration from architecture proof to broader operational coverage:
1. move Google credential handling from placeholder opaque refs toward active `credential_secret_id` use where live integrations are introduced
2. extend the same broker path to additional provider/channel credentials
3. keep secret use audited and redacted in transport, tool, and operator surfaces
4. harden the payload format later if needed without changing the source-of-truth contract that payload custody is shared-core and root custody is adapter-specific
