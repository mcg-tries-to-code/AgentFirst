# AgentFirst V1 Secrets Custody Architecture

## Judgment

AgentFirst V1 now has a real phase-1 secrets-custody implementation, but it is still only a partial production answer.

Current repo posture:
- `secret_records` and `secret_access_events` now exist as canonical metadata and access-audit tables.
- `LocalEncryptedSecretVault`, `SecretBroker`, `MacOSKeychainRootKeyProvider`, and `OperatorPassphraseRootKeyProvider` implement the cross-platform custody slice.
- Telegram transport now supports brokered retrieval through `bot_token_secret_id`, while still keeping raw `bot_token` as a compatibility fallback.
- `google_connections` preserves both the legacy opaque `credential_ref` path and the migration hook `credential_secret_id`.
- `AgentFirstStore.write_artifact()` still writes plaintext files under the normal artifact root, which remains correct for ordinary artifacts and still incorrect for secret payloads.

Bottom line: V1 should be judged as **secret-aware with a working bounded custody substrate, but not yet fully migrated or fully production-accepted across every integration**.

## Existing and implied repo assumptions

### Explicit good assumptions already present
1. **Opaque reference doctrine exists**
   - `google_workspace.py` uses `credential_ref` rather than storing OAuth material inline.
   - Chunk 5 documentation explicitly says the ref is opaque and live credentials are out of scope.

2. **Some sensitive challenge material is already minimized**
   - Telegram and BlueBubbles enrollment state stores `challenge_secret_hash`, nonce, expiry, and attempt counters.
   - This is the right pattern for verifier material: do not keep reusable plaintext when a verifier/hash is enough.

3. **Provider trust is already treated as insufficient by itself**
   - Enrollment, owner approval, authority checks, and policy linkage already show the right V1 trust doctrine.
   - The same doctrine should apply to Google, model providers, bot tokens, and future integrations.

### Unsafe or incomplete assumptions
1. **The shared secret substrate exists, but migration is incomplete**
   - Telegram has an end-to-end brokered retrieval path.
   - Google and other provider/channel credentials are not yet broadly migrated to active `secret_id` use.

2. **Normal artifacts are plaintext by default**
   - `write_artifact()` writes normal UTF-8 or bytes under the regular artifact tree.
   - A careless implementation could still leak secrets into `messages/`, `transport/`, `tool-output/`, validation outputs, or future docs if adapters bypass the broker.

3. **Compatibility plaintext paths still exist**
   - `TelegramBotApiTransport(bot_token=...)` remains available as a compatibility fallback.
   - That should be treated as transitional rather than the target V1 operating model.

4. **Phase 1 vault format is intentionally minimal**
   - The current implementation uses OpenSSL AES-256-CBC plus HMAC-SHA256 with root-key-derived subkeys.
   - It proves bounded encrypted custody, but it is not yet the fuller wrapped-DEK or AEAD-first hardening posture that later iterations may want.

5. **Broker authorization is still trusted-local oriented**
   - Secret access is audited, but authorization around who may resolve which secret is still narrow and implementation-local.
   - That is acceptable for the current bounded slice, not the end-state for every deployment.

## V1 architecture decision

AgentFirst should adopt a **handle-based custody model**:
- ordinary canonical state stores **secret metadata and handles only**
- encrypted secret payloads live in a **dedicated secret vault store**
- the root encryption key lives **outside the repo and outside ordinary AgentFirst state**
- agents and integrations retrieve secrets only through a **secret broker** that returns either a short lease or integration-specific injected execution, not broad plaintext reuse

This keeps the design small enough for V1 while remaining reusable across channels and integrations.

## What counts as a secret in this package

In this package, a **secret** is a bounded class of material whose possession can directly grant, replay, elevate, wrap, authorize, or impersonate access.

Stated plainly: secrets here are primarily **access credentials or other authority-bearing materials**.

This package does **not** collapse all confidential, private, regulated, or sensitive information into the secret category.

### In scope as secrets
- API keys
- bot tokens
- app passwords
- OAuth client secrets
- OAuth refresh tokens
- bearer tokens
- session cookies when they can authenticate or replay a session
- usernames/passwords and other login credentials
- website or service-account credentials
- communication-channel credentials
- webhook signing secrets
- encryption keys, wrapping keys, and other cryptographic key-encryption material
- financial instrument data **when it functions as an access-enabling payment credential**, for example card data plus related authentication material

### Not automatically secrets
The following may be confidential or sensitive, but they are not automatically secrets for this architecture unless they also function as authority-bearing material:
- private messages and documents
- personal health information
- financial records that are informative but not payment credentials
- business-confidential strategy or notes
- ordinary internal metadata

Those data classes still matter, but they belong to broader data-classification and privacy policy, not automatically to the secrets-custody system.

### Boundary rule
If disclosure would be harmful but would **not** directly enable authentication, replay, signing, decryption, payment authorization, impersonation, or privileged system use, it is usually **sensitive/confidential content**, not a secret in this package.

## Secret classes and risk tiers

### Class S1, high-value replayable credentials
Examples:
- Telegram bot tokens
- BlueBubbles server/API credentials
- Google OAuth refresh tokens
- OAuth client secrets
- app passwords
- API keys for model/search providers
- bearer tokens and replayable session cookies
- usernames/passwords and service-account credentials
- webhook signing secrets
- encryption or wrapping keys

Rule:
- never store in ordinary repo files, docs, chat, or standard artifact paths
- require dedicated custody and rotation metadata

### Class S2, verifier or derivative material
Examples:
- salted verifier hashes
- challenge-secret hashes
- token fingerprints
- masked previews

Rule:
- may live in ordinary canonical state when non-replayable and justified
- still redact from user-facing logs when it helps attack correlation

### Class S3, ephemeral session material
Examples:
- short-lived access tokens
- temporary STS credentials
- one-use enrollment codes
- short local execution leases

Rule:
- prefer memory only
- if persistence is unavoidable, store with strict expiry and auto-purge

## Safe ingest recommendation

### Approved V1 safe ingest path
**Do not paste secrets into ordinary chat.**

The sanctioned V1 path should be:
1. operator uses a **trusted local AgentFirst admin surface** (native TUI or CLI on the host)
2. operator runs a dedicated secret-ingest command, for example `agentfirst admin secrets put`
3. the command prompts for the secret via **non-echo terminal input** or accepts a **local file/stdin pipe**
4. the client sends the secret over a **local-only channel** to the secret broker, preferably a Unix domain socket or localhost-only admin endpoint
5. the broker immediately encrypts and stores the payload in the dedicated secret vault store
6. ordinary AgentFirst state receives only:
   - `secret_id`
   - `secret_handle` / URI
   - owner and scope metadata
   - provider/integration type
   - created/rotated timestamps
   - fingerprint / last4-style preview if needed

### Why this is the recommended V1 path
- it is implementable now
- it matches the master plan’s trusted local operator direction
- it avoids inventing a big external vault platform in V1
- it cleanly avoids ordinary chat as a transport

### For remote/external operators
If remote secret submission is needed later, add a **separate trusted admin web flow** with strong operator auth and TLS. External channels may deliver only a link or instruction to complete secure submission, never the secret itself.

## At-rest custody model

### Recommended model
Use a **two-layer envelope model**:
- **metadata plane**: normal AgentFirst canonical DB rows, containing no secret payload
- **payload plane**: dedicated encrypted secrets store, separate from ordinary artifacts

#### Metadata plane
Add a canonical registry such as `secret_records` with fields like:
- `secret_id`
- `owner_type`, `owner_ref`
- `scope_type`, `scope_ref`
- `integration_type` (telegram, google_workspace, model_provider, bluebubbles, etc.)
- `secret_kind` (bot_token, oauth_refresh_token, api_key, app_password, webhook_secret)
- `handle_uri` such as `secret://sec_xxx`
- `status` (active, suspended, revoked, destroyed)
- `version`
- `fingerprint`
- `display_hint`
- `expires_at`, `rotated_at`, `revoked_at`
- `policy_refs_json`, `metadata_json`

#### Payload plane
Store encrypted payload blobs in a dedicated location outside ordinary artifact paths, for example:
- separate SQLite DB with encrypted blob column, or
- separate `secure-secrets/` store with one encrypted blob per secret version

Each payload should be encrypted with a per-secret or per-version DEK. The DEK is wrapped by a KEK.

### Root key placement
For V1 on the local trusted host:
- keep the KEK in the **OS secret store** (macOS Keychain on this host)
- do not store the KEK in the repo, normal `.env`, standard AgentFirst DB, or ordinary artifacts

This is a pragmatic V1 answer to “what encrypts them?” and “where does the root key live?”

## Runtime retrieval and injection model

### Design rule
Most callers should not retrieve broad reusable plaintext. They should request a **purpose-bound secret use**.

### Broker pattern
Add a local `SecretBroker` service with operations like:
- `resolve_handle_for_use(handle, actor, purpose, integration)`
- `lease_secret_text(...)` for the few integrations that truly require plaintext
- `inject_env_for_subprocess(...)` for subprocess-based tools
- `build_auth_headers(...)` for HTTP-based integrations
- `revoke_secret(...)`
- `rotate_secret(...)`

### Preferred retrieval order
1. **Injected execution**
   - best for subprocess or adapter calls
   - broker places the secret into child-process env or request header construction immediately before execution
   - do not persist the plaintext in durable records

2. **Short-lived plaintext lease**
   - only when direct injection is impractical
   - plaintext returned only in-memory to the adapter
   - lease includes TTL, caller identity, purpose, and audit record

3. **Never direct user/chat retrieval**
   - no tool or chat surface should reveal the secret value back to an operator by default

### Integration mapping
- Telegram: channel service holds `telegram_bot_secret_id`, broker injects bot token into transport call at send time
- BlueBubbles: same handle-based pattern
- Google Workspace: `google_connections` should move from raw `credential_ref` convention to governed `secret_id` or `credential_secret_id` plus secret kind/version metadata
- model/search providers: provider profiles reference secret handles, not env sprawl

## Redaction and non-proliferation rules

Redaction must be default.

### Required rules
1. never write secret payloads to:
   - chat responses
   - audit event summaries
   - event log payloads
   - normal docs
   - validation outputs
   - ordinary artifact paths

2. store only masked displays, for example:
   - provider name
   - last 4 chars or token fingerprint
   - created / rotated timestamps
   - status and scope

3. add a central redaction pass for:
   - tool input/output capture
   - transport request artifact generation
   - exception rendering
   - approval payloads
   - operator displays

4. mark secret-bearing fields as sensitive at schema/service boundaries so future adapters inherit the behavior automatically

### Minimum V1 implementation rule
Any field named or typed as secret-bearing must either:
- be omitted entirely from logs/artifacts, or
- be replaced with `[REDACTED secret://sec_xxx]`

## Rotation, revocation, and recovery

### Rotation model
- version secrets rather than mutating in place
- keep one active version by default
- allow staged cutover where old version remains readable only until validation completes
- update referencing integration bindings to the new active version atomically

### Revocation model
- revoke by secret handle/version without breaking unrelated integrations
- scope revocation to the bound integration or owner object
- record revocation reason, actor, timestamp, and blast radius

### Recovery model
- if compromise is suspected, AgentFirst should support:
  - suspend secret use immediately
  - mark dependent integrations degraded
  - prompt operator for replacement through safe ingest
  - retain masked auditability without showing the old value

## Reusable cross-channel doctrine

This secrets architecture should be reused across new channels/integrations:
- provider-native login or trust is input, not sufficiency
- every external integration binds to an AgentFirst-owned secret handle
- runtime access is purpose-bound and auditable
- metadata may be broad enough for governance, payload custody stays narrow
- channels may bootstrap trust, but not become secret-storage surfaces

## What must be remediated before broader rollout

1. no production secret should be stored via normal `write_artifact()` paths
2. raw constructor-secret paths such as fallback `bot_token` should remain compatibility-only and continue being removed from real deployments
3. `google_connections` should stop at opaque refs only temporarily and move toward active governed secret bindings where live credentials are introduced
4. operator secret submission must stay on trusted local admin UI/CLI, not ordinary chat
5. live deployment acceptance still needs to prove the broker path under real credentials and supervision

## Current bounded implementation step, now completed

The minimal local secret broker slice is now in place:
1. `secret_records` metadata table and `secret_access_events` audit table
2. shared encrypted local vault plus pluggable root-key providers
3. trusted local CLI ingest/rotate/revoke/list commands
4. Telegram Bot API token handling via `secret_id` lookup + runtime injection path
5. Google schema hook for governed secret binding through `credential_secret_id`

That slice answers ingest, custody, retrieval, and rotation in bounded form without turning V1 into a giant secrets platform.

## Next bounded follow-on step

1. migrate additional integrations from placeholder refs or ambient environment material to brokered secret bindings
2. tighten broker-side authorization semantics as more integrations come online
3. decide later whether payload-format hardening should move from the current CBC+HMAC phase-1 shape to a stronger wrapped-DEK or AEAD-first format
