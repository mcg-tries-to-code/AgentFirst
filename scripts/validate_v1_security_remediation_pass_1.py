#!/usr/bin/env python3
"""Validate AgentFirst V1 security remediation pass 1."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import (
    AgentFirstStore,
    AuthorityEngine,
    BlueBubblesApiTransport,
    BlueBubblesChannelService,
    OperatorSurface,
    TelegramBotApiTransport,
    TelegramChannelService,
)


def read_ref(ref: str) -> str:
    if not ref.startswith("file://"):
        raise ValueError(f"Unsupported ref: {ref}")
    return Path(ref.removeprefix("file://")).read_text(encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-security-pass1-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()
        primary = store.bootstrap_admin("Pass 1 Primary", "America/New_York")
        operator = OperatorSurface(store)
        authority = AuthorityEngine(store)
        telegram = TelegramChannelService(
            store,
            authority_engine=authority,
            bot_api_transport=TelegramBotApiTransport(bot_token=None, execute_live=False),
        )
        bluebubbles = BlueBubblesChannelService(
            store,
            authority_engine=authority,
            api_transport=BlueBubblesApiTransport(execute_live=False),
        )
        secondary = store.create_user(
            display_name="Pass 1 Secondary",
            authority_tier="standard",
            actor_type="user",
            actor_ref=primary["user_id"],
        )

        tg_pair = telegram.ingest_message(
            {
                "update_id": 1,
                "message": {
                    "message_id": 100,
                    "date": 1776878400,
                    "chat": {"id": 9001, "type": "private"},
                    "from": {"id": 7001, "is_bot": False, "first_name": "Unknown", "username": "unknown_tg"},
                    "text": "hello unauthorized telegram sender",
                },
            }
        )
        tg_discovery = store.get_by_id("external_channel_discoveries", tg_pair["discovery"]["discovery_id"])
        tg_preview = json.loads(read_ref(tg_pair["content_ref"]))
        if tg_discovery["first_seen_metadata_json"].get("raw_payload_retained"):
            raise RuntimeError("Telegram discovery retained raw payload by default")
        if tg_preview["raw_payload_retained"]:
            raise RuntimeError("Telegram containment artifact retained raw payload by default")

        tg_enrollment = telegram.issue_enrollment_challenge(
            telegram_user_id="7001",
            display_name="Unknown",
            username="unknown_tg",
            requested_by_type="user",
            requested_by_ref=primary["user_id"],
        )
        try:
            telegram.verify_enrollment_challenge(tg_enrollment["enrollment_id"])
        except PermissionError:
            telegram_missing_challenge_denied = True
        else:
            telegram_missing_challenge_denied = False
        if not telegram_missing_challenge_denied:
            raise RuntimeError("Telegram verification allowed missing challenge material")
        tg_enrollment = telegram.issue_enrollment_challenge(
            telegram_user_id="7001",
            display_name="Unknown",
            username="unknown_tg",
            requested_by_type="user",
            requested_by_ref=primary["user_id"],
        )
        tg_verified = telegram.verify_enrollment_challenge(
            tg_enrollment["enrollment_id"],
            challenge_secret=tg_enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=tg_enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="pass1_validation",
        )
        try:
            telegram.approve_enrollment(
                tg_verified["enrollment_id"],
                user_id=primary["user_id"],
                approver_user_id=primary["user_id"],
            )
        except PermissionError:
            telegram_unresolved_approval_denied = True
        else:
            telegram_unresolved_approval_denied = False
        if not telegram_unresolved_approval_denied:
            raise RuntimeError("Telegram enrollment approved without resolved approval record")
        try:
            operator.resolve_approval(
                tg_verified["metadata_json"]["approval_record_id"],
                actor_user_id=secondary["user_id"],
                status="approved",
                confirmation="APPROVED",
            )
        except PermissionError:
            telegram_wrong_approver_denied = True
        else:
            telegram_wrong_approver_denied = False
        if not telegram_wrong_approver_denied:
            raise RuntimeError("Telegram approval resolution allowed unauthorized approver")
        operator.resolve_approval(
            tg_verified["metadata_json"]["approval_record_id"],
            actor_user_id=primary["user_id"],
            status="approved",
            confirmation="APPROVED",
        )
        tg_promoted = telegram.approve_enrollment(
            tg_verified["enrollment_id"],
            user_id=primary["user_id"],
            approver_user_id=primary["user_id"],
        )
        tg_thread = telegram.ingest_message(
            {
                "update_id": 2,
                "bot_id": "bot",
                "bot_username": "bot",
                "message": {
                    "message_id": 101,
                    "date": 1776878500,
                    "chat": {"id": 9001, "type": "private"},
                    "from": {"id": 7001, "is_bot": False, "first_name": "Unknown", "username": "unknown_tg"},
                    "text": "/commit trusted telegram message",
                },
            }
        )
        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": "telegram:chat:9001",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
        )
        tg_gated = telegram.create_outbound_message(
            thread_id=tg_thread["thread"]["thread_id"],
            text="Private content should stay preview-only until actually sent.",
            actor_type="agent",
            actor_ref=tg_thread["agent"]["agent_id"],
            sponsoring_user_id=primary["user_id"],
            classification="private",
        )
        tg_gated_artifact = json.loads(read_ref(tg_gated["message"]["content_ref"]))
        if tg_gated["message"]["provenance_json"].get("content_retention_mode") != "preview_only":
            raise RuntimeError("Telegram gated outbound retained full content")
        if "content_preview" not in tg_gated_artifact:
            raise RuntimeError("Telegram gated outbound preview artifact missing preview")

        bb_unknown = bluebubbles.ingest_message(
            {
                "message": {
                    "guid": "IM-1",
                    "chatGuid": "iMessage;-;+15555550155",
                    "isFromMe": False,
                    "text": "hello unauthorized imessage sender",
                    "handle": {"address": "+1 (555) 555-0155", "displayName": "Unknown iMessage", "type": "phone"},
                }
            }
        )
        bb_discovery = store.get_by_id("external_channel_discoveries", bb_unknown["discovery"]["discovery_id"])
        if bb_discovery["first_seen_metadata_json"].get("raw_payload_retained"):
            raise RuntimeError("BlueBubbles discovery retained raw payload by default")

        bb_enrollment = bluebubbles.issue_enrollment_challenge(
            sender_address="+1 (555) 555-0155",
            display_name="Unknown iMessage",
            requested_by_type="user",
            requested_by_ref=primary["user_id"],
        )
        try:
            bluebubbles.verify_enrollment_challenge(bb_enrollment["enrollment_id"])
        except ValueError:
            bluebubbles_missing_challenge_denied = True
        else:
            bluebubbles_missing_challenge_denied = False
        if not bluebubbles_missing_challenge_denied:
            raise RuntimeError("BlueBubbles verification allowed missing challenge material")
        bb_enrollment = bluebubbles.issue_enrollment_challenge(
            sender_address="+1 (555) 555-0155",
            display_name="Unknown iMessage",
            requested_by_type="user",
            requested_by_ref=primary["user_id"],
        )
        bb_verified = bluebubbles.verify_enrollment_challenge(
            bb_enrollment["enrollment_id"],
            challenge_secret=bb_enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=bb_enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="pass1_validation",
        )
        denied_id = bb_verified["metadata_json"]["approval_record_id"]
        operator.resolve_approval(denied_id, actor_user_id=primary["user_id"], status="denied", confirmation="DENIED")
        try:
            bluebubbles.approve_enrollment(
                bb_verified["enrollment_id"],
                user_id=primary["user_id"],
                approver_user_id=primary["user_id"],
            )
        except PermissionError:
            bluebubbles_denied_approval_blocked = True
        else:
            bluebubbles_denied_approval_blocked = False
        if not bluebubbles_denied_approval_blocked:
            raise RuntimeError("BlueBubbles enrollment ignored denied approval")

        bb_enrollment = bluebubbles.issue_enrollment_challenge(
            sender_address="+1 (555) 555-0155",
            display_name="Unknown iMessage",
            requested_by_type="user",
            requested_by_ref=primary["user_id"],
        )
        bb_verified = bluebubbles.verify_enrollment_challenge(
            bb_enrollment["enrollment_id"],
            challenge_secret=bb_enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=bb_enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="pass1_validation",
        )
        operator.resolve_approval(
            bb_verified["metadata_json"]["approval_record_id"],
            actor_user_id=primary["user_id"],
            status="approved",
            confirmation="APPROVED",
        )
        bb_promoted = bluebubbles.approve_enrollment(
            bb_verified["enrollment_id"],
            user_id=primary["user_id"],
            approver_user_id=primary["user_id"],
        )
        bb_thread = bluebubbles.ingest_message(
            {
                "message": {
                    "guid": "IM-2",
                    "chatGuid": "iMessage;-;+15555550155",
                    "isFromMe": False,
                    "text": "/commit trusted imessage message",
                    "handle": {"address": "+1 (555) 555-0155", "displayName": "Unknown iMessage", "type": "phone"},
                    "threadClass": "direct_1to1",
                },
                "agentfirst": {"thread_class": "direct_1to1"},
            }
        )
        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": "bluebubbles:chat:iMessage;-;+15555550155",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
        )
        bb_allowed = bluebubbles.create_outbound_message(
            thread_id=bb_thread["thread"]["thread_id"],
            text="Public but unsent content should still stay preview-only in storage.",
            actor_type="agent",
            actor_ref=bb_thread["agent"]["agent_id"],
            sponsoring_user_id=primary["user_id"],
            classification="public",
        )
        bb_allowed_artifact = json.loads(read_ref(bb_allowed["message"]["content_ref"]))
        if bb_allowed["message"]["status"] != "bluebubbles_request_prepared":
            raise RuntimeError("BlueBubbles allowed outbound did not prepare request")
        if bb_allowed["message"]["provenance_json"].get("content_retention_mode") != "preview_only":
            raise RuntimeError("BlueBubbles unsent outbound retained full content")
        if bb_allowed_artifact.get("preview") is None and bb_allowed_artifact.get("content_preview") is None:
            raise RuntimeError("BlueBubbles preview artifact missing preview")

        audits = store.list_records("audit_events", 1000)
        output = {
            "ok": True,
            "telegram": {
                "missing_challenge_denied": telegram_missing_challenge_denied,
                "wrong_approver_denied": telegram_wrong_approver_denied,
                "unresolved_approval_denied": telegram_unresolved_approval_denied,
                "approved_enrollment_id": tg_promoted["enrollment"]["enrollment_id"],
                "gated_retention_mode": tg_gated["message"]["provenance_json"]["content_retention_mode"],
                "discovery_raw_retained": tg_discovery["first_seen_metadata_json"].get("raw_payload_retained", False),
            },
            "bluebubbles": {
                "missing_challenge_denied": bluebubbles_missing_challenge_denied,
                "denied_approval_blocked": bluebubbles_denied_approval_blocked,
                "approved_enrollment_id": bb_promoted["enrollment"]["enrollment_id"],
                "allowed_retention_mode": bb_allowed["message"]["provenance_json"]["content_retention_mode"],
                "discovery_raw_retained": bb_discovery["first_seen_metadata_json"].get("raw_payload_retained", False),
            },
            "audit": {
                "audit_event_count": len(audits),
                "approval_records": len(store.list_records("approval_records", 1000)),
                "policy_decisions": len(store.list_records("policy_decisions", 1000)),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
