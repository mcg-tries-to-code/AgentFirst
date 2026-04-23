# Google Chat Channel Judgment

Date: 2026-04-22

## Recommendation
**Do not implement Google Chat as a first-class external-channel adapter in this phase. Implement it, if needed, as a Google Workspace service extension first, but keep it aligned to the same canonical AgentFirst enrollment, approval, and policy model used for other communication channels.**

## Judgment
Google Chat is a poor fit for the current first-class transport-adapter model compared with Telegram or BlueBubbles.

The repo already has a bounded `GoogleWorkspaceService` with explicit per-user connection ownership, scoped services, authority checks, and policy checks. That matches the likely security boundary for Google Chat much better than introducing a new transport-first chat adapter that would need its own discovery, enrollment, rebinding, approval, disclosure, and trust-tier semantics.

That said, provider-native trust is not automatically sufficient. Google account and workspace controls should be treated as upstream trust inputs, not as a complete replacement for AgentFirst-side governance. The replicable architectural pattern should be:
- channel-specific/provider-specific trust posture evaluation
- then canonical AgentFirst enrollment/approval/policy enforcement
- then trusted communication activation

In other words, a provider gate may reduce risk, but it should not silently collapse the AgentFirst gate.

## Rationale
1. **Identity model**
   - Telegram and BlueBubbles are external-user inbound channels that need strong enrollment and binding controls.
   - Google Chat more naturally sits inside an existing Google account and workspace-connection boundary.

2. **Replicable trust architecture**
   - new communication channels should, where practical, feed a common AgentFirst trust model rather than each inventing their own approval semantics
   - the reusable pattern is: provider trust posture as input, then AgentFirst enrollment decision, then explicit approval/policy linkage, then trusted activation
   - this preserves architectural consistency for future channels such as Teams, Slack, or other tenant-bound systems

3. **Security reuse**
   - treating Google Chat as a Workspace extension lets it reuse per-user Google connection ownership and policy controls
   - this avoids creating a second overlapping trust model for the same Google account surface while still preserving AgentFirst-side approval and policy checks where the action crosses trust boundaries

4. **Complexity control**
   - a first-class adapter would require its own discovery, enrollment, challenge, approval, rebinding, retention, and audit model
   - that is a great deal of new security surface for rather little architectural gain right now

5. **Pass-1 priority**
   - the urgent work was hardening existing high-risk channel boundaries, not expanding the adapter set

## When this judgment should change
Revisit this only if Google Chat must behave as a true peer messaging boundary with independent inbound enrollment and durable threaded conversation semantics that cannot be modeled safely through the Google Workspace connection layer.

If that happens, the correct move is not a bespoke one-off shortcut. It is to map Google Chat's provider-native controls into the same canonical AgentFirst enrollment, approval, audit, and policy pattern already being established for other channels.

## Bottom line
For V1, **Google Chat should be treated as a Google Workspace service extension, not a first-class channel adapter.**

However, that judgment should still preserve a replicable cross-channel trust architecture: provider-native controls are inputs, not automatic sufficiency, and the final trusted state should remain governed by common AgentFirst enrollment, approval, and policy semantics.
