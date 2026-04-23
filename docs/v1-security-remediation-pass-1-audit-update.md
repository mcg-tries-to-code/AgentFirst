# V1 Security Remediation Pass 1 Audit Update

Date: 2026-04-22

## Executive update
This bounded remediation pass materially improves the V1 security posture at the external-channel enrollment and disclosure boundaries.

It also preserves a bounded but replicable architectural pattern for future communication channels: channel-specific trust posture should feed a common AgentFirst enrollment, approval, audit, and policy model rather than each adapter inventing its own trust semantics.

The prior pre-patch judgment was a V1 no-go. After this pass, that judgment changes to:

**Updated judgment: conditional go for continued bounded V1 development and local acceptance validation, but still no-go for unqualified production launch.**

That change is justified because the most serious pass-1 defects are no longer open in their original form.

## Closed findings
### 1. Challenge verification was previously a state flip, not proof
Status: **closed for pass-1 scope**

What changed:
- enrollment verification now requires explicit `challenge_secret` and `challenge_nonce`
- verification is bound to enrollment id, address, nonce, stored hash, issuance state, and expiry state
- failed attempts are counted
- stale, mismatched, and denied paths fail closed

Why this matters:
- discovery is no longer enough to advance enrollment
- administrative advancement without challenge material is no longer the normal success path

### 2. Enrollment promotion lacked a canonical auditable approval gate
Status: **closed for pass-1 scope**

What changed:
- successful challenge verification creates an approval record
- enrollment promotion now requires a resolved approval record
- approval linkage is written back into enrollment metadata
- denial blocks promotion and transitions the enrollment into a denied state

Why this matters:
- enrollment promotion is no longer an informal follow-on call without explicit approval state
- the approval actor and approval record are now audit-visible

### 3. Unauthorized first contact retained too much trust value
Status: **closed for pass-1 scope**

What changed:
- unauthorized/pre-trust inbound no longer creates trusted channel identity or trusted thread state
- discovery metadata defaults to reduced metadata plus retention flags and digests
- raw inbound payload retention is no longer default behavior

Why this matters:
- first contact is now discovery/containment, not trusted activation

## Partially mitigated findings
### 4. Replicable trust architecture is established, but not yet fully generalized
Status: **partially mitigated**

Current state:
- Telegram and BlueBubbles now follow materially similar challenge, approval, and retention-hardening semantics
- the pass establishes the right pattern: provider/channel-specific trust posture first, canonical AgentFirst gate second

Residual debt:
- this is still implemented in channel adapters rather than through a fully shared enrollment-security abstraction
- future channel onboarding should reuse this pattern deliberately instead of treating provider-native trust as automatically sufficient

### 5. Pre-trust payload retention still has audit-oriented preview persistence
Status: **partially mitigated**

Current state:
- raw payload persistence was reduced materially
- preview-oriented retention remains for containment and auditability

Judgment:
- this is acceptable for the bounded pass, but it is still retention
- later passes should review preview length, storage lifetime, and any per-channel override rules

### 6. Outbound unsent-content retention is reduced, not eliminated everywhere
Status: **partially mitigated**

Current state:
- approval-pending and otherwise unsent outbound content now prefers preview/hash retention
- transport request artifacts are sanitized rather than stored with blind full request fidelity

Residual debt:
- the repo still uses bounded local adapter artifacts rather than a unified cross-channel outbound retention policy surface
- a later pass should standardize this policy across all adapters and artifact writers

### 7. Approval-path unification is improved but not globally complete
Status: **partially mitigated**

Current state:
- enrollment approval for the remediated Telegram and BlueBubbles flows is routed through auditable approval records
- validation scripts were updated to resolve the approval record explicitly

Residual debt:
- this is a bounded pass, not a repo-wide approval-architecture consolidation
- broader unification of approval semantics across other sensitive actions still remains future work

## Remaining findings / residual risks
### 1. Production hardening is still incomplete
- validation is local and artifact-based, not a live production deployment proof
- live secret management, credential rotation, and operational alerting are still outside this pass

### 2. Structural cleanup debt remains in the Telegram adapter
- the remediation was applied narrowly and successfully validated
- the file would still benefit from a cleanup pass to reduce helper duplication and make the hardened path easier to audit line-by-line
- this is maintainability debt, not a demonstrated bypass in the validated paths

### 3. Newly onboarded channels still need a clear trust-posture mapping discipline
- provider-native trust layers, such as tenant/account controls, should be treated as inputs rather than automatic sufficiency
- future channel work should explicitly decide whether the provider gate is enough for a specific action, or whether provider gate plus AgentFirst gate is required
- the safer default for new channels is provider gate plus AgentFirst gate until a narrower exception is justified

### 4. Google Chat is still unresolved as an implementation choice
- this pass intentionally did not implement Google Chat
- the architecture decision is captured separately in `docs/google-chat-channel-judgment.md`

### 5. Recovery and rebinding semantics are better represented, but not exhaustively validated here
- this pass focused on the highest-risk pass-1 controls
- broader recovery/rebinding cases should receive a dedicated follow-on validation pass

## Patched-surface judgment by topic
### Challenge verification
**Reduced from blocker to acceptable for bounded V1 development.**

### Enrollment approval
**Reduced from blocker to acceptable for bounded V1 development.**

### Pre-trust inbound retention
**Reduced materially.**

### Outbound unsent retention
**Reduced materially, with remaining policy-surface cleanup debt.**

## Overall security judgment
Before pass 1:
- **V1 no-go**

After pass 1:
- **Conditional go for bounded V1 development and local acceptance validation**
- **Still no-go for unqualified production launch**

## Recommended next pass
1. remove remaining adapter-internal duplication and consolidate helper behavior for audit clarity
2. unify outbound retention policy behavior across adapters
3. extract a small shared channel-enrollment security pattern only if it can be done cleanly and reversibly
4. validate rebinding, recovery, and stale-binding flows explicitly
5. require any future communication channel to document its provider-native trust posture and how that posture feeds the common AgentFirst enrollment-first model before treating it as trusted
