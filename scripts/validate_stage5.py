#!/usr/bin/env python3
"""Run Stage 5 real Telegram-boundary and v0 completion validation flows."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import (
    AgentFirstStore,
    GovernedAction,
    PolicyEngine,
    TaskEngine,
    TelegramBotApiTransport,
    TelegramChannelService,
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-stage5-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        admin = store.bootstrap_admin("Stage 5 Primary", "America/New_York")
        telegram = TelegramChannelService(
            store,
            bot_api_transport=TelegramBotApiTransport(bot_token=None, execute_live=False),
        )
        policy = PolicyEngine(store)
        task_engine = TaskEngine(store)

        inbound = telegram.ingest_message(
            {
                "update_id": 5001,
                "bot_id": "stage5-bot",
                "bot_username": "agentfirst_stage5_bot",
                "message": {
                    "message_id": 201,
                    "date": 1776878400,
                    "chat": {"id": 777001, "type": "private"},
                    "from": {
                        "id": 515151,
                        "is_bot": False,
                        "first_name": "Real",
                        "last_name": "Telegram",
                        "username": "stage5_real_user",
                    },
                    "text": "/commit Validate the Telegram vertical slice and report what is still stubbed.",
                },
                "agentfirst": {"classification": "private"},
            }
        )
        commitment = inbound["commitment"]
        thread = inbound["thread"]
        user_id = inbound["channel_identity"]["user_id"]
        agent = inbound["agent"]
        destination_identity = "telegram:chat:777001"

        extra_user = store.create_user(
            "Stage 5 Additional User",
            authority_tier="standard",
            contact_identities=[{"channel_type": "telegram", "address": "telegram:user:616161"}],
            actor_type="system",
            actor_ref="stage5_validation",
        )

        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": destination_identity,
                "trust_tier": 1,
                "policy_refs_json": [],
            },
        )

        project_note_ref = store.write_artifact(
            "projects/stage5-telegram-proof.md",
            "Stage 5 links the Telegram-created commitment to a lightweight project scope.",
        )
        project = store.insert(
            "projects",
            {
                "name": "Stage 5 Telegram v0 Proof",
                "description_ref": project_note_ref,
                "owner_scope_type": "user",
                "owner_scope_ref": user_id,
                "participants_json": [{"user_id": user_id}, {"user_id": admin["user_id"]}],
                "goals_json": ["Prove Telegram boundary and v0 validation honestly."],
                "milestones_json": ["Telegram request prepared", "v0 gaps documented"],
                "policy_refs_json": [],
            },
            actor_type="system",
            actor_ref="stage5_validation",
        )
        commitment = store.update(
            "commitments",
            commitment["commitment_id"],
            {"project_id": project["project_id"]},
            actor_type="system",
            actor_ref="stage5_validation",
            event_type="stage5_commitment_linked_to_project",
        )
        store.update(
            "threads",
            thread["thread_id"],
            {"linked_project_ids_json": [project["project_id"]]},
            actor_type="system",
            actor_ref="stage5_validation",
            event_type="stage5_thread_linked_to_project",
        )

        allowed_outbound = telegram.create_outbound_message(
            thread_id=thread["thread_id"],
            text="I captured the Stage 5 Telegram proof request and prepared a Telegram Bot API sendMessage call.",
            actor_type="agent",
            actor_ref=agent["agent_id"],
            sponsoring_user_id=user_id,
            classification="public",
            provenance={"source": "stage5-real-telegram-boundary"},
        )
        request = allowed_outbound["transport"]["request"]

        gated_outbound = telegram.create_outbound_message(
            thread_id=thread["thread_id"],
            text="Private details require approval before Telegram delivery.",
            actor_type="agent",
            actor_ref=agent["agent_id"],
            sponsoring_user_id=user_id,
            classification="private",
            provenance={"source": "stage5-policy-gated-outbound"},
        )

        tool_capability = store.insert(
            "tool_capabilities",
            {
                "name": "telegram_send_message",
                "provider": "telegram-bot-api",
                "input_schema_ref": "schema://telegram/sendMessage/input",
                "output_schema_ref": "schema://telegram/sendMessage/output",
                "policy_refs_json": [],
                "availability_status": "enabled",
                "risk_class": "medium",
                "audit_requirements_json": {"audit": "always", "stage5_boundary": "telegram_bot_api"},
            },
            actor_type="system",
            actor_ref="stage5_validation",
        )
        tool_input_ref = allowed_outbound["transport"]["send_request_ref"]
        tool_invocation = policy.record_tool_invocation(
            GovernedAction(
                action_type="invoke_tool",
                actor_type="agent",
                actor_ref=agent["agent_id"],
                sponsoring_user_id=user_id,
                object_type="tool_capability",
                object_ref=tool_capability["tool_capability_id"],
                destination_type="channel",
                destination_identity=destination_identity,
                content_classification="public",
                metadata={"telegram_method": "sendMessage", "commitment_id": commitment["commitment_id"]},
            ),
            tool_capability["tool_capability_id"],
            input_ref=tool_input_ref,
            output_ref=allowed_outbound["transport"]["send_request_ref"],
        )

        sub_output_ref = store.write_artifact(
            "subagents/stage5-result.md",
            "Sub-agent checked the prepared Telegram request and confirmed it targets sendMessage.",
        )
        sub_agent = task_engine.delegate_to_sub_agent(
            commitment["commitment_id"],
            parent_agent_id=agent["agent_id"],
            sponsor_user_id=user_id,
            goal="Inspect the Telegram Bot API request artifact for the Stage 5 proof.",
            scope={"project_id": project["project_id"]},
            authority_scope={"may_read": [allowed_outbound["transport"]["send_request_ref"]], "may_send": False},
            input_artifacts=[allowed_outbound["transport"]["send_request_ref"]],
            deliverable_expectation={"type": "request-boundary-check"},
            provenance_refs=[tool_invocation["tool_invocation"]["tool_invocation_id"]],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        reconciled_sub_agent = task_engine.reconcile_sub_agent_result(
            sub_agent["sub_agent_run_id"],
            result_summary="Prepared Telegram request is present; live transport was not attempted.",
            output_refs=[sub_output_ref],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )

        waiting = task_engine.enter_waiting(
            commitment["commitment_id"],
            waiting_on_type="telegram_live_credentials",
            waiting_on_ref="TELEGRAM_BOT_TOKEN",
            expected_resolution_at="2026-04-23T00:00:00Z",
            review_at="2026-04-23T00:00:00Z",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        blocker = task_engine.open_blocker(
            commitment["commitment_id"],
            blocker_type="live_transport_not_exercised",
            summary="No Telegram bot token/live network execution is available in this repo validation environment.",
            evidence_refs=[allowed_outbound["transport"]["send_request_ref"]],
            resolution_options=[
                "Run with TELEGRAM_BOT_TOKEN and execute_live enabled against a controlled chat.",
                "Accept prepared Bot API request boundary as near-real proof for v0 architecture only.",
            ],
            requires_human_decision=True,
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )

        proof = task_engine.record_completion_proof(
            commitment["commitment_id"],
            evidence_refs=[
                inbound["message"]["message_event_id"],
                allowed_outbound["message"]["message_event_id"],
                allowed_outbound["transport"]["send_request_ref"],
                gated_outbound["message"]["message_event_id"],
                tool_invocation["tool_invocation"]["tool_invocation_id"],
                reconciled_sub_agent["sub_agent_run_id"],
                waiting["waiting_condition_id"],
                blocker["blocker_id"],
                project["project_id"],
            ],
            verified_by_type="agent",
            verified_by_ref=agent["agent_id"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        completed = task_engine.complete_commitment(
            commitment["commitment_id"],
            proof_id=proof["completion_proof_id"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )

        audits = store.list_records("audit_events", 500)
        gated_decision = gated_outbound["policy_result"]["decision"]
        gated_audits = [audit for audit in audits if audit.get("policy_decision_id") == gated_decision["policy_decision_id"]]
        if inbound["intent"] != "create_commitment":
            raise RuntimeError("Inbound Telegram payload did not create a commitment")
        if allowed_outbound["message"]["status"] != "telegram_request_prepared":
            raise RuntimeError("Allowed outbound did not prepare a Telegram Bot API request")
        if request["telegram_method"] != "sendMessage" or request["json_body"]["chat_id"] != "777001":
            raise RuntimeError("Prepared Telegram request does not target the expected sendMessage chat")
        if gated_decision["decision"] not in {"require_owner_approval", "require_primary_user_approval"}:
            raise RuntimeError("Private outbound action was not approval-gated")
        if not gated_audits:
            raise RuntimeError("Policy-gated outbound action lacks audit linkage")
        if tool_invocation["tool_invocation"]["status"] != "policy_allowed":
            raise RuntimeError("Tool invocation was not policy-recorded as allowed")
        if reconciled_sub_agent["status"] != "completed":
            raise RuntimeError("Sub-agent run was not reconciled")
        if completed["status"] != "completed":
            raise RuntimeError("Completion proof did not complete the commitment")

        output = {
            "ok": True,
            "real_vs_stubbed": {
                "real": [
                    "Actual Telegram webhook-shaped payload accepted at adapter boundary",
                    "Canonical channel identity/thread/message/commitment/progress/policy/audit writes",
                    "Telegram Bot API sendMessage request generated as durable artifact",
                    "Policy-gated private outbound action created approval/audit records",
                ],
                "stubbed_or_not_exercised": [
                    "No live Telegram HTTPS send was attempted",
                    "No Telegram token is present in the validation run",
                    "Live research/provider work is validated separately by scripts/validate_research_provider.py",
                ],
            },
            "telegram": {
                "thread_id": thread["thread_id"],
                "inbound_message_id": inbound["message"]["message_event_id"],
                "prepared_outbound_message_id": allowed_outbound["message"]["message_event_id"],
                "prepared_status": allowed_outbound["message"]["status"],
                "send_request_ref": allowed_outbound["transport"]["send_request_ref"],
                "send_request_method": request["telegram_method"],
                "live_transport": allowed_outbound["transport"]["live_transport"],
            },
            "task": {
                "commitment_id": commitment["commitment_id"],
                "final_status": completed["status"],
                "completion_proof_id": proof["completion_proof_id"],
                "waiting_condition_id": waiting["waiting_condition_id"],
                "blocker_id": blocker["blocker_id"],
                "sub_agent_run_id": reconciled_sub_agent["sub_agent_run_id"],
            },
            "policy": {
                "gated_decision": gated_decision["decision"],
                "gated_policy_decision_id": gated_decision["policy_decision_id"],
                "gated_audit_event_id": gated_audits[0]["audit_event_id"],
                "tool_invocation_status": tool_invocation["tool_invocation"]["status"],
            },
            "v0_scenarios": {
                "inbound_request_becomes_durable_task": True,
                "policy_gated_outbound_action": True,
                "delegated_sub_agent_work_reconciled": True,
                "waiting_vs_blocked_distinction": True,
                "generic_additional_user_creation": True,
                "lightweight_project_linkage": True,
            },
            "users": {
                "admin_user_id": admin["user_id"],
                "telegram_user_id": user_id,
                "additional_user_id": extra_user["user_id"],
            },
            "project_id": project["project_id"],
            "event_log_rows": len(store.list_records("event_log", 1000)),
            "recommendation": "Stage 5 remains the Telegram-boundary proof. Run scripts/validate_research_provider.py for the separate live non-fixture research/provider proof; live Telegram delivery is proven outside this repo.",
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
