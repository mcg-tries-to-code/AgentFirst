# AgentFirst V1 Secrets Custody Threat Model and Tradeoffs

## Current risk judgment

**Current judgment: elevated / rollout-blocking for real credentials.**

Why:
- the repo has good authority and audit structure, but no dedicated secret vault
- ordinary artifacts are plaintext by default
- runtime integrations still imply ad hoc plaintext token injection
- there is no sanctioned non-chat secret intake path yet

This is not a criticism of the current bounded chunks. It is a statement that the missing custody layer now matters.

## Secret scope for this threat model

This threat model is intentionally narrow.

A **secret** here means an access credential or other authority-bearing material whose possession can directly grant, replay, elevate, wrap, authorize, decrypt, sign, impersonate, or charge.

In scope:
- Telegram bot tokens
- BlueBubbles credentials
- Google OAuth refresh tokens and client secrets
- model/search provider API keys
- app passwords
- bearer tokens and replayable session cookies
- usernames/passwords and service-account credentials
- communication-channel credentials
- webhook signing secrets
- encryption and wrapping keys
- payment credential material when it functions as an access-enabling secret

Out of scope unless they also carry direct authority:
- ordinary confidential business content
- private messages and documents
- health data
- most financial records
- general sensitive metadata

Those still need protection, but they belong to broader confidentiality/privacy controls rather than this secrets-specific custody model.

## Assets to protect

Primary assets:
- Telegram bot tokens
- BlueBubbles credentials
- Google OAuth refresh tokens and client secrets
- model/search provider API keys
- app passwords
- bearer tokens and replayable session cookies
- usernames/passwords and service-account credentials
- webhook secrets
- encryption and wrapping keys
- future per-user provider credentials

Secondary assets:
- secret fingerprints
- provider/account linkage metadata
- access audit showing who used which secret and when

## Threat actors

1. accidental operator leakage
   - pasting authority-bearing credentials into ordinary chat, docs, issues, or validation notes

2. local filesystem exposure
   - plaintext artifacts, backups, copied SQLite files, terminal scrollback, or exported logs

3. compromised integration or buggy adapter
   - writes request headers/tokens into artifacts or audit events

4. over-privileged internal component
   - retrieves secrets outside its actual purpose or scope

5. stolen host account / post-exploitation local access
   - attacker reads repo, DB, artifacts, or process env

6. provider compromise / token replay
   - long-lived replayable credential remains valid after disclosure

## Main threat scenarios

### T1. Secret pasted into ordinary chat
Impact:
- immediate proliferation of authority-bearing material across chat history, notifications, exports, and model context

Mitigation:
- sanctioned local admin ingest path
- explicit chat-side rejection messaging that redirects to secure intake
- secret-pattern redaction before persistence when possible

Residual risk:
- partial if a user ignores guidance and a channel/provider already captured the secret upstream

### T2. Secret written to normal artifact storage
Impact:
- plaintext secret lands in `file://...artifacts/...`, backups, validation bundles, or developer inspection paths

Mitigation:
- dedicated secret payload store, separate from normal artifacts
- central redaction hooks before `write_artifact()` for secret-bearing flows
- code review rule: no secret payload to generic artifact helpers

Residual risk:
- moderate until existing integration paths are migrated

### T3. Token leaks through logs, audit, or failure payloads
Impact:
- durable compromise through observability surfaces that are supposed to improve trust

Mitigation:
- redact by default
- secret-aware exception rendering
- request artifacts store placeholders only
- fingerprints instead of payloads

Residual risk:
- low once central redaction exists, high before it does

### T4. Broad plaintext retrieval by agents or tools
Impact:
- one misbehaving tool or prompt could exfiltrate reusable credentials

Mitigation:
- purpose-bound broker access
- least-privilege secret scopes
- injected execution preferred over raw retrieval
- audit every access

Residual risk:
- moderate for integrations that truly need plaintext at call time

### T5. Host compromise or backup disclosure
Impact:
- attacker obtains DB/artifact files and attempts offline decryption

Mitigation:
- envelope encryption
- KEK outside repo and DB, stored in OS keychain
- encrypted payload blobs only
- short-lived access tokens where possible

Residual risk:
- not eliminated if attacker has active local user context, but materially improved over plaintext

### T6. Rotation failure after suspected compromise
Impact:
- compromised token remains valid, or revocation breaks unrelated features

Mitigation:
- versioned secret records
- per-integration binding to specific secret handles
- staged cutover and explicit status tracking

Residual risk:
- manageable if versioning is built first rather than retrofitted later

## Design tradeoffs

### Tradeoff 1, OS keychain plus local encrypted vault vs external enterprise vault
Recommendation:
- use OS keychain plus local encrypted vault for V1

Why:
- bounded and implementable
- fits single trusted host / local operator model
- avoids turning V1 into a distributed secret-management project

Cost:
- less cloud-native than KMS/HSM-backed designs
- host trust remains important

### Tradeoff 2, metadata in canonical DB vs everything hidden in vault
Recommendation:
- keep metadata in canonical DB, payload in vault

Why:
- AgentFirst needs governance, ownership, status, rotation history, and audit linkage
- metadata is operationally useful and lower-risk than payload

Cost:
- reveals that a secret exists and what it is for
- requires careful minimization of display hints/fingerprints

### Tradeoff 3, plaintext retrieval vs injected execution
Recommendation:
- prefer injected execution, allow plaintext lease only as an exception

Why:
- reduces proliferation and reuse window
- easier to audit and bound

Cost:
- some adapters become slightly more complex
- not all provider SDKs make opaque injection equally convenient

### Tradeoff 4, secure local admin ingest first vs remote secret portal first
Recommendation:
- build secure local admin ingest first

Why:
- matches the trusted local operator plan already present in V1
- solves the core problem faster
- leaves room for remote admin later without blocking current progress

Cost:
- remote operators need a mediated workflow until a later admin surface exists

## Non-goals for V1

V1 does not need:
- enterprise-wide distributed vault federation
- multi-region secret replication platform
- automatic provider-specific rotation for every integration on day one
- secret sharing through ordinary messaging surfaces

## Security properties V1 must achieve

Required:
- no secret payload in ordinary repo/doc/chat state
- sanctioned non-chat ingest path
- encrypted at-rest custody with root key outside repo/db/artifacts
- auditable retrieval and rotation
- redaction by default
- revocation scoped to the affected integration binding

Nice but later:
- remote admin web portal
- hardware-backed attestation
- provider-native automatic rotation per integration

## Recommended go / no-go rule

**No-go for broader rollout with real replayable credentials until the minimal secret broker slice is implemented.**

Acceptable interim use:
- architecture docs
- placeholder refs like `secret://...`
- local development with throwaway credentials under explicit operator awareness

Not acceptable interim use:
- storing production tokens in plaintext files, artifacts, or chat
- relying on constructor/env sprawl as the long-term custody story
