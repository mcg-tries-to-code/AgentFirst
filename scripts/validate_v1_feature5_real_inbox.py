#!/usr/bin/env python3
"""Validate V1 Feature 5 truthful local real-inbox inspection."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentfirst_storage import AgentFirstStore, OperatorSurface, TrustedOperatorTUI
from agentfirst_storage.store import new_id


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def write_message_body(store: AgentFirstStore, name: str, body: str) -> str:
    return store.write_artifact(f"feature5-inbox/{name}.txt", body)


def create_identity(
    store: AgentFirstStore,
    *,
    user_id: str,
    channel_type: str,
    address: str,
    state: str = "enrolled",
    status: str = "active",
) -> dict:
    enrollment = store.insert(
        "channel_enrollments",
        {
            "enrollment_id": new_id("enr"),
            "channel_type": channel_type,
            "address": address,
            "user_id": user_id,
            "state": state,
            "challenge_status": "verified",
            "owner_approval_status": "approved",
            "status": status,
            "metadata_json": {"feature": "v1_feature5_real_inbox"},
        },
        actor_type="system",
        actor_ref="feature5_validation",
    )
    identity = store.insert(
        "channel_identities",
        {
            "channel_identity_id": new_id("chan"),
            "user_id": user_id,
            "channel_type": channel_type,
            "address": address,
            "enrollment_id": enrollment["enrollment_id"],
            "enrollment_state": state,
            "binding_generation": 1,
            "metadata_json": {"feature": "v1_feature5_real_inbox"},
            "routing_policy_refs_json": [],
            "status": status,
        },
        actor_type="system",
        actor_ref="feature5_validation",
    )
    return {"enrollment": enrollment, "identity": identity}


def add_message(
    store: AgentFirstStore,
    *,
    thread_id: str,
    direction: str,
    body: str,
    status: str = "stored",
    timestamp: str,
) -> dict:
    return store.insert(
        "messages",
        {
            "message_event_id": new_id("msg"),
            "thread_id": thread_id,
            "direction": direction,
            "sender_identity_json": {"validation": "feature5", "direction": direction},
            "recipient_identities_json": [],
            "content_ref": write_message_body(store, new_id("body"), body),
            "attachments_json": [],
            "classification": "internal",
            "provenance_json": {"local_mirror": True, "live_delivery_claimed": False},
            "policy_decision_refs_json": [],
            "status": status,
            "timestamp": timestamp,
        },
        actor_type="system",
        actor_ref="feature5_validation",
    )


def add_thread(
    store: AgentFirstStore,
    *,
    user_id: str,
    channel_type: str,
    identity_id: str,
    visibility_model: str = "private",
    mode: str | None = None,
    linked_commitment_ids: list[str] | None = None,
) -> dict:
    participant = {
        "channel_identity_id": identity_id,
        "participant_role": "enrolled_sender",
        "destination_identity": f"{channel_type}:validation:{identity_id}",
    }
    if mode:
        participant["telegram_thread_mode"] = mode
        participant["telegram_thread_behavior"] = "monitor_only" if mode == "monitored" else "direct_commitment_enabled"
    return store.insert(
        "threads",
        {
            "thread_id": new_id("thr"),
            "channel_type": channel_type,
            "ownership_context_type": "user",
            "ownership_context_ref": user_id,
            "participants_json": [participant],
            "visibility_model": visibility_model,
            "linked_project_ids_json": [],
            "linked_commitment_ids_json": linked_commitment_ids or [],
            "status": "active",
        },
        actor_type="system",
        actor_ref="feature5_validation",
    )


def add_thread_approval(store: AgentFirstStore, *, thread_id: str, actor_user_id: str, approver_user_id: str) -> dict:
    policy = store.insert(
        "policy_decisions",
        {
            "policy_decision_id": new_id("poldec"),
            "actor_type": "user",
            "actor_ref": actor_user_id,
            "sponsoring_user_id": actor_user_id,
            "action_type": "outbound_message",
            "object_type": "thread",
            "object_ref": thread_id,
            "destination_type": "external_channel",
            "destination_identity": "validation-inbox-target",
            "destination_trust_tier": 1,
            "content_classification": "private",
            "applicable_policy_refs_json": [],
            "decision": "require_primary_user_approval",
            "rationale_summary": "Feature 5 validation approval-gated outbound boundary.",
        },
        actor_type="system",
        actor_ref="feature5_validation",
    )
    return store.insert(
        "approval_records",
        {
            "approval_record_id": new_id("apr"),
            "policy_decision_id": policy["policy_decision_id"],
            "requested_by_type": "user",
            "requested_by_ref": actor_user_id,
            "approver_user_id": approver_user_id,
            "approval_type": "primary_user",
            "scope_json": {"thread_id": thread_id},
            "justification_summary": "Validate approval disclosure in real inbox.",
            "status": "requested",
        },
        actor_type="system",
        actor_ref="feature5_validation",
    )


def validate_empty_inbox() -> dict:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature5-empty-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()
        tui = TrustedOperatorTUI(store)
        audit_before = count(store, "audit_events")
        events_before = count(store, "event_log")
        result = tui.handle_command("inbox")
        audit_after = count(store, "audit_events")
        events_after = count(store, "event_log")
        if result.mode != "READ-ONLY" or not result.data["empty"]:
            raise RuntimeError("Empty inbox did not render as a read-only empty local inbox")
        if "No stored local inbox threads" not in result.text:
            raise RuntimeError("Empty inbox output did not disclose the empty state")
        if audit_before != audit_after or events_before != events_after:
            raise RuntimeError("Empty inbox read mutated audit or event state")
        return {"empty_disclosed": True, "read_only_preserved": True}


def validate_seeded_inbox() -> dict:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature5-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("Feature 5 Primary", "America/New_York")
        user = store.create_user(
            display_name="Feature 5 Inbox User",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        active_identity = create_identity(
            store,
            user_id=user["user_id"],
            channel_type="telegram",
            address="telegram:feature5-active",
        )["identity"]
        monitored_identity = create_identity(
            store,
            user_id=user["user_id"],
            channel_type="telegram",
            address="telegram:feature5-monitored",
        )["identity"]
        degraded_identity = create_identity(
            store,
            user_id=user["user_id"],
            channel_type="telegram",
            address="telegram:feature5-degraded",
            state="suspended",
            status="suspended",
        )["identity"]

        active_thread = add_thread(
            store,
            user_id=user["user_id"],
            channel_type="telegram",
            identity_id=active_identity["channel_identity_id"],
        )
        add_message(
            store,
            thread_id=active_thread["thread_id"],
            direction="inbound",
            body="Inbound stored local message for Feature 5.",
            timestamp="2026-04-23T10:00:00.000Z",
        )
        add_message(
            store,
            thread_id=active_thread["thread_id"],
            direction="outbound",
            body="Outbound stored local response for Feature 5.",
            timestamp="2026-04-23T10:05:00.000Z",
        )
        store.insert(
            "conversation_lanes",
            {
                "lane_id": new_id("lane"),
                "owner_scope_type": "user",
                "owner_scope_ref": user["user_id"],
                "lane_key": "feature5-inbox",
                "display_name": "Feature 5 Inbox Lane",
                "role": "support",
                "behavior_json": {"real_inbox_validation": True},
                "metadata_json": {"thread_id": active_thread["thread_id"]},
                "status": "active",
            },
            actor_type="system",
            actor_ref="feature5_validation",
        )

        monitored_thread = add_thread(
            store,
            user_id=user["user_id"],
            channel_type="telegram",
            identity_id=monitored_identity["channel_identity_id"],
            visibility_model="monitored",
            mode="monitored",
        )
        add_message(
            store,
            thread_id=monitored_thread["thread_id"],
            direction="inbound",
            body="Monitored stored message; outbound is not sendable.",
            timestamp="2026-04-23T10:10:00.000Z",
        )

        degraded_thread = add_thread(
            store,
            user_id=user["user_id"],
            channel_type="telegram",
            identity_id=degraded_identity["channel_identity_id"],
        )
        add_message(
            store,
            thread_id=degraded_thread["thread_id"],
            direction="inbound",
            body="Degraded enrollment message.",
            timestamp="2026-04-23T10:15:00.000Z",
        )

        approval_thread = add_thread(
            store,
            user_id=user["user_id"],
            channel_type="telegram",
            identity_id=active_identity["channel_identity_id"],
        )
        approval = add_thread_approval(
            store,
            thread_id=approval_thread["thread_id"],
            actor_user_id=user["user_id"],
            approver_user_id=primary["user_id"],
        )
        add_message(
            store,
            thread_id=approval_thread["thread_id"],
            direction="outbound",
            body="Drafted approval-gated outbound text; not sent.",
            status="drafted",
            timestamp="2026-04-23T10:20:00.000Z",
        )

        tui = TrustedOperatorTUI(store)
        audit_before = count(store, "audit_events")
        events_before = count(store, "event_log")
        results = tui.run_script(
            [
                "inbox",
                f"inbox thread {active_thread['thread_id']}",
                f"inbox thread {monitored_thread['thread_id']}",
                f"inbox thread {degraded_thread['thread_id']}",
                f"inbox thread {approval_thread['thread_id']}",
                "mode chat",
                "chat inbox",
                f"chat thread {approval_thread['thread_id']}",
            ]
        )
        audit_after = count(store, "audit_events")
        events_after = count(store, "event_log")
        if audit_before != audit_after or events_before != events_after:
            raise RuntimeError("Read-only inbox inspection mutated audit or event state")
        inbox_result = results[0]
        if inbox_result.mode != "READ-ONLY" or len(inbox_result.data["threads"]) != 4:
            raise RuntimeError("Inbox list did not expose the seeded local threads")
        if "NO LIVE CHANNEL" not in inbox_result.text or "DERIVED BADGES" not in inbox_result.text:
            raise RuntimeError("Inbox list did not disclose local/no-live/derived boundaries")

        details = {result.data.get("thread", {}).get("thread_id"): result for result in results[1:5]}
        active_detail = details[active_thread["thread_id"]]
        if [message["role_label"] for message in active_detail.data["messages"]] != ["INBOUND", "OUTBOUND"]:
            raise RuntimeError("Active thread detail did not preserve message timeline roles")
        monitored_item = details[monitored_thread["thread_id"]].data["thread"]
        if monitored_item["sendable"] is not False or "UNSENDABLE" not in monitored_item["badges"]:
            raise RuntimeError("Monitored thread was not marked unsendable")
        degraded_item = details[degraded_thread["thread_id"]].data["thread"]
        if "ENROLLMENT-DEGRADED" not in degraded_item["badges"] or not degraded_item["degraded_bindings"]:
            raise RuntimeError("Degraded enrollment state was not visible")
        approval_detail = details[approval_thread["thread_id"]]
        approval_item = approval_detail.data["thread"]
        if "APPROVAL-GATED" not in approval_item["badges"] or approval_detail.data["approvals"][0]["approval_record_id"] != approval["approval_record_id"]:
            raise RuntimeError("Approval-gated thread was not disclosed")
        if "LOCAL-DRAFT" not in approval_item["badges"] or not approval_detail.data["drafts"]:
            raise RuntimeError("Local draft state was not reported as unsent")
        if "UNSENT" not in approval_detail.text or "NO LIVE CHANNEL" not in approval_detail.text:
            raise RuntimeError("Thread detail did not show unsent/no-live disclosure")
        chat_inbox = results[6]
        chat_detail = results[7]
        if chat_inbox.mode != "READ-ONLY" or chat_detail.mode != "READ-ONLY":
            raise RuntimeError("Chat inbox inspection should be real read-only local inspection")
        if chat_inbox.data["disclosure"]["live_channel_integration"] is not False:
            raise RuntimeError("Chat inbox blurred the no-live-channel boundary")

        list_badges = {badge for item in inbox_result.data["threads"] for badge in item["badges"]}
        return {
            "threads_seen": len(inbox_result.data["threads"]),
            "degraded_states_seen": degraded_item["degraded_binding_count"],
            "approval_states_seen": approval_item["approval_count"],
            "drafts_seen": len(approval_detail.data["drafts"]),
            "read_only_audit_preserved": True,
            "badges_seen": sorted(list_badges),
            "approval_record_id": approval["approval_record_id"],
        }


def main() -> None:
    empty = validate_empty_inbox()
    seeded = validate_seeded_inbox()
    output = {
        "ok": True,
        "scenarios": {
            "empty_inbox": empty,
            "active_thread": True,
            "monitored_unsendable_thread": True,
            "approval_gated_thread": True,
            "enrollment_degraded_thread": True,
            "local_draft_unsent": True,
            "read_only_integrity": seeded["read_only_audit_preserved"],
            "chat_mode_real_local_inbox": True,
        },
        "threads_seen": seeded["threads_seen"],
        "degraded_states_seen": seeded["degraded_states_seen"],
        "approval_states_seen": seeded["approval_states_seen"],
        "drafts_seen": seeded["drafts_seen"],
        "read_only_audit_preserved": seeded["read_only_audit_preserved"],
        "badges_seen": seeded["badges_seen"],
        "approval_record_id": seeded["approval_record_id"],
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
