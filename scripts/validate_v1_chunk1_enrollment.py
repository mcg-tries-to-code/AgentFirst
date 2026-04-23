#!/usr/bin/env python3
"""Validate V1 Chunk 1 enrollment and channel-binding containment."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import AgentFirstStore, OperatorSurface, TelegramChannelService


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk1-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        admin = store.bootstrap_admin("V1 Chunk 1 Owner", "America/New_York")
        telegram = TelegramChannelService(store)

        before = {
            "users": count(store, "users"),
            "channel_identities": count(store, "channel_identities"),
            "threads": count(store, "threads"),
            "messages": count(store, "messages"),
            "commitments": count(store, "commitments"),
        }

        unknown = telegram.ingest_message(
            {
                "update_id": 11001,
                "bot_id": "v1-bot",
                "bot_username": "agentfirst_v1_bot",
                "message": {
                    "message_id": 301,
                    "date": 1776792000,
                    "chat": {"id": 111001, "type": "private"},
                    "from": {
                        "id": 700700,
                        "is_bot": False,
                        "first_name": "Unknown",
                        "last_name": "Contact",
                        "username": "unknown_contact",
                    },
                    "text": "/commit This must not become trusted work.",
                },
                "agentfirst": {"classification": "private"},
            }
        )

        after_unknown = {
            "users": count(store, "users"),
            "channel_identities": count(store, "channel_identities"),
            "threads": count(store, "threads"),
            "messages": count(store, "messages"),
            "commitments": count(store, "commitments"),
            "discoveries": count(store, "external_channel_discoveries"),
            "enrollments": count(store, "channel_enrollments"),
        }
        if unknown["intent"] != "enrollment_required" or not unknown["contained"]:
            raise RuntimeError("Unknown Telegram contact was not contained")
        for table in ["users", "channel_identities", "threads", "messages", "commitments"]:
            if after_unknown[table] != before[table]:
                raise RuntimeError(f"Unauthorized first contact changed trusted table: {table}")
        if after_unknown["discoveries"] != 1 or after_unknown["enrollments"] != 1:
            raise RuntimeError("Unauthorized first contact did not create bounded discovery/enrollment records")

        enrollment = telegram.issue_enrollment_challenge(
            telegram_user_id="700700",
            display_name="Known Owner Contact",
            username="known_owner_contact",
            requested_by_type="user",
            requested_by_ref=admin["user_id"],
        )
        verified = telegram.verify_enrollment_challenge(
            enrollment["enrollment_id"],
            challenge_secret=enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="validation_pairing_code",
        )
        OperatorSurface(store).resolve_approval(
            verified["metadata_json"]["approval_record_id"],
            actor_user_id=admin["user_id"],
            status="approved",
            confirmation="APPROVED",
        )
        approved = telegram.approve_enrollment(
            verified["enrollment_id"],
            user_id=admin["user_id"],
            approver_user_id=admin["user_id"],
        )

        trusted = telegram.ingest_message(
            {
                "update_id": 11002,
                "bot_id": "v1-bot",
                "bot_username": "agentfirst_v1_bot",
                "message": {
                    "message_id": 302,
                    "date": 1776792060,
                    "chat": {"id": 111001, "type": "private"},
                    "from": {
                        "id": 700700,
                        "is_bot": False,
                        "first_name": "Known",
                        "last_name": "Owner Contact",
                        "username": "known_owner_contact",
                    },
                    "text": "/commit This enrolled contact may create trusted work.",
                },
            }
        )
        if trusted["intent"] != "create_commitment":
            raise RuntimeError("Enrolled Telegram contact did not reach trusted commitment flow")
        if trusted["channel_identity"]["enrollment_state"] != "enrolled":
            raise RuntimeError("Trusted flow did not use enrolled channel identity")
        if trusted["thread"]["status"] != "active":
            raise RuntimeError("Trusted thread was not activated after enrollment")

        suspended = telegram.suspend_enrollment(
            approved["enrollment"]["enrollment_id"],
            actor_ref=admin["user_id"],
            reason="validation suspension before recovery",
        )
        suspended_try = telegram.ingest_message(
            {
                "update_id": 11003,
                "bot_id": "v1-bot",
                "bot_username": "agentfirst_v1_bot",
                "message": {
                    "message_id": 303,
                    "date": 1776792120,
                    "chat": {"id": 111001, "type": "private"},
                    "from": {
                        "id": 700700,
                        "is_bot": False,
                        "first_name": "Known",
                        "last_name": "Owner Contact",
                        "username": "known_owner_contact",
                    },
                    "text": "/commit Suspended contact must not activate work.",
                },
            }
        )
        if suspended["state"] != "suspended":
            raise RuntimeError("Suspension state was not recorded")
        if suspended_try["intent"] != "enrollment_required" or not suspended_try["contained"]:
            raise RuntimeError("Suspended binding was allowed into trusted flow")

        audits = store.list_records("audit_events", 1000)
        contained_audits = [
            audit for audit in audits if audit["event_type"] == "telegram_unauthorized_inbound_contained"
        ]
        owner_approval_audits = [
            audit for audit in audits if audit["event_type"] == "telegram_enrollment_owner_approved"
        ]
        if not contained_audits:
            raise RuntimeError("Unauthorized inbound containment audit event missing")
        if not owner_approval_audits:
            raise RuntimeError("Owner approval audit event missing")

        output = {
            "ok": True,
            "unauthorized_first_contact": {
                "contained": unknown["contained"],
                "canonical_user_created": after_unknown["users"] != before["users"],
                "trusted_channel_identity_created": after_unknown["channel_identities"] != before["channel_identities"],
                "trusted_thread_created": after_unknown["threads"] != before["threads"],
                "trusted_message_created": after_unknown["messages"] != before["messages"],
                "commitment_created": after_unknown["commitments"] != before["commitments"],
                "discovery_id": unknown["discovery"]["discovery_id"],
                "enrollment_state": unknown["enrollment"]["state"],
            },
            "enrollment_flow": {
                "challenge_state": enrollment["state"],
                "verified_state": verified["state"],
                "approved_state": approved["enrollment"]["state"],
                "channel_identity_id": approved["channel_identity"]["channel_identity_id"],
                "binding_generation": approved["channel_identity"]["binding_generation"],
            },
            "trusted_activation": {
                "thread_id": trusted["thread"]["thread_id"],
                "message_id": trusted["message"]["message_event_id"],
                "commitment_id": trusted["commitment"]["commitment_id"],
            },
            "suspension": {
                "state": suspended["state"],
                "post_suspension_inbound_contained": suspended_try["contained"],
            },
            "audit": {
                "contained_event_id": contained_audits[0]["audit_event_id"],
                "owner_approval_event_id": owner_approval_audits[0]["audit_event_id"],
                "audit_event_count": len(audits),
            },
            "event_log_rows": count(store, "event_log"),
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
