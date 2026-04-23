#!/usr/bin/env python3
"""Validate V1 Chunk 11 integrated acceptance across bounded V1 surfaces."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import (
    AgentFirstStore,
    AuthorityEngine,
    BlueBubblesChannelService,
    GovernedAction,
    GoogleWorkspaceRequest,
    GoogleWorkspaceService,
    MemoryRetrievalRequest,
    MemoryScope,
    MemoryService,
    ModelPreferenceRequest,
    ModelRouteRequest,
    ModelRoutingService,
    PolicyEngine,
    ProjectWorkService,
    TelegramChannelService,
    ToolInvocationRequest,
    OperatorSurface,
    ToolingService,
    TrustedOperatorTUI,
)
from agentfirst_storage.store import new_id


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def audit_types(store: AgentFirstStore) -> set[str]:
    return {audit["event_type"] for audit in store.list_records("audit_events", 1000)}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk11-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 11 Primary", "America/New_York")
        alex = store.create_user(
            display_name="Alex Integrated Owner",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        blair = store.create_user(
            display_name="Blair Integrated Contributor",
            authority_tier="standard",
            default_timezone="America/Chicago",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        casey = store.create_user(
            display_name="Casey Integrated Outsider",
            authority_tier="standard",
            default_timezone="America/Denver",
            actor_type="user",
            actor_ref=primary["user_id"],
        )

        authority = AuthorityEngine(store)
        policy = PolicyEngine(store)
        telegram = TelegramChannelService(store, authority_engine=authority, policy_engine=policy)
        bluebubbles = BlueBubblesChannelService(store, authority_engine=authority, policy_engine=policy)
        google = GoogleWorkspaceService(store, authority_engine=authority, policy_engine=policy)
        tooling = ToolingService(store, authority_engine=authority, policy_engine=policy)
        memory = MemoryService(store, authority_engine=authority)
        models = ModelRoutingService(store, policy_engine=policy)
        project_work = ProjectWorkService(store, authority)

        trusted_before = {
            "users": count(store, "users"),
            "messages": count(store, "messages"),
            "threads": count(store, "threads"),
            "commitments": count(store, "commitments"),
            "channel_identities": count(store, "channel_identities"),
        }
        unknown_telegram = telegram.ingest_message(
            {
                "update_id": 211001,
                "bot_id": "v1-integrated-bot",
                "message": {
                    "message_id": 1,
                    "date": 1776792000,
                    "chat": {"id": 211001, "type": "private"},
                    "from": {"id": 900001, "is_bot": False, "first_name": "Unknown"},
                    "text": "/commit This must stay outside trusted state.",
                },
            }
        )
        trusted_after_unknown = {
            "users": count(store, "users"),
            "messages": count(store, "messages"),
            "threads": count(store, "threads"),
            "commitments": count(store, "commitments"),
            "channel_identities": count(store, "channel_identities"),
        }
        if unknown_telegram["intent"] != "enrollment_required" or not unknown_telegram["contained"]:
            raise RuntimeError("Unknown Telegram inbound was not contained")
        if trusted_after_unknown != trusted_before:
            raise RuntimeError("Unknown Telegram inbound mutated trusted canonical state")

        tg_enrollment = telegram.issue_enrollment_challenge(
            telegram_user_id="900002",
            display_name="Alex Telegram",
            username="alex_integrated",
            requested_by_type="user",
            requested_by_ref=primary["user_id"],
        )
        tg_verified = telegram.verify_enrollment_challenge(
            tg_enrollment["enrollment_id"],
            challenge_secret=tg_enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=tg_enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="chunk11_pairing_code",
        )
        OperatorSurface(store).resolve_approval(
            tg_verified["metadata_json"]["approval_record_id"],
            actor_user_id=primary["user_id"],
            status="approved",
            confirmation="APPROVED",
        )
        telegram.approve_enrollment(
            tg_verified["enrollment_id"],
            user_id=alex["user_id"],
            approver_user_id=primary["user_id"],
        )
        trusted_telegram = telegram.ingest_message(
            {
                "update_id": 211002,
                "bot_id": "v1-integrated-bot",
                "message": {
                    "message_id": 2,
                    "date": 1776792060,
                    "chat": {"id": 211002, "type": "private"},
                    "from": {
                        "id": 900002,
                        "is_bot": False,
                        "first_name": "Alex",
                        "username": "alex_integrated",
                    },
                    "text": "/commit Integrated Telegram commitment",
                },
            }
        )
        if trusted_telegram["intent"] != "create_commitment":
            raise RuntimeError("Enrolled Telegram message did not create trusted work")

        bb_enrollment = bluebubbles.issue_enrollment_challenge(
            sender_address="+15555550101",
            display_name="Alex iMessage",
            requested_by_type="user",
            requested_by_ref=primary["user_id"],
        )
        bb_verified = bluebubbles.verify_enrollment_challenge(
            bb_enrollment["enrollment_id"],
            challenge_secret=bb_enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=bb_enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="chunk11_pairing_code",
        )
        OperatorSurface(store).resolve_approval(
            bb_verified["metadata_json"]["approval_record_id"],
            actor_user_id=primary["user_id"],
            status="approved",
            confirmation="APPROVED",
        )
        bluebubbles.approve_enrollment(
            bb_verified["enrollment_id"],
            user_id=alex["user_id"],
            approver_user_id=primary["user_id"],
        )
        trusted_bluebubbles = bluebubbles.ingest_message(
            {
                "message": {
                    "guid": "bb-msg-integrated-1",
                    "chatGuid": "iMessage;+;+15555550101",
                    "text": "/commit Integrated BlueBubbles commitment",
                    "handle": {"address": "+15555550101", "type": "phone", "displayName": "Alex iMessage"},
                },
                "agentfirst": {"thread_class": "direct_1to1"},
            }
        )
        if trusted_bluebubbles["intent"] != "create_commitment":
            raise RuntimeError("Enrolled BlueBubbles message did not create trusted work")

        alex_google = google.create_connection(
            user_id=alex["user_id"],
            google_account_email="alex.integrated@example.com",
            services=["gmail", "calendar", "contacts", "drive"],
            scopes=["gmail.readonly", "calendar.readonly", "contacts.readonly", "drive.metadata.readonly"],
            credential_ref="secret://google/alex-integrated",
            actor_user_id=alex["user_id"],
        )
        blair_google = google.create_connection(
            user_id=blair["user_id"],
            google_account_email="blair.integrated@example.com",
            services=["gmail"],
            scopes=["gmail.readonly"],
            credential_ref="secret://google/blair-integrated",
            actor_user_id=blair["user_id"],
        )
        own_gmail = google.perform_action(
            GoogleWorkspaceRequest(
                actor_user_id=alex["user_id"],
                target_user_id=alex["user_id"],
                service="gmail",
                operation="list_recent_messages",
                google_connection_id=alex_google["google_connection_id"],
            )
        )
        if own_gmail["action"]["status"] != "completed":
            raise RuntimeError("Own-account Gmail action did not complete")
        cross_user_blocked = False
        try:
            google.perform_action(
                GoogleWorkspaceRequest(
                    actor_user_id=blair["user_id"],
                    target_user_id=alex["user_id"],
                    service="drive",
                    operation="list_alex_drive_without_grant",
                    google_connection_id=alex_google["google_connection_id"],
                )
            )
        except PermissionError:
            cross_user_blocked = True
        if not cross_user_blocked:
            raise RuntimeError("Cross-user Google access was not blocked")
        grant = authority.create_supervisory_grant(
            grantor_user_id=primary["user_id"],
            grantee_user_id=blair["user_id"],
            target_user_id=alex["user_id"],
            permissions=["read"],
            constraints=[{"scope": "chunk11_integrated_google_calendar"}],
        )
        granted_calendar = google.perform_action(
            GoogleWorkspaceRequest(
                actor_user_id=blair["user_id"],
                target_user_id=alex["user_id"],
                service="calendar",
                operation="list_alex_calendar_with_grant",
                google_connection_id=alex_google["google_connection_id"],
            )
        )
        if granted_calendar["action"]["status"] != "completed":
            raise RuntimeError("Granted cross-user Google action did not complete")
        if blair_google["user_id"] != blair["user_id"]:
            raise RuntimeError("Separate Google connection ownership was not retained")

        project_policy = store.insert(
            "policies",
            {
                "policy_id": new_id("pol"),
                "policy_type": "project",
                "owner_user_id": alex["user_id"],
                "priority": 20,
                "rules_json": [
                    {
                        "action": "export",
                        "classification_floor": "internal",
                        "decision": "deny",
                        "rationale": "Integrated project artifacts stay internal during acceptance.",
                    }
                ],
                "targets_json": ["project", "artifact", "commitment"],
                "status": "active",
            },
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        project = project_work.create_project(
            name="Chunk 11 Integrated Acceptance Project",
            owner_scope_type="user",
            owner_scope_ref=alex["user_id"],
            actor_user_id=alex["user_id"],
            goals=["Exercise project, memory, tools, policy, audit, and operator review together."],
            participants=[
                {
                    "subject_type": "user",
                    "subject_ref": blair["user_id"],
                    "role": "contributor",
                    "permissions": ["read", "monitor", "intervene"],
                }
            ],
            milestones=[{"title": "Acceptance evidence assembled", "status": "active"}],
            policy_refs=[project_policy["policy_id"]],
        )
        artifact = store.insert(
            "artifacts",
            {
                "artifact_id": new_id("art"),
                "name": "Chunk 11 Integrated Evidence",
                "artifact_type": "document",
                "storage_ref": store.write_artifact(
                    "projects/chunk11/evidence.md",
                    "Integrated acceptance evidence for project artifact linkage.",
                ),
                "owner_scope_type": "user",
                "owner_scope_ref": alex["user_id"],
                "source_refs_json": [],
                "project_refs_json": [],
                "classification": "internal",
                "provenance_json": {"chunk": "v1-chunk11"},
                "status": "created",
            },
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        linked_artifact = project_work.link_artifact(
            project["project_id"],
            artifact["artifact_id"],
            actor_user_id=alex["user_id"],
            link_reason="chunk11 integrated evidence",
        )
        project_commitment = project_work.create_project_commitment(
            project["project_id"],
            title="Complete integrated acceptance sweep",
            commitment_type="validation",
            actor_user_id=blair["user_id"],
            next_action="Run integrated validator and inspect operator guide.",
            completion_criteria={"proof_required": True, "artifact_id": linked_artifact["artifact_id"]},
        )
        outsider_denied = False
        try:
            project_work.get_project_work_bundle(project["project_id"], actor_user_id=casey["user_id"])
        except PermissionError:
            outsider_denied = True
        if not outsider_denied:
            raise RuntimeError("Project outsider read was not denied")

        memory.create_memory(
            owner_scope_type="user",
            owner_scope_ref=alex["user_id"],
            memory_type="preference",
            body="Alex private integrated memory contains the keyword falcon.",
            source_refs=[trusted_telegram["message"]["message_event_id"]],
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        memory.create_memory(
            owner_scope_type="project",
            owner_scope_ref=project["project_id"],
            memory_type="project_fact",
            body="The integrated acceptance project contains the keyword anchor.",
            source_refs=[linked_artifact["artifact_id"]],
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        denied_memory = memory.retrieve(
            MemoryRetrievalRequest(
                actor_user_id=casey["user_id"],
                sponsoring_user_id=casey["user_id"],
                query="falcon",
                scopes=[MemoryScope("user", alex["user_id"])],
            )
        )
        if denied_memory["retrieval"]["status"] != "denied":
            raise RuntimeError("Unauthorized private memory retrieval was not denied")
        project_memory = memory.retrieve(
            MemoryRetrievalRequest(
                actor_user_id=blair["user_id"],
                sponsoring_user_id=blair["user_id"],
                query="anchor",
                scopes=[MemoryScope("project", project["project_id"])],
            )
        )
        if project_memory["retrieval"]["status"] != "returned" or not project_memory["results"]:
            raise RuntimeError("Authorized project memory retrieval did not return provenance-bearing results")
        if not project_memory["results"][0]["provenance"].get("memory_id"):
            raise RuntimeError("Project memory result did not include provenance")

        completed_tool = tooling.invoke(
            ToolInvocationRequest(
                actor_user_id=blair["user_id"],
                sponsoring_user_id=blair["user_id"],
                capability_name="local.artifact_write",
                provider="agentfirst_core",
                operation="write_acceptance_note",
                scope_type="project",
                scope_ref=project["project_id"],
                input={"name": "chunk11-tool-output.md", "body": "Integrated tool output."},
            )
        )
        if not completed_tool["executed"]:
            raise RuntimeError("Authorized project tool action did not execute")
        denied_tool = tooling.invoke(
            ToolInvocationRequest(
                actor_user_id=casey["user_id"],
                sponsoring_user_id=casey["user_id"],
                capability_name="local.artifact_write",
                provider="agentfirst_core",
                operation="write_unauthorized_note",
                scope_type="project",
                scope_ref=project["project_id"],
                input={"name": "unauthorized.md", "body": "Should not execute."},
            )
        )
        if denied_tool["executed"] or denied_tool["tool_invocation"]["status"] != "authority_denied":
            raise RuntimeError("Unauthorized project tool action was not denied by authority")

        models.create_preference(
            ModelPreferenceRequest(
                scope_type="user",
                scope_ref=alex["user_id"],
                provider="openai",
                model="gpt-5.4",
                purpose="general",
                rationale_summary="Integrated acceptance prefers OpenAI with local fallback.",
                fallback_routes=[
                    {
                        "provider": "local",
                        "model": "llama.cpp-default",
                        "reason": "external provider unavailable",
                    }
                ],
                created_by_type="user",
                created_by_ref=alex["user_id"],
            )
        )
        fallback_route = models.route(
            ModelRouteRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                purpose="general",
                scope_type="user",
                scope_ref=alex["user_id"],
                unavailable_providers={"openai"},
                content_classification="internal",
            )
        )
        if not fallback_route["fallback_used"] or "fallback" not in fallback_route["disclosure"].lower():
            raise RuntimeError("Model fallback was not selected and disclosed")
        failed_route = models.route(
            ModelRouteRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                purpose="general",
                scope_type="user",
                scope_ref=alex["user_id"],
                unavailable_providers={"openai", "local"},
                content_classification="internal",
            )
        )
        if failed_route["route_decision"]["status"] != "failed":
            raise RuntimeError("Model route exhaustion did not record an honest failure")

        blocked_commitment = store.update(
            "commitments",
            project_commitment["commitment_id"],
            {"status": "blocked", "blocker_state_json": {"reason": "manual_acceptance_pending"}},
            actor_type="user",
            actor_ref=blair["user_id"],
            event_type="commitment_blocked_for_acceptance",
        )
        store.insert(
            "blocker_records",
            {
                "blocker_id": new_id("blk"),
                "commitment_id": blocked_commitment["commitment_id"],
                "blocker_type": "acceptance",
                "summary": "Manual operator acceptance is still required before V1 release.",
                "evidence_refs_json": [linked_artifact["artifact_id"]],
                "resolution_options_json": [{"option": "accept"}, {"option": "hold"}],
                "requires_human_decision": True,
                "status": "active",
            },
            actor_type="user",
            actor_ref=blair["user_id"],
        )
        approval_result = policy.evaluate_and_record(
            GovernedAction(
                action_type="export",
                actor_type="user",
                actor_ref=blair["user_id"],
                sponsoring_user_id=blair["user_id"],
                object_type="user",
                object_ref=blair["user_id"],
                destination_type="external_workspace",
                destination_identity="manual-acceptance-review",
                content_classification="private",
                metadata={"project_id": project["project_id"], "chunk": "v1-chunk11"},
            )
        )
        approval = approval_result["approval_record"]
        if approval is None:
            raise RuntimeError("Integrated approval setup did not create an approval record")

        tui = TrustedOperatorTUI(store)
        audit_before_tui = count(store, "audit_events")
        event_before_tui = count(store, "event_log")
        read_results = tui.run_script(["status", "approvals", "users", "tasks", "failures"])
        if count(store, "audit_events") != audit_before_tui or count(store, "event_log") != event_before_tui:
            raise RuntimeError("Read-only TUI commands mutated audit/event state")
        if not all(result.mode == "READ-ONLY" for result in read_results):
            raise RuntimeError("A read-only TUI command did not report READ-ONLY")
        failure_sources = {item["source"] for item in read_results[-1].data["failures"]}
        if "commitments" not in failure_sources or "tool_invocations" not in failure_sources:
            raise RuntimeError("TUI failure disclosure missed blocked work or denied tool action")
        admin_result = tui.handle_command(
            "admin approval approve "
            f"{approval['approval_record_id']} --actor {primary['user_id']} --confirm APPROVED"
        )
        if admin_result.mode != "ADMIN":
            raise RuntimeError("TUI approval resolution did not report ADMIN mode")
        resolved_approval = store.get_by_id("approval_records", approval["approval_record_id"])
        if resolved_approval is None or resolved_approval["status"] != "approved":
            raise RuntimeError("TUI approval resolution did not update approval state")

        required_audits = {
            "telegram_unauthorized_inbound_contained",
            "telegram_enrollment_owner_approved",
            "bluebubbles_enrollment_owner_approved",
            "google_workspace_action_recorded",
            "authority_evaluated",
            "project_created",
            "project_artifact_linked",
            "memory_retrieval_recorded",
            "tool_invocation_recorded",
            "model_route_decision_recorded",
            "operator_approval_resolved",
        }
        missing_audits = sorted(required_audits - audit_types(store))
        if missing_audits:
            raise RuntimeError(f"Integrated acceptance missing audit event(s): {missing_audits}")

        output = {
            "ok": True,
            "judgment": "CONDITIONAL GO for bounded V1 local acceptance; NO-GO for unqualified production launch",
            "decisions": {
                "unknown_inbound_contained": unknown_telegram["contained"],
                "telegram_enrolled_commitment_created": trusted_telegram["intent"] == "create_commitment",
                "bluebubbles_enrolled_commitment_created": trusted_bluebubbles["intent"] == "create_commitment",
                "google_cross_user_blocked": cross_user_blocked,
                "google_granted_cross_user_completed": granted_calendar["action"]["status"] == "completed",
                "project_outsider_denied": outsider_denied,
                "private_memory_denied": denied_memory["retrieval"]["status"] == "denied",
                "project_memory_returned_with_provenance": bool(project_memory["results"]),
                "tool_authorized_completed": completed_tool["executed"],
                "tool_unauthorized_denied": denied_tool["tool_invocation"]["status"] == "authority_denied",
                "model_fallback_disclosed": fallback_route["fallback_used"],
                "model_route_failure_recorded": failed_route["route_decision"]["status"] == "failed",
                "tui_read_only_non_mutating": True,
                "tui_admin_approval_resolved": resolved_approval["status"] == "approved",
            },
            "residual_risks": [
                "Validation uses local/stubbed adapters and temporary SQLite state, not live Telegram, BlueBubbles, Google OAuth, or model-provider credentials.",
                "Trusted TUI is bounded and plain; only approval resolution is implemented as a consequential admin action.",
                "Manual operator acceptance is still required before treating this as a real deployment candidate.",
            ],
            "counts": {
                "users": count(store, "users"),
                "channel_enrollments": count(store, "channel_enrollments"),
                "channel_identities": count(store, "channel_identities"),
                "messages": count(store, "messages"),
                "commitments": count(store, "commitments"),
                "google_workspace_actions": count(store, "google_workspace_actions"),
                "tool_invocations": count(store, "tool_invocations"),
                "model_route_decisions": count(store, "model_route_decisions"),
                "memory_retrievals": count(store, "memory_retrievals"),
                "policy_decisions": count(store, "policy_decisions"),
                "approval_records": count(store, "approval_records"),
                "audit_events": count(store, "audit_events"),
                "event_log": count(store, "event_log"),
            },
            "ids": {
                "primary_user_id": primary["user_id"],
                "alex_user_id": alex["user_id"],
                "blair_user_id": blair["user_id"],
                "casey_user_id": casey["user_id"],
                "supervisory_grant_id": grant["grant_id"],
                "project_id": project["project_id"],
                "approval_record_id": approval["approval_record_id"],
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
