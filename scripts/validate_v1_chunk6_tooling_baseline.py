#!/usr/bin/env python3
"""Validate V1 Chunk 6 bounded tooling baseline and governed invocation provenance."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import AgentFirstStore, ToolInvocationRequest, ToolingService, V1_TOOL_BASELINE


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk6-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 6 Primary", "America/New_York")
        alex = store.create_user(
            display_name="Alex Tool Sponsor",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        blair = store.create_user(
            display_name="Blair Tool Overreach",
            authority_tier="standard",
            default_timezone="America/Chicago",
            actor_type="user",
            actor_ref=primary["user_id"],
        )

        tooling = ToolingService(store)
        baseline = tooling.ensure_v1_baseline(actor_type="system", actor_ref="v1_chunk6_validation")
        if len(baseline) != len(V1_TOOL_BASELINE):
            raise RuntimeError("V1 tool baseline was not registered explicitly")
        if any(not item["audit_requirements_json"].get("provenance_required") for item in baseline):
            raise RuntimeError("A baseline tool capability is missing provenance requirements")

        allowed = tooling.invoke(
            ToolInvocationRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                capability_name="local.artifact_write",
                provider="agentfirst_core",
                operation="write_validation_artifact",
                scope_type="user",
                scope_ref=alex["user_id"],
                input={
                    "name": "allowed-tool-output.md",
                    "body": "Allowed V1 Chunk 6 local artifact write.",
                },
                destination_type="local",
                destination_identity="agentfirst-core",
                content_classification="internal",
            )
        )
        allowed_invocation = allowed["tool_invocation"]
        if allowed_invocation["status"] != "completed":
            raise RuntimeError(f"Allowed consequential tool did not complete: {allowed_invocation['status']}")
        if not allowed_invocation["output_ref"]:
            raise RuntimeError("Allowed consequential tool did not record an output_ref")
        allowed_provenance = allowed_invocation["provenance_json"]
        if allowed_provenance.get("capability_name") != "local.artifact_write":
            raise RuntimeError("Allowed invocation provenance lost the capability name")
        if allowed_provenance.get("sponsoring_user_id") != alex["user_id"]:
            raise RuntimeError("Allowed invocation provenance lost the sponsor")
        if allowed_invocation["scope_json"].get("scope_ref") != alex["user_id"]:
            raise RuntimeError("Allowed invocation provenance lost the scope")
        if not allowed_invocation["outcome_json"].get("executed"):
            raise RuntimeError("Allowed invocation outcome did not record execution")
        if not allowed_invocation["policy_decision_refs_json"]:
            raise RuntimeError("Allowed invocation is not policy-linked")
        if not allowed_invocation["authority_policy_decision_id"]:
            raise RuntimeError("Allowed invocation is not authority-linked")

        authority_denied = tooling.invoke(
            ToolInvocationRequest(
                actor_user_id=blair["user_id"],
                sponsoring_user_id=alex["user_id"],
                capability_name="local.artifact_write",
                provider="agentfirst_core",
                operation="write_other_users_artifact_without_grant",
                scope_type="user",
                scope_ref=alex["user_id"],
                input={
                    "name": "denied-tool-output.md",
                    "body": "This write must not execute.",
                },
                destination_type="local",
                destination_identity="agentfirst-core",
                content_classification="internal",
            )
        )
        denied_invocation = authority_denied["tool_invocation"]
        if denied_invocation["status"] != "authority_denied":
            raise RuntimeError("Cross-user tool invocation was not authority-denied")
        if denied_invocation["outcome_json"].get("executed"):
            raise RuntimeError("Authority-denied tool invocation executed")
        if denied_invocation["provenance_json"].get("sponsoring_user_id") != alex["user_id"]:
            raise RuntimeError("Denied invocation provenance lost the sponsor")
        if denied_invocation["scope_json"].get("scope_ref") != alex["user_id"]:
            raise RuntimeError("Denied invocation provenance lost the denied scope")

        policy_denied = tooling.invoke(
            ToolInvocationRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                capability_name="local.artifact_write",
                provider="agentfirst_core",
                operation="write_restricted_artifact",
                scope_type="user",
                scope_ref=alex["user_id"],
                input={
                    "name": "policy-denied-tool-output.md",
                    "body": "Restricted content must be blocked by policy.",
                },
                destination_type="local",
                destination_identity="agentfirst-core",
                content_classification="restricted",
            )
        )
        policy_invocation = policy_denied["tool_invocation"]
        if policy_invocation["status"] != "policy_denied":
            raise RuntimeError("Restricted tool invocation was not policy-denied")
        if policy_invocation["outcome_json"].get("executed"):
            raise RuntimeError("Policy-denied tool invocation executed")
        if not policy_invocation["policy_decision_refs_json"]:
            raise RuntimeError("Policy-denied invocation is not policy-linked")

        audits = store.list_records("audit_events", 1000)
        tool_audits = [audit for audit in audits if audit["event_type"] == "tool_invocation_recorded"]
        authority_audits = [audit for audit in audits if audit["event_type"] == "authority_evaluated"]
        policy_audits = [audit for audit in audits if audit["event_type"] == "policy_evaluated"]
        if len(tool_audits) < 3:
            raise RuntimeError("Tool invocation audit events were not recorded")
        if len(authority_audits) < 3:
            raise RuntimeError("Authority audit events were not recorded for tool invocations")
        if len(policy_audits) < 2:
            raise RuntimeError("Policy audit events were not recorded for policy-reached tool invocations")

        output = {
            "ok": True,
            "baseline": {
                "count": len(baseline),
                "capabilities": [
                    {
                        "name": item["name"],
                        "provider": item["provider"],
                        "risk_class": item["risk_class"],
                        "scope": item["audit_requirements_json"]["scope"],
                    }
                    for item in sorted(baseline, key=lambda item: (item["provider"], item["name"]))
                ],
            },
            "allowed_consequential_action": {
                "tool_invocation_id": allowed_invocation["tool_invocation_id"],
                "status": allowed_invocation["status"],
                "capability_name": allowed_provenance["capability_name"],
                "sponsoring_user_id": allowed_provenance["sponsoring_user_id"],
                "scope": allowed_invocation["scope_json"],
                "output_ref": allowed_invocation["output_ref"],
            },
            "denied_action": {
                "tool_invocation_id": denied_invocation["tool_invocation_id"],
                "status": denied_invocation["status"],
                "blocked_by": denied_invocation["outcome_json"]["blocked_by"],
                "scope": denied_invocation["scope_json"],
            },
            "policy_denied_action": {
                "tool_invocation_id": policy_invocation["tool_invocation_id"],
                "status": policy_invocation["status"],
                "blocked_by": policy_invocation["outcome_json"]["blocked_by"],
                "policy_decision_refs": policy_invocation["policy_decision_refs_json"],
            },
            "audit": {
                "tool_invocation_audit_count": len(tool_audits),
                "authority_audit_count": len(authority_audits),
                "policy_audit_count": len(policy_audits),
                "tool_invocation_count": count(store, "tool_invocations"),
                "policy_decision_count": count(store, "policy_decisions"),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
