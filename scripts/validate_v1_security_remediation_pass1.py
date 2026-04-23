#!/usr/bin/env python3
"""Validate the bounded V1 security remediation pass 1 controls."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import (
    AgentFirstStore,
    BlueBubblesChannelService,
    OperatorSurface,
    TelegramChannelService,
)


def read_artifact(root: Path, ref: str | None) -> str | None:
    if not ref:
        return None
    if ref.startswith("file://"):
        path = Path(ref.removeprefix("file://"))
    else:
        path = root / ref
    return path.read_text() if path.exists() else None


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-security-pass1-") as tmp:
        root = Path(tmp)
        artifact_root = root / "artifacts"
        store = AgentFirstStore(root / "agentfirst.sqlite3", artifact_root)
        store.initialize()
        admin = store.bootstrap_admin("Security Pass 1 Owner", "America/New_York")
        telegram = TelegramChannelService(store)
        bluebubbles = BlueBubblesChannelService(store)
        operator = OperatorSurface(store)

        unauthorized = telegram.ingest_message(
            {
                "update_id": 44001,
                "bot_id": "security-bot",
                "bot_username": "agentfirst_security_bot",
                "message": {
                    "message_id": 701,
                    "date": 1776792000,
                    "chat": {"id": 910001, "type": "private"},
                    "from": {
                        "id": 700700,
                        "is_bot": False,
                        "first_name": "Unknown",
                        "username": "unknown_contact",
                    },
                    "text": "hello from an unknown contact",
                },
                "agentfirst": {"classification": "private"},
            }
        )
        discovery = unauthorized["discovery"]
        contained_audit = unauthorized["audit_event"]
        if discovery["last_seen_metadata_json"].get("raw_update") is not None:
            raise RuntimeError("Raw Telegram update was retained in discovery metadata by default")
        if discovery["last_seen_metadata_json"].get("raw_payload_retained") is not False:
            raise RuntimeError("Telegram discovery did not record default minimized retention")
        contained_ref = contained_audit["metadata_json"].get("content_ref")
        if not contained_ref:
            raise RuntimeError("Unauthorized Telegram content should retain a minimized preview artifact")
        contained_body = read_artifact(root, contained_ref)
        if contained_body and "hello from an unknown contact" in contained_body and '"content_preview"' not in contained_body:
            raise RuntimeError("Unauthorized Telegram content retained full-body plaintext instead of preview-only payload")

        enrollment = telegram.issue_enrollment_challenge(
            telegram_user_id="700700",
            display_name="Known Owner Contact",
            username="known_owner_contact",
            requested_by_type="user",
            requested_by_ref=admin["user_id"],
        )
        try:
            telegram.verify_enrollment_challenge(
                enrollment["enrollment_id"],
                challenge_secret="wrong-secret",
                challenge_nonce=enrollment["challenge_material"]["challenge_nonce"],
                actor_type="system",
                actor_ref="security_validation_wrong_secret",
            )
            raise RuntimeError("Challenge verification unexpectedly succeeded with wrong secret")
        except PermissionError:
            pass
        failed_attempt = store.get_by_id("channel_enrollments", enrollment["enrollment_id"])
        if failed_attempt["metadata_json"].get("challenge_attempt_count") != 1:
            raise RuntimeError("Failed Telegram challenge attempt was not counted")

        verified = telegram.verify_enrollment_challenge(
            enrollment["enrollment_id"],
            challenge_secret=enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="security_validation_pairing_code",
        )
        approval_record_id = verified["metadata_json"].get("approval_record_id")
        if not approval_record_id:
            raise RuntimeError("Telegram verification did not create a canonical approval record")
        try:
            telegram.approve_enrollment(
                verified["enrollment_id"],
                user_id=admin["user_id"],
                approver_user_id=admin["user_id"],
            )
            raise RuntimeError("Enrollment approval unexpectedly bypassed approval record resolution")
        except PermissionError:
            pass
        operator.resolve_approval(
            approval_record_id,
            actor_user_id=admin["user_id"],
            status="approved",
            confirmation="APPROVED",
        )
        approved = telegram.approve_enrollment(
            verified["enrollment_id"],
            user_id=admin["user_id"],
            approver_user_id=admin["user_id"],
        )

        denied_enrollment = bluebubbles.issue_enrollment_challenge(
            sender_address="+15555550101",
            display_name="Denied iMessage",
            requested_by_type="user",
            requested_by_ref=admin["user_id"],
        )
        denied_verified = bluebubbles.verify_enrollment_challenge(
            denied_enrollment["enrollment_id"],
            challenge_secret=denied_enrollment["challenge_material"]["challenge_secret"],
            challenge_nonce=denied_enrollment["challenge_material"]["challenge_nonce"],
            actor_type="system",
            actor_ref="security_validation_pairing_code",
        )
        operator.resolve_approval(
            denied_verified["metadata_json"]["approval_record_id"],
            actor_user_id=admin["user_id"],
            status="denied",
            confirmation="DENIED",
        )
        try:
            bluebubbles.approve_enrollment(
                denied_verified["enrollment_id"],
                user_id=admin["user_id"],
                approver_user_id=admin["user_id"],
            )
            raise RuntimeError("Denied approval unexpectedly allowed BlueBubbles enrollment promotion")
        except PermissionError:
            pass
        denied_state = store.get_by_id("channel_enrollments", denied_verified["enrollment_id"])
        if denied_state["state"] != "denied":
            raise RuntimeError("Denied BlueBubbles enrollment was not transitioned to denied")

        trusted = telegram.ingest_message(
            {
                "update_id": 44002,
                "bot_id": "security-bot",
                "bot_username": "agentfirst_security_bot",
                "message": {
                    "message_id": 702,
                    "date": 1776792060,
                    "chat": {"id": 910001, "type": "private"},
                    "from": {
                        "id": 700700,
                        "is_bot": False,
                        "first_name": "Known",
                        "username": "known_owner_contact",
                    },
                    "text": "/commit create a trusted thread",
                },
            }
        )
        outbound = telegram.create_outbound_message(
            thread_id=trusted["thread"]["thread_id"],
            text="Sensitive outbound draft that should not be durably retained in full while approval is pending.",
            actor_type="agent",
            actor_ref=trusted["agent"]["agent_id"],
            sponsoring_user_id=admin["user_id"],
            classification="private",
        )
        outbound_message = outbound["message"]
        if outbound_message["status"] != "awaiting_policy_approval":
            raise RuntimeError("Expected Telegram outbound message to require policy approval")
        if outbound_message["provenance_json"].get("content_retention_mode") != "preview_only":
            raise RuntimeError("Unsent outbound Telegram content was not downgraded to preview retention")
        retained_body = read_artifact(artifact_root, outbound_message["content_ref"])
        if retained_body is None or "Sensitive outbound draft" not in retained_body:
            preview_payload = json.loads(retained_body or "{}")
            if preview_payload.get("preview") != "Sensitive outbound draft that should not be durably retained in full while approval is pending."[:120]:
                raise RuntimeError("Outbound preview artifact did not contain the expected minimized preview")
        if retained_body and retained_body.strip().startswith("Sensitive outbound draft"):
            raise RuntimeError("Unsent outbound Telegram content retained full plaintext")

        result = {
            "ok": True,
            "telegram": {
                "unauthorized_contained": unauthorized["contained"],
                "discovery_raw_payload_retained": discovery["last_seen_metadata_json"].get("raw_payload_retained"),
                "wrong_secret_rejected": True,
                "approval_record_id": approval_record_id,
                "approved_enrollment_state": approved["enrollment"]["state"],
                "approved_via_approval_record_id": approved["enrollment"]["metadata_json"].get(
                    "approved_via_approval_record_id"
                ),
            },
            "bluebubbles": {
                "denied_enrollment_state": denied_state["state"],
                "denied_approval_record_id": denied_verified["metadata_json"].get("approval_record_id"),
            },
            "outbound_retention": {
                "status": outbound_message["status"],
                "retention_mode": outbound_message["provenance_json"].get("content_retention_mode"),
                "content_ref": outbound_message["content_ref"],
            },
            "approval_records": len(store.list_records("approval_records", 100)),
            "audit_events": len(store.list_records("audit_events", 200)),
        }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
