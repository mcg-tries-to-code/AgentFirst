#!/usr/bin/env python3
"""Run representative Stage 1 create/store/retrieve validation flows."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import AgentFirstStore
from agentfirst_storage.store import new_id


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-stage1-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        admin = store.bootstrap_admin("Stage 1 Admin", "America/New_York")
        extra_user = store.create_user(
            "Stage 1 Collaborator",
            authority_tier="standard",
            default_timezone="America/New_York",
            metadata={"validation": "first-extra-user-generic-path"},
            actor_type="user",
            actor_ref=admin["user_id"],
        )

        system_policy = store.insert(
            "policies",
            {
                "policy_type": "global",
                "priority": 0,
                "rules_json": [{"invariant": "no_silent_audit_bypass"}],
                "targets_json": ["tool_invocation", "policy_decision", "message"],
                "status": "active",
            },
        )
        per_user_policy = store.insert(
            "policies",
            {
                "policy_type": "per-user",
                "owner_user_id": extra_user["user_id"],
                "priority": 50,
                "rules_json": [{"action": "query_model", "classification": "sensitive", "decision": "deny"}],
                "targets_json": ["user", "agent"],
                "status": "active",
            },
        )
        external_rule = store.insert(
            "data_classification_rules",
            {
                "classification": "external_confidential",
                "origin_entity_ref": "entity:validation-partner",
                "content_selectors_json": [{"artifact_type": "partner_note"}],
                "allowed_destinations_json": ["destination:partner-approved"],
                "blocked_destinations_json": ["destination:unknown"],
                "approval_requirements_json": {"required": True, "approver": "primary_user"},
                "logging_requirements_json": {"level": "heightened"},
                "status": "active",
            },
        )
        destination = store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "model_provider",
                "destination_identity": "local-validation-model",
                "trust_tier": 0,
                "policy_refs_json": [system_policy["policy_id"]],
            },
        )

        shared_context = store.insert(
            "shared_contexts",
            {
                "name": "Stage 1 Validation Space",
                "context_type": "team",
                "visibility_model": "shared-members",
                "governance_policy_refs_json": [system_policy["policy_id"]],
            },
        )
        agent = store.insert(
            "agents",
            {
                "display_name": "Stage 1 Agent",
                "owner_user_id": admin["user_id"],
                "persona_profile_json": {"style": "concise"},
                "capability_profile_json": {"commitment_first": True},
                "tool_policy_bindings_json": [system_policy["policy_id"]],
                "model_routing_policy_json": {"default_destination": destination["destination_id"]},
            },
        )
        authority_grant = store.insert(
            "authority_grants",
            {
                "grantor_user_id": admin["user_id"],
                "grantee_user_id": extra_user["user_id"],
                "scope_type": "shared_context",
                "scope_ref": shared_context["shared_context_id"],
                "permissions_json": ["read_context", "create_commitment"],
                "constraints_json": [{"classification_max": "internal"}],
                "effective_at": "2026-04-21T00:00:00Z",
            },
        )
        store.add_shared_context_member(
            shared_context["shared_context_id"],
            "user",
            admin["user_id"],
            role="administrator",
            actor_type="user",
            actor_ref=admin["user_id"],
        )
        store.add_shared_context_member(
            shared_context["shared_context_id"],
            "user",
            extra_user["user_id"],
            role="member",
            actor_type="user",
            actor_ref=admin["user_id"],
        )

        channel = store.insert(
            "channel_identities",
            {
                "user_id": extra_user["user_id"],
                "channel_type": "telegram",
                "address": "@stage1_collaborator",
                "routing_policy_refs_json": [per_user_policy["policy_id"]],
            },
        )
        project = store.insert(
            "projects",
            {
                "name": "Stage 1 Project",
                "owner_scope_type": "shared_context",
                "owner_scope_ref": shared_context["shared_context_id"],
                "participants_json": [admin["user_id"], extra_user["user_id"]],
                "goals_json": ["prove schema storage scaffold"],
                "policy_refs_json": [system_policy["policy_id"]],
            },
        )
        thread = store.insert(
            "threads",
            {
                "channel_type": "telegram",
                "ownership_context_type": "user",
                "ownership_context_ref": extra_user["user_id"],
                "participants_json": [channel["channel_identity_id"]],
                "linked_project_ids_json": [project["project_id"]],
            },
        )
        content_ref = store.write_artifact("messages/inbound-request.txt", "Please track the Stage 1 validation task.")
        message = store.insert(
            "messages",
            {
                "thread_id": thread["thread_id"],
                "direction": "inbound",
                "sender_identity_json": {"channel_identity_id": channel["channel_identity_id"]},
                "recipient_identities_json": [{"agent_id": agent["agent_id"]}],
                "content_ref": content_ref,
                "classification": "internal",
                "provenance_json": {"source": "validation-script"},
            },
        )
        commitment = store.insert(
            "commitments",
            {
                "title": "Validate Stage 1 schema and storage",
                "commitment_type": "validation",
                "owner_scope_type": "agent",
                "owner_scope_ref": agent["agent_id"],
                "origin_ref_type": "message",
                "origin_ref": message["message_event_id"],
                "project_id": project["project_id"],
                "status": "active",
                "priority": 2,
                "next_action": "Create representative records and retrieve them",
                "review_at": "2026-04-22T15:00:00Z",
                "completion_criteria_json": {"required": ["all representative reads succeed"]},
            },
        )
        attention = store.insert(
            "task_attention_records",
            {
                "commitment_id": commitment["commitment_id"],
                "current_owner_type": "agent",
                "current_owner_ref": agent["agent_id"],
                "attention_state": "active",
                "next_review_at": "2026-04-22T15:00:00Z",
                "last_meaningful_activity_at": "2026-04-22T14:00:00Z",
                "urgency_score": 0.35,
            },
        )
        progress = store.insert(
            "progress_updates",
            {
                "parent_type": "commitment",
                "parent_ref": commitment["commitment_id"],
                "author_agent_id": agent["agent_id"],
                "summary": "Representative storage records created.",
                "state_change_json": {"from": "captured", "to": "active"},
            },
        )
        waiting = store.insert(
            "waiting_conditions",
            {
                "commitment_id": commitment["commitment_id"],
                "waiting_on_type": "scheduled_review",
                "waiting_on_ref": attention["attention_record_id"],
                "review_at": "2026-04-22T15:00:00Z",
                "status": "active",
            },
        )
        blocker = store.insert(
            "blocker_records",
            {
                "commitment_id": commitment["commitment_id"],
                "blocker_type": "policy",
                "summary": "Sensitive outbound validation would require approval.",
                "evidence_refs_json": [external_rule["rule_id"]],
                "resolution_options_json": ["request_primary_user_approval", "use_local_destination"],
                "requires_human_decision": 1,
                "status": "active",
            },
        )
        proof_ref = store.write_artifact("proofs/stage1-proof.txt", "All representative records retrieved by primary key.")
        completion_proof = store.insert(
            "completion_proofs",
            {
                "commitment_id": commitment["commitment_id"],
                "completion_criteria_snapshot_json": commitment["completion_criteria_json"],
                "evidence_refs_json": [proof_ref],
                "verified_by_type": "system",
                "verified_by_ref": "validation-script",
                "verified_at": "2026-04-22T15:05:00Z",
                "status": "verified",
            },
        )

        artifact = store.insert(
            "artifacts",
            {
                "name": "Stage 1 Validation Proof",
                "artifact_type": "document",
                "storage_ref": proof_ref,
                "owner_scope_type": "project",
                "owner_scope_ref": project["project_id"],
                "source_refs_json": [completion_proof["completion_proof_id"]],
                "project_refs_json": [project["project_id"]],
                "classification": "internal",
                "provenance_json": {"generated_by": "validation-script"},
            },
        )
        memory = store.insert(
            "memory_records",
            {
                "memory_type": "event",
                "owner_scope_type": "project",
                "owner_scope_ref": project["project_id"],
                "source_refs_json": [artifact["artifact_id"]],
                "content_ref": artifact["storage_ref"],
                "confidence": 1.0,
                "canonicality": "canonical",
            },
        )
        corpus = store.insert(
            "knowledge_corpora",
            {
                "name": "Stage 1 Corpus",
                "owner_scope_type": "project",
                "owner_scope_ref": project["project_id"],
                "corpus_type": "project",
                "source_definitions_json": [{"artifact_id": artifact["artifact_id"]}],
                "index_refs_json": ["index:stage1-validation"],
                "policy_refs_json": [system_policy["policy_id"]],
            },
        )
        search_results_ref = store.write_artifact(
            "search/stage1-results.json",
            json.dumps([{"title": "Local validation result", "url": "file://local"}]),
        )
        search = store.insert(
            "search_runs",
            {
                "query": "AgentFirst Stage 1 validation",
                "provider": "local-fixture",
                "results_ref": search_results_ref,
                "freshness_metadata_json": {"generated_at": "2026-04-22T15:02:00Z"},
                "status": "returned",
            },
        )
        research = store.insert(
            "research_runs",
            {
                "requestor_user_id": admin["user_id"],
                "sponsoring_agent_id": agent["agent_id"],
                "question": "Does Stage 1 storage persist representative records?",
                "scope_json": {"project_id": project["project_id"], "corpus_id": corpus["corpus_id"]},
                "search_refs_json": [search["search_run_id"]],
                "source_refs_json": [memory["memory_id"]],
                "working_notes_ref": proof_ref,
                "output_ref": artifact["storage_ref"],
                "citation_refs_json": [search["search_run_id"]],
                "status": "completed",
            },
        )
        capability = store.insert(
            "tool_capabilities",
            {
                "name": "local_file_write",
                "provider": "agentfirst-local",
                "input_schema_ref": "schema://tool/local_file_write/input",
                "output_schema_ref": "schema://tool/local_file_write/output",
                "policy_refs_json": [system_policy["policy_id"]],
                "availability_status": "enabled",
                "risk_class": "medium",
                "audit_requirements_json": {"audit": "always"},
            },
        )
        policy_decision = store.insert(
            "policy_decisions",
            {
                "actor_type": "agent",
                "actor_ref": agent["agent_id"],
                "sponsoring_user_id": admin["user_id"],
                "action_type": "invoke_tool",
                "object_type": "tool_capability",
                "object_ref": capability["tool_capability_id"],
                "destination_type": destination["destination_type"],
                "destination_identity": destination["destination_identity"],
                "destination_trust_tier": destination["trust_tier"],
                "content_classification": "internal",
                "applicable_policy_refs_json": [system_policy["policy_id"]],
                "decision": "allow_with_logging",
                "rationale_summary": "Local trusted validation tool with audit requirement.",
            },
        )
        invocation = store.insert(
            "tool_invocations",
            {
                "tool_capability_id": capability["tool_capability_id"],
                "invoker_agent_id": agent["agent_id"],
                "sponsoring_user_id": admin["user_id"],
                "input_ref": content_ref,
                "output_ref": proof_ref,
                "policy_decision_refs_json": [policy_decision["policy_decision_id"]],
                "status": "completed",
                "started_at": "2026-04-22T15:03:00Z",
                "ended_at": "2026-04-22T15:04:00Z",
            },
        )
        sub_agent = store.insert(
            "sub_agent_runs",
            {
                "parent_agent_id": agent["agent_id"],
                "sponsor_user_id": admin["user_id"],
                "goal": "Check representative validation records.",
                "scope_json": {"commitment_id": commitment["commitment_id"]},
                "authority_scope_json": {"may_read": [project["project_id"]], "may_write": []},
                "input_artifacts_json": [artifact["artifact_id"]],
                "deliverable_expectation_json": {"type": "summary"},
                "provenance_refs_json": [invocation["tool_invocation_id"]],
                "result_summary": "Records are retrievable.",
                "status": "completed",
                "started_at": "2026-04-22T15:04:00Z",
                "ended_at": "2026-04-22T15:05:00Z",
            },
        )
        audit = store.insert(
            "audit_events",
            {
                "event_type": "tool_invocation_completed",
                "actor_type": "agent",
                "actor_ref": agent["agent_id"],
                "object_type": "tool_invocation",
                "object_ref": invocation["tool_invocation_id"],
                "action_summary": "Completed local validation write.",
                "outcome": "completed",
                "policy_decision_id": policy_decision["policy_decision_id"],
                "metadata_json": {"sub_agent_run_id": sub_agent["sub_agent_run_id"]},
            },
        )
        store.append_event(
            "tool_invocation_completed",
            "tool_invocation",
            invocation["tool_invocation_id"],
            "agent",
            agent["agent_id"],
            {"audit_event_id": audit["audit_event_id"]},
            audit_event_id=audit["audit_event_id"],
        )

        created = {
            "admin": ("users", admin["user_id"]),
            "extra_user": ("users", extra_user["user_id"]),
            "agent": ("agents", agent["agent_id"]),
            "shared_context": ("shared_contexts", shared_context["shared_context_id"]),
            "authority_grant": ("authority_grants", authority_grant["grant_id"]),
            "policy": ("policies", system_policy["policy_id"]),
            "classification_rule": ("data_classification_rules", external_rule["rule_id"]),
            "channel_identity": ("channel_identities", channel["channel_identity_id"]),
            "thread": ("threads", thread["thread_id"]),
            "message": ("messages", message["message_event_id"]),
            "commitment": ("commitments", commitment["commitment_id"]),
            "progress_update": ("progress_updates", progress["progress_update_id"]),
            "attention": ("task_attention_records", attention["attention_record_id"]),
            "waiting_condition": ("waiting_conditions", waiting["waiting_condition_id"]),
            "blocker": ("blocker_records", blocker["blocker_id"]),
            "completion_proof": ("completion_proofs", completion_proof["completion_proof_id"]),
            "tool_capability": ("tool_capabilities", capability["tool_capability_id"]),
            "tool_invocation": ("tool_invocations", invocation["tool_invocation_id"]),
            "sub_agent_run": ("sub_agent_runs", sub_agent["sub_agent_run_id"]),
            "memory": ("memory_records", memory["memory_id"]),
            "corpus": ("knowledge_corpora", corpus["corpus_id"]),
            "search": ("search_runs", search["search_run_id"]),
            "research": ("research_runs", research["research_run_id"]),
            "project": ("projects", project["project_id"]),
            "artifact": ("artifacts", artifact["artifact_id"]),
            "audit_event": ("audit_events", audit["audit_event_id"]),
            "policy_decision": ("policy_decisions", policy_decision["policy_decision_id"]),
        }

        missing = [name for name, (table, record_id) in created.items() if store.get_by_id(table, record_id) is None]
        if missing:
            raise RuntimeError(f"Validation retrieval failed for: {missing}")

        members = store.list_shared_context_members(shared_context["shared_context_id"])
        if {member["member_ref"] for member in members} != {admin["user_id"], extra_user["user_id"]}:
            raise RuntimeError("Shared context membership validation failed")

        event_count = len(store.list_records("event_log", 500))
        if event_count < len(created):
            raise RuntimeError(f"Expected append-only event coverage, got {event_count} events")

        print(
            json.dumps(
                {
                    "ok": True,
                    "db": str(store.db_path),
                    "artifact_root": str(store.artifact_root),
                    "created_and_retrieved": sorted(created),
                    "event_log_rows": event_count,
                    "admin_user_id": admin["user_id"],
                    "extra_user_id": extra_user["user_id"],
                    "generic_user_path_reused": extra_user["primary_user_flag"] == 0,
                    "shared_context_member_count": len(members),
                    "policy_decision": policy_decision["decision"],
                    "audit_event_id": audit["audit_event_id"],
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
