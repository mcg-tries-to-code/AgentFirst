# AgentFirst V1 Cross-Platform Secrets and OS Portability Review

## Executive judgment

AgentFirst V1 should **not** standardize on macOS Keychain as the architecture.

The correct V1 shape is a **hybrid local-secrets architecture**:
- a **shared encrypted local secret vault** for secret payloads
- a **shared broker and metadata model** in core application logic
- a **pluggable root-key provider interface**
- **thin platform adapters** for root-key custody
- **no external KMS or enterprise vault dependency in V1**

That gives AgentFirst a real native path on both macOS and Linux without pretending Linux has one universally available first-party secret store equivalent to macOS Keychain.

## Recommended V1 decision

### Architecture choice
Use a **hybrid**:
1. **Shared local encrypted vault** for secret payloads
2. **Native OS key store adapter where it is strong and available**
3. **Operator-unlock root custody fallback for Linux/headless environments**
4. **External KMS/vault deferred to post-V1 hosted deployments**

### Why this is the right bounded answer

A pure "native OS key stores behind a common interface" design sounds elegant, but on Linux it breaks down quickly:
- desktop Linux commonly means Secret Service / libsecret over D-Bus
- headless Linux often has no reliable user-session key store
- systemd-specific credential paths are real but not universal
- server distributions vary too much to treat one Linux store as the V1 baseline

A pure external vault/KMS design is too large and deployment-heavy for current V1.

A pure local encrypted vault unlocked only by operator material is portable, but it throws away a genuinely good native custody surface on macOS.

So V1 should use the hybrid: **shared encrypted payload store plus pluggable root custody**.

## Root custody recommendation

### Shared model
- Core metadata stores only handles, bindings, fingerprints, policy, state, rotation metadata, and audit references.
- Payload custody lives in a shared encrypted local vault.
- The vault root key is obtained through a `RootKeyProvider` interface.
- The current phase-1 implementation derives encryption and MAC subkeys from that root key per stored secret version.
- A fuller wrapped-DEK or AEAD-first format remains a later hardening option, not a prerequisite for the bounded V1 slice.

### macOS
Preferred V1 root custody:
- **macOS Keychain adapter**

Reason:
- strong local operator fit
- native and stable
- materially better than storing a root key in repo, DB, `.env`, or artifacts

### Linux
Preferred V1 root custody:
- **operator-unlock adapter as the default Linux baseline**
- optional Linux native adapter later where actually available

Reason:
- it works on headless Linux, local Linux, VPS Linux, and CI-like service environments
- it avoids pretending Secret Service/libsecret is universal
- it keeps Linux support honest instead of desktop-biased

Practical V1 Linux root options:
- passphrase entered on trusted local admin CLI/TUI at startup or unlock time
- optional root-key file encrypted/wrapped by operator material and stored outside repo state

### What not to use as the V1 baseline
- external KMS as the mandatory default
- plaintext `.env` or repo files
- ordinary SQLite rows or artifact files
- Linux Secret Service as the only Linux story

## Shared core versus thin platform adapters

### Shared core logic
These should be identical on macOS and Linux:
- `SecretRecord` metadata model
- `SecretAccessEvent` audit model
- secret handle and binding model
- secret versioning, rotation, revocation, suspension
- broker policy for lease versus injected use
- redaction utilities
- ciphertext payload format
- vault blob storage
- admin verbs: `put`, `rotate`, `revoke`, `list`, `inspect-masked`
- adapter-facing APIs such as `lease_secret_text` or `inject_for_use`

### Thin platform adapters
These should vary by OS:
- `RootKeyProvider`
- host-local admin unlock wiring
- storage path conventions where appropriate
- optional service supervision integration later

Implemented V1 adapter boundary:
- `RootKeyProvider.get_or_create_root_key()`
- `RootKeyProvider.describe()`

The current interface is intentionally small. Rotation and alternative unwrap strategies can be added later without changing the core source-of-truth split between shared payload custody and platform-specific root custody.

## Repo findings that matter

### 1. The cross-platform decision is now implemented in bounded form
The repo now contains:
- `secret_records` and `secret_access_events`
- `LocalEncryptedSecretVault`
- `SecretBroker`
- `MacOSKeychainRootKeyProvider`
- `OperatorPassphraseRootKeyProvider`

So the architecture is no longer only a paper decision.

### 2. macOS and Linux root custody are both first-class in code
The implementation now treats:
- macOS Keychain as the native macOS adapter
- operator-passphrase unlock as the honest Linux/headless baseline

That is the right cross-platform split.

### 3. Artifact storage is still generic plaintext local filesystem
`AgentFirstStore.write_artifact()` writes directly under the artifact root.
That remains fine for ordinary messages and validation artifacts, but it is still an unacceptable secret payload destination.

### 4. Telegram now has a brokered path, with compatibility fallback still present
`TelegramBotApiTransport` now supports both:
- `bot_token_secret_id` plus `secret_broker`
- fallback raw `bot_token`

That means custody is now real, but migration is not yet complete enough to delete plaintext compatibility inputs everywhere.

### 5. Google connection model is portable and partially migration-ready
`google_connections.credential_ref` remains the legacy opaque abstraction boundary.
`google_connections.credential_secret_id` is now the governed schema hook for real secret binding.

## Material OS-specific drift beyond secrets

### A. BlueBubbles is inherently macOS-host-oriented
This is the largest non-secret portability drift.

Why:
- BlueBubbles is an iMessage bridge, and iMessage hosting is fundamentally Apple-device anchored
- the adapter defaults to `http://localhost:1234`
- the feature is not truly Linux-native in the same way Telegram or Google can be

Judgment:
- acceptable as a **platform-specific integration adapter**
- not acceptable as a **core architecture assumption**

Meaning:
- AgentFirst core can be cross-platform
- BlueBubbles should be explicitly documented as a macOS-adjacent adapter, or a remote integration reachable from Linux, not a universal local capability

### B. Repo docs and validation commands show host-specific path drift
Examples include:
- host-specific absolute paths
- Homebrew-based Python paths in `.venv`
- validation commands pinned to local absolute paths

Judgment:
- mostly repo/tooling drift, not core architecture lock-in
- still worth cleaning in docs so Linux operation is not treated as second-class by habit

### C. Local SQLite + local artifact root is single-host oriented, not macOS-specific
This is portable to Linux, but it is still a host-local operations model.
That is acceptable for V1 if documented honestly.

### D. Avoid future launchd-shaped drift
The repo does not appear deeply committed to launchd yet, which is good.
Keep it that way.
If service supervision is added later, keep it outside core logic and provide service templates separately for launchd and systemd.

## Acceptable adapters versus unacceptable lock-in

### Acceptable
- macOS Keychain adapter
- Linux operator-unlock adapter
- optional Linux Secret Service adapter later
- BlueBubbles as a platform-specific channel adapter
- OS-specific service files outside core app code

### Unacceptable
- making macOS Keychain the only root custody path
- assuming Linux has one universal first-class native secret store
- putting secret payloads in regular artifacts because the path is convenient
- forcing V1 to depend on external KMS to function locally
- mixing OS-specific secret calls directly into channel and provider business logic

## Minimum sane V1 design for macOS and Linux

1. Keep `secret_records` and `secret_access_events` as the canonical metadata and audit tables
2. Keep the shared encrypted local vault and `SecretBroker` as core, cross-platform components
3. Keep `MacOSKeychainRootKeyProvider` and `OperatorPassphraseRootKeyProvider` as the default adapter pair
4. Continue migrating integrations to `secret_id` or `credential_secret_id` bindings
5. Keep request artifacts and logs redacted by default
6. Add later hardening only in ways that preserve the shared-core versus adapter split

## Final recommendation

For V1, AgentFirst should use a **hybrid local secret architecture**:
- **shared encrypted local vault** as the payload plane
- **shared broker + metadata** as the application plane
- **native OS key store on macOS** where it is genuinely good
- **operator-unlock root custody on Linux** as the honest native baseline
- **optional Linux native key-store adapters later**, not as the only Linux answer
- **external KMS deferred** until hosted deployment truly needs it
