#!/usr/bin/env python3
"""Run Stage 4 Telegram-first channel integration validation flows."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import AgentFirstStore, OperatorSurface, TelegramChannelService, TaskEngine


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-stage4-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        admin = store.bootstrap_admin("Stage 4 Primary", "America/New_York")
        telegram = TelegramChannelService(store)
        enrollment = telegram.issue_enrollment_challenge(
            telegram_user_id="424242",
            display_name="Telegram User",
            username="stage4_user",
            requested_by_type="user",
            requested_by_ref=admin["user_id"],
        )
        verified = telegram.verify_enrollment_challenge(
            enrollment["enrollment_id"],
            challenge_secret=enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="stage4_validation_pairing",
        )
        OperatorSurface(store).resolve_approval(
            verified["metadata_json"]["approval_record_id"],
            actor_user_id=admin["user_id"],
            status="approved",
            confirmation="APPROVED",
        )
        telegram.approve_enrollment(
            verified["enrollment_id"],
            user_id=admin["user_id"],
            approver_user_id=admin["user_id"],
        )

        inbound = telegram.ingest_message(
            {
                "update_id": 4001,
                "bot_id": "stage4-bot",
                "bot_username": "agentfirst_stage4_bot",
                "message": {
                    "message_id": 101,
                    "date": 1776792000,
                    "chat": {"id": 999001, "type": "private"},
                    "from": {
                        "id": 424242,
                        "is_bot": False,
                        "first_name": "Telegram",
                        "last_name": "User",
                        "username": "stage4_user",
                    },
                    "text": "/commit Prepare a concise project status note for Friday.",
                },
                "agentfirst": {"classification": "private"},
            }
        )
        commitment = inbound["commitment"]
        thread = inbound["thread"]
        user_id = inbound["channel_identity"]["user_id"]
        agent = inbound["agent"]
        destination_identity = "telegram:chat:999001"

        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": destination_identity,
                "trust_tier": 1,
                "policy_refs_json": [],
            },
        )

        update = telegram.ingest_message(
            {
                "update_id": 4002,
                "bot_id": "stage4-bot",
                "bot_username": "agentfirst_stage4_bot",
                "message": {
                    "message_id": 102,
                    "date": 1776792060,
                    "chat": {"id": 999001, "type": "private"},
                    "from": {
                        "id": 424242,
                        "is_bot": False,
                        "first_name": "Telegram",
                        "last_name": "User",
                        "username": "stage4_user",
                    },
                    "text": "update: Include the product launch milestone and ask whether risks changed.",
                },
            }
        )

        outbound = telegram.create_outbound_message(
            thread_id=thread["thread_id"],
            text="I captured this and will prepare the Friday status note.",
            actor_type="agent",
            actor_ref=agent["agent_id"],
            sponsoring_user_id=user_id,
            classification="public",
            provenance={"source": "stage4-validation-direct-outbound"},
        )

        task_engine = TaskEngine(store)
        visible_progress = task_engine.record_progress_update(
            commitment["commitment_id"],
            summary="Draft status-note outline is ready for review.",
            state_change={
                "source": "stage4_validation",
                "current_state": "active",
                "next_action": "surface progress through Telegram path",
            },
            visibility="user",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        surfaced = telegram.surface_progress_update(
            visible_progress["progress_update_id"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
            sponsoring_user_id=user_id,
            classification="internal",
        )

        if inbound["intent"] != "create_commitment":
            raise RuntimeError("Inbound Telegram message did not create a commitment")
        if commitment["status"] != "active":
            raise RuntimeError("Created commitment was not activated")
        if update["intent"] != "update_commitment" or update["progress_update"] is None:
            raise RuntimeError("Inbound Telegram update did not update the active commitment")
        if outbound["message"]["status"] != "send_stubbed":
            raise RuntimeError("Allowed outbound Telegram message was not prepared for stubbed send")
        if not outbound["message"]["policy_decision_refs_json"]:
            raise RuntimeError("Outbound message is missing policy decision linkage")
        if surfaced["message"]["status"] != "send_stubbed":
            raise RuntimeError("Progress update was not surfaced through Telegram outbound path")
        if not surfaced["message"]["policy_decision_refs_json"]:
            raise RuntimeError("Surfaced progress update is missing policy decision linkage")

        policy_decision_id = surfaced["message"]["policy_decision_refs_json"][0]
        audits = [
            audit
            for audit in store.list_records("audit_events", 200)
            if audit.get("policy_decision_id") == policy_decision_id
        ]
        if not audits:
            raise RuntimeError("Policy decision audit linkage was not recorded")

        thread_after = store.get_by_id("threads", thread["thread_id"])
        assert thread_after is not None
        if commitment["commitment_id"] not in thread_after["linked_commitment_ids_json"]:
            raise RuntimeError("Thread was not linked to the created commitment")

        output = {
            "ok": True,
            "telegram_channel_identity_id": inbound["channel_identity"]["channel_identity_id"],
            "telegram_thread_id": thread["thread_id"],
            "inbound_message_id": inbound["message"]["message_event_id"],
            "commitment_id": commitment["commitment_id"],
            "commitment_status": store.get_by_id("commitments", commitment["commitment_id"])["status"],
            "update_progress_id": update["progress_update"]["progress_update_id"],
            "outbound_message_status": outbound["message"]["status"],
            "outbound_policy_decision": outbound["policy_result"]["decision"]["decision"],
            "surfaced_progress_message_status": surfaced["message"]["status"],
            "surfaced_progress_policy_decision": surfaced["policy_result"]["decision"]["decision"],
            "policy_audit_event_id": audits[0]["audit_event_id"],
            "thread_linked_commitments": thread_after["linked_commitment_ids_json"],
            "event_log_rows": len(store.list_records("event_log", 500)),
            "admin_user_id": admin["user_id"],
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
