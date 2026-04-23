#!/usr/bin/env python3
"""Validate V1 Chunk 4 BlueBubbles/iMessage first-class surface."""

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
    BlueBubblesApiTransport,
    BlueBubblesChannelService,
    OperatorSurface,
)


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def enroll_bluebubbles(
    bluebubbles: BlueBubblesChannelService,
    *,
    sender_address: str,
    display_name: str,
    user_id: str,
    approver_user_id: str,
) -> dict[str, dict]:
    enrollment = bluebubbles.issue_enrollment_challenge(
        sender_address=sender_address,
        display_name=display_name,
        requested_by_type="user",
        requested_by_ref=approver_user_id,
    )
    verified = bluebubbles.verify_enrollment_challenge(
        enrollment["enrollment_id"],
        challenge_secret=enrollment["challenge_material"]["challenge_secret"],
        challenge_nonce=enrollment["challenge_material"]["challenge_nonce"],
        actor_type="system",
        actor_ref="v1_chunk4_pairing_validation",
    )
    OperatorSurface(bluebubbles.store).resolve_approval(
        verified["metadata_json"]["approval_record_id"],
        actor_user_id=approver_user_id,
        status="approved",
        confirmation="APPROVED",
    )
    return bluebubbles.approve_enrollment(
        verified["enrollment_id"],
        user_id=user_id,
        approver_user_id=approver_user_id,
    )


def inbound_event(
    *,
    guid: str,
    chat_guid: str,
    sender: str,
    text: str,
    display_name: str = "Chunk Four Sender",
    thread_class: str = "direct_1to1",
) -> dict:
    return {
        "type": "new-message",
        "message": {
            "guid": guid,
            "chatGuid": chat_guid,
            "isFromMe": False,
            "text": text,
            "dateCreated": 1776964800000,
            "handle": {
                "address": sender,
                "displayName": display_name,
                "type": "phone",
            },
            "threadClass": thread_class,
        },
        "agentfirst": {
            "thread_class": thread_class,
            "classification": "private",
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk4-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 4 Primary", "America/New_York")
        authority = AuthorityEngine(store)
        bluebubbles = BlueBubblesChannelService(
            store,
            authority_engine=authority,
            api_transport=BlueBubblesApiTransport(execute_live=False),
        )

        before_unknown = {
            "users": count(store, "users"),
            "channel_identities": count(store, "channel_identities"),
            "threads": count(store, "threads"),
            "messages": count(store, "messages"),
            "commitments": count(store, "commitments"),
        }
        unknown = bluebubbles.ingest_message(
            inbound_event(
                guid="IM-UNKNOWN-001",
                chat_guid="iMessage;-;+15555550100",
                sender="+1 (555) 555-0100",
                text="hello from an unknown iMessage sender",
                display_name="Unknown iMessage",
            )
        )
        after_unknown = {
            "users": count(store, "users"),
            "channel_identities": count(store, "channel_identities"),
            "threads": count(store, "threads"),
            "messages": count(store, "messages"),
            "commitments": count(store, "commitments"),
        }
        if unknown["intent"] != "enrollment_required" or not unknown["contained"]:
            raise RuntimeError("Unknown BlueBubbles inbound was not contained")
        for table, before in before_unknown.items():
            if after_unknown[table] != before:
                raise RuntimeError(f"Unknown BlueBubbles inbound changed trusted table: {table}")

        before_pairing = after_unknown
        pairing = bluebubbles.ingest_message(
            inbound_event(
                guid="IM-PAIR-001",
                chat_guid="iMessage;-;+15555550101",
                sender="+1 (555) 555-0101",
                text="/pair",
                display_name="Pairing iMessage",
            )
        )
        after_pairing = {
            "users": count(store, "users"),
            "channel_identities": count(store, "channel_identities"),
            "threads": count(store, "threads"),
            "messages": count(store, "messages"),
            "commitments": count(store, "commitments"),
        }
        if pairing["intent"] != "pairing_requested" or pairing["enrollment"]["state"] != "pairing_requested":
            raise RuntimeError("BlueBubbles pairing request did not enter pairing_requested state")
        for table, before in before_pairing.items():
            if after_pairing[table] != before:
                raise RuntimeError(f"Pairing request changed trusted table before enrollment: {table}")

        enrolled = enroll_bluebubbles(
            bluebubbles,
            sender_address="+1 (555) 555-0101",
            display_name="Pairing iMessage",
            user_id=primary["user_id"],
            approver_user_id=primary["user_id"],
        )
        trusted = bluebubbles.ingest_message(
            inbound_event(
                guid="IM-TRUSTED-001",
                chat_guid="iMessage;-;+15555550101",
                sender="+15555550101",
                text="/commit Capture this enrolled iMessage request.",
                display_name="Pairing iMessage",
            )
        )
        if trusted["intent"] != "create_commitment":
            raise RuntimeError("Enrolled BlueBubbles direct inbound did not create trusted work")
        thread = trusted["thread"]
        semantics = thread["participants_json"][-1]
        if semantics["bluebubbles_thread_mode"] != "direct":
            raise RuntimeError("BlueBubbles direct thread semantics were not stamped")
        if thread["ownership_context_type"] != "user" or thread["ownership_context_ref"] != primary["user_id"]:
            raise RuntimeError("BlueBubbles direct thread was not user-owned")

        group = bluebubbles.ingest_message(
            inbound_event(
                guid="IM-GROUP-001",
                chat_guid="chat-group-v1-chunk4",
                sender="+15555550101",
                text="/commit This group text must not create trusted work.",
                display_name="Pairing iMessage",
                thread_class="group",
            )
        )
        if group["intent"] != "unsupported_thread_contained" or group["commitment"] is not None:
            raise RuntimeError("Unsupported BlueBubbles group thread was not contained")

        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": "bluebubbles:chat:iMessage;-;+15555550101",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
        )
        allowed_outbound = bluebubbles.create_outbound_message(
            thread_id=thread["thread_id"],
            text="Public status captured for the enrolled direct iMessage thread.",
            actor_type="agent",
            actor_ref=trusted["agent"]["agent_id"],
            sponsoring_user_id=primary["user_id"],
            classification="public",
            provenance={"source": "v1-chunk4-validation-allowed"},
        )
        gated_outbound = bluebubbles.create_outbound_message(
            thread_id=thread["thread_id"],
            text="Private details require review before iMessage delivery.",
            actor_type="agent",
            actor_ref=trusted["agent"]["agent_id"],
            sponsoring_user_id=primary["user_id"],
            classification="private",
            provenance={"source": "v1-chunk4-validation-gated"},
        )
        if allowed_outbound["message"]["status"] != "bluebubbles_request_prepared":
            raise RuntimeError("Allowed BlueBubbles outbound did not prepare a send request")
        if not allowed_outbound["message"]["provenance_json"].get("authority_policy_decision_id"):
            raise RuntimeError("Allowed BlueBubbles outbound lacks authority decision linkage")
        if not allowed_outbound["message"]["provenance_json"].get("recipient_enrollment_refs"):
            raise RuntimeError("Allowed BlueBubbles outbound lacks enrolled-recipient linkage")
        if gated_outbound["policy_result"]["decision"]["decision"] not in {
            "require_owner_approval",
            "require_primary_user_approval",
        }:
            raise RuntimeError("Private BlueBubbles outbound was not policy-gated")

        suspended = bluebubbles.suspend_enrollment(
            enrolled["enrollment"]["enrollment_id"],
            actor_ref=primary["user_id"],
            reason="v1 chunk4 validation suspension",
        )
        suspended_inbound = bluebubbles.ingest_message(
            inbound_event(
                guid="IM-SUSPENDED-001",
                chat_guid="iMessage;-;+15555550101",
                sender="+15555550101",
                text="/commit Suspended enrollment must not route.",
                display_name="Pairing iMessage",
            )
        )
        try:
            bluebubbles.create_outbound_message(
                thread_id=thread["thread_id"],
                text="This suspended binding must not receive outbound iMessage traffic.",
                actor_type="agent",
                actor_ref=trusted["agent"]["agent_id"],
                sponsoring_user_id=primary["user_id"],
                classification="public",
            )
        except PermissionError:
            suspended_outbound_blocked = True
        else:
            suspended_outbound_blocked = False
        if suspended["state"] != "suspended" or suspended_inbound["intent"] != "enrollment_required":
            raise RuntimeError("Suspended BlueBubbles enrollment did not block trusted inbound")
        if not suspended_outbound_blocked:
            raise RuntimeError("Suspended BlueBubbles enrollment did not block outbound")

        audits = store.list_records("audit_events", 1000)
        authority_audits = [audit for audit in audits if audit["event_type"] == "authority_evaluated"]
        policy_audits = [audit for audit in audits if audit["event_type"] == "policy_evaluated"]
        containment_audits = [
            audit for audit in audits if audit["event_type"] == "bluebubbles_unauthorized_inbound_contained"
        ]
        pairing_audits = [audit for audit in audits if audit["event_type"] == "bluebubbles_pairing_requested"]
        unsupported_audits = [audit for audit in audits if audit["event_type"] == "bluebubbles_unsupported_thread_contained"]
        if not authority_audits:
            raise RuntimeError("BlueBubbles validation did not record authority audits")
        if not policy_audits:
            raise RuntimeError("BlueBubbles validation did not record policy audits")
        if not containment_audits or not pairing_audits or not unsupported_audits:
            raise RuntimeError("BlueBubbles containment audit events missing")

        output = {
            "ok": True,
            "containment": {
                "unknown_intent": unknown["intent"],
                "unknown_trusted_tables_unchanged": after_unknown == before_unknown,
                "pairing_intent": pairing["intent"],
                "pairing_state": pairing["enrollment"]["state"],
                "pairing_trusted_tables_unchanged": after_pairing == before_pairing,
                "unsupported_group_intent": group["intent"],
            },
            "inbound": {
                "direct_thread_mode": semantics["bluebubbles_thread_mode"],
                "direct_thread_behavior": semantics["bluebubbles_thread_behavior"],
                "commitment_id": trusted["commitment"]["commitment_id"],
                "suspended_inbound_contained": suspended_inbound["contained"],
            },
            "outbound": {
                "allowed_status": allowed_outbound["message"]["status"],
                "allowed_policy_decision": allowed_outbound["policy_result"]["decision"]["decision"],
                "gated_status": gated_outbound["message"]["status"],
                "gated_policy_decision": gated_outbound["policy_result"]["decision"]["decision"],
                "suspended_outbound_blocked": suspended_outbound_blocked,
                "send_request_ref": allowed_outbound["transport"]["send_request_ref"],
            },
            "audit": {
                "authority_decision_count": len(authority_audits),
                "policy_decision_count": count(store, "policy_decisions"),
                "policy_audit_count": len(policy_audits),
                "audit_event_count": len(audits),
                "event_log_rows": count(store, "event_log"),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
