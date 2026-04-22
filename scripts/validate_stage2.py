#!/usr/bin/env python3
"""Run Stage 2 policy and exfiltration enforcement validation flows."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import AgentFirstStore, GovernedAction, PolicyEngine


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-stage2-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        admin = store.bootstrap_admin("Stage 2 Primary", "America/New_York")
        user = store.create_user(
            "Stage 2 User",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=admin["user_id"],
        )
        agent = store.insert(
            "agents",
            {
                "display_name": "Stage 2 Agent",
                "owner_user_id": user["user_id"],
                "persona_profile_json": {"stage": 2},
                "capability_profile_json": {"policy_enforced_actions": True},
            },
        )
        thread = store.insert(
            "threads",
            {
                "channel_type": "telegram",
                "ownership_context_type": "user",
                "ownership_context_ref": user["user_id"],
                "participants_json": ["channel:trusted-family-telegram"],
            },
        )

        system_policy = store.insert(
            "policies",
            {
                "policy_type": "global",
                "priority": 0,
                "rules_json": [
                    {
                        "action": "share_external",
                        "classification": "restricted",
                        "decision": "deny",
                        "rationale": "System policy blocks restricted outbound sharing.",
                    },
                    {
                        "action": "query_model",
                        "classification_floor": "sensitive",
                        "min_trust_tier": 2,
                        "decision": "deny",
                        "rationale": "System policy blocks sensitive-or-higher data to external model providers.",
                    },
                ],
                "targets_json": ["message", "tool_invocation", "model_provider", "export"],
            },
        )
        primary_policy = store.insert(
            "policies",
            {
                "policy_type": "primary-user",
                "owner_user_id": admin["user_id"],
                "priority": 10,
                "rules_json": [
                    {
                        "action": "share_external",
                        "classification": "public",
                        "max_trust_tier": 1,
                        "decision": "allow",
                        "rationale": "Primary user permits public outbound messages to trusted destinations.",
                    },
                    {
                        "action": "share_external",
                        "classification_floor": "private",
                        "decision": "require_primary_user_approval",
                        "rationale": "Primary user requires approval for private-or-higher outbound sharing.",
                    },
                ],
                "targets_json": ["message", "agent"],
            },
        )
        per_user_policy = store.insert(
            "policies",
            {
                "policy_type": "per-user",
                "owner_user_id": user["user_id"],
                "priority": 50,
                "rules_json": [
                    {
                        "action": "export",
                        "classification": "private",
                        "decision": "require_owner_approval",
                        "rationale": "Per-user policy requires owner approval for private exports.",
                    }
                ],
                "targets_json": ["user", "export"],
            },
        )

        trusted_channel = store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": "trusted-family-telegram",
                "trust_tier": 1,
                "policy_refs_json": [primary_policy["policy_id"]],
            },
        )
        partner_channel = store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": "partner-secure-channel",
                "trust_tier": 1,
                "policy_refs_json": [primary_policy["policy_id"]],
            },
        )
        general_llm = store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "model_provider",
                "destination_identity": "general-llm-api",
                "trust_tier": 2,
                "policy_refs_json": [system_policy["policy_id"]],
            },
        )
        local_export = store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "export",
                "destination_identity": "local-encrypted-archive",
                "trust_tier": 0,
                "policy_refs_json": [per_user_policy["policy_id"]],
            },
        )
        outbound_tool_destination = store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "tool_provider",
                "destination_identity": "approved-webhook",
                "trust_tier": 1,
                "policy_refs_json": [primary_policy["policy_id"]],
            },
        )

        external_rule = store.insert(
            "data_classification_rules",
            {
                "classification": "external_confidential",
                "origin_entity_ref": "entity:acme-nda",
                "allowed_destinations_json": ["channel:partner-secure-channel"],
                "blocked_destinations_json": ["model_provider:general-llm-api"],
                "approval_requirements_json": {"required": True, "approver": "primary_user"},
                "logging_requirements_json": {"level": "heightened"},
                "override_rules_json": [
                    {
                        "action": "query_model",
                        "destination_type": "model_provider",
                        "decision": "deny",
                        "rationale": "ACME NDA data may not be sent to model providers.",
                    }
                ],
            },
        )

        public_ref = store.write_artifact("messages/public-outbound.txt", "Public launch note.")
        external_ref = store.write_artifact("messages/acme-confidential.txt", "ACME confidential roadmap excerpt.")
        private_ref = store.write_artifact("exports/private-export.txt", "Private account notes.")

        engine = PolicyEngine(store)

        allow_result = engine.evaluate_and_record(
            GovernedAction(
                action_type="share_external",
                actor_type="agent",
                actor_ref=agent["agent_id"],
                sponsoring_user_id=user["user_id"],
                object_type="message",
                destination_type=trusted_channel["destination_type"],
                destination_identity=trusted_channel["destination_identity"],
                content_classification="public",
            )
        )
        outbound_message = store.insert(
            "messages",
            {
                "thread_id": thread["thread_id"],
                "direction": "outbound",
                "sender_identity_json": {"agent_id": agent["agent_id"]},
                "recipient_identities_json": [{"destination": trusted_channel["destination_identity"]}],
                "content_ref": public_ref,
                "classification": "public",
                "provenance_json": {"policy_engine": "stage2"},
                "policy_decision_refs_json": [allow_result["decision"]["policy_decision_id"]],
                "status": "sent",
            },
        )

        approval_result = engine.evaluate_and_record(
            GovernedAction(
                action_type="share_external",
                actor_type="agent",
                actor_ref=agent["agent_id"],
                sponsoring_user_id=user["user_id"],
                object_type="message",
                object_ref=external_ref,
                destination_type=partner_channel["destination_type"],
                destination_identity=partner_channel["destination_identity"],
                content_classification="external_confidential",
                origin_entity_ref="entity:acme-nda",
            )
        )

        deny_result = engine.evaluate_and_record(
            GovernedAction(
                action_type="query_model",
                actor_type="agent",
                actor_ref=agent["agent_id"],
                sponsoring_user_id=user["user_id"],
                object_type="artifact",
                object_ref=external_ref,
                destination_type=general_llm["destination_type"],
                destination_identity=general_llm["destination_identity"],
                content_classification="external_confidential",
                origin_entity_ref="entity:acme-nda",
            )
        )

        export_result = engine.evaluate_and_record(
            GovernedAction(
                action_type="export",
                actor_type="agent",
                actor_ref=agent["agent_id"],
                sponsoring_user_id=user["user_id"],
                object_type="artifact",
                object_ref=private_ref,
                destination_type=local_export["destination_type"],
                destination_identity=local_export["destination_identity"],
                content_classification="private",
            )
        )

        tool = store.insert(
            "tool_capabilities",
            {
                "name": "approved_webhook_post",
                "provider": "agentfirst-local",
                "input_schema_ref": "schema://tool/webhook/input",
                "output_schema_ref": "schema://tool/webhook/output",
                "policy_refs_json": [primary_policy["policy_id"]],
                "risk_class": "medium",
                "audit_requirements_json": {"audit": "always"},
            },
        )
        tool_result = engine.record_tool_invocation(
            GovernedAction(
                action_type="invoke_tool",
                actor_type="agent",
                actor_ref=agent["agent_id"],
                sponsoring_user_id=user["user_id"],
                object_type="tool_capability",
                object_ref=tool["tool_capability_id"],
                destination_type=outbound_tool_destination["destination_type"],
                destination_identity=outbound_tool_destination["destination_identity"],
                content_classification="public",
                metadata={"outbound_implication": True},
            ),
            tool["tool_capability_id"],
            input_ref=public_ref,
        )

        decisions = {
            "allow_outbound_message": allow_result["decision"]["decision"],
            "approval_external_confidential": approval_result["decision"]["decision"],
            "deny_external_model": deny_result["decision"]["decision"],
            "owner_approval_export": export_result["decision"]["decision"],
            "tool_invocation": tool_result["decision"]["decision"],
        }
        expected = {
            "allow_outbound_message": "allow",
            "approval_external_confidential": "require_primary_user_approval",
            "deny_external_model": "deny",
            "owner_approval_export": "require_owner_approval",
        }
        for key, value in expected.items():
            if decisions[key] != value:
                raise RuntimeError(f"{key} expected {value}, got {decisions[key]}")

        if approval_result["approval_record"] is None or export_result["approval_record"] is None:
            raise RuntimeError("Approval-gated decisions did not create approval records")

        audit_rows = store.list_records("audit_events", 100)
        decision_ids_with_audit = {
            row["policy_decision_id"] for row in audit_rows if row.get("policy_decision_id")
        }
        for result in [allow_result, approval_result, deny_result, export_result, tool_result]:
            decision_id = result["decision"]["policy_decision_id"]
            if decision_id not in decision_ids_with_audit:
                raise RuntimeError(f"Missing audit linkage for {decision_id}")

        event_rows = store.list_records("event_log", 200)
        linked_policy_events = [
            row
            for row in event_rows
            if row["event_type"] == "policy_decision_recorded" and row["audit_event_id"]
        ]
        if len(linked_policy_events) < 5:
            raise RuntimeError("Expected linked policy decision events for all governed actions")

        print(
            json.dumps(
                {
                    "ok": True,
                    "db": str(store.db_path),
                    "artifact_root": str(store.artifact_root),
                    "decisions": decisions,
                    "policy_decision_ids": [
                        allow_result["decision"]["policy_decision_id"],
                        approval_result["decision"]["policy_decision_id"],
                        deny_result["decision"]["policy_decision_id"],
                        export_result["decision"]["policy_decision_id"],
                        tool_result["decision"]["policy_decision_id"],
                    ],
                    "approval_record_ids": [
                        approval_result["approval_record"]["approval_record_id"],
                        export_result["approval_record"]["approval_record_id"],
                    ],
                    "audit_event_ids": [
                        allow_result["audit_event"]["audit_event_id"],
                        approval_result["audit_event"]["audit_event_id"],
                        deny_result["audit_event"]["audit_event_id"],
                        export_result["audit_event"]["audit_event_id"],
                        tool_result["audit_event"]["audit_event_id"],
                    ],
                    "external_confidential_rule": external_rule["rule_id"],
                    "external_confidential_origin": "entity:acme-nda",
                    "linked_policy_event_count": len(linked_policy_events),
                    "outbound_message_policy_refs": outbound_message["policy_decision_refs_json"],
                    "tool_invocation_status": tool_result["tool_invocation"]["status"],
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
