#!/usr/bin/env python3
"""Validate V1 Chunk 3 production Telegram surface hardening."""

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
    OperatorSurface,
    TelegramBotApiTransport,
    TelegramChannelService,
)


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def enroll_telegram(
    telegram: TelegramChannelService,
    *,
    telegram_user_id: str,
    username: str,
    display_name: str,
    user_id: str,
    approver_user_id: str,
) -> dict[str, dict]:
    enrollment = telegram.issue_enrollment_challenge(
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        username=username,
        requested_by_type="user",
        requested_by_ref=approver_user_id,
    )
    verified = telegram.verify_enrollment_challenge(
        enrollment["enrollment_id"],
        challenge_secret=enrollment["challenge_material"]["challenge_secret"],
        challenge_nonce=enrollment["challenge_material"]["challenge_nonce"],
        actor_type="system",
        actor_ref="v1_chunk3_pairing_validation",
    )
    OperatorSurface(telegram.store).resolve_approval(
        verified["metadata_json"]["approval_record_id"],
        actor_user_id=approver_user_id,
        status="approved",
        confirmation="APPROVED",
    )
    return telegram.approve_enrollment(
        verified["enrollment_id"],
        user_id=user_id,
        approver_user_id=approver_user_id,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk3-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 3 Primary", "America/New_York")
        authority = AuthorityEngine(store)
        telegram = TelegramChannelService(
            store,
            authority_engine=authority,
            bot_api_transport=TelegramBotApiTransport(bot_token=None, execute_live=False),
        )

        before_pairing = {
            "users": count(store, "users"),
            "channel_identities": count(store, "channel_identities"),
            "threads": count(store, "threads"),
            "messages": count(store, "messages"),
            "commitments": count(store, "commitments"),
        }
        pairing = telegram.ingest_message(
            {
                "update_id": 13001,
                "message": {
                    "message_id": 501,
                    "date": 1776878400,
                    "chat": {"id": 313001, "type": "private"},
                    "from": {"id": 880001, "is_bot": False, "first_name": "Pairing", "username": "pairing_user"},
                    "text": "/pair",
                },
            }
        )
        after_pairing = {
            "users": count(store, "users"),
            "channel_identities": count(store, "channel_identities"),
            "threads": count(store, "threads"),
            "messages": count(store, "messages"),
            "commitments": count(store, "commitments"),
        }
        if pairing["intent"] != "pairing_requested" or pairing["enrollment"]["state"] != "pairing_requested":
            raise RuntimeError("Pairing request did not enter pairing_requested containment state")
        for table, before in before_pairing.items():
            if after_pairing[table] != before:
                raise RuntimeError(f"Pairing request changed trusted table before enrollment: {table}")

        enrolled = enroll_telegram(
            telegram,
            telegram_user_id="880001",
            username="pairing_user",
            display_name="Pairing User",
            user_id=primary["user_id"],
            approver_user_id=primary["user_id"],
        )
        private_inbound = telegram.ingest_message(
            {
                "update_id": 13002,
                "bot_id": "v1-chunk3-bot",
                "bot_username": "agentfirst_v1_chunk3_bot",
                "message": {
                    "message_id": 502,
                    "date": 1776878460,
                    "chat": {"id": 313001, "type": "private"},
                    "from": {"id": 880001, "is_bot": False, "first_name": "Pairing", "username": "pairing_user"},
                    "text": "/commit Capture this enrolled private Telegram request.",
                },
            }
        )
        private_thread = private_inbound["thread"]
        private_semantics = private_thread["participants_json"][-1]
        if private_inbound["intent"] != "create_commitment":
            raise RuntimeError("Enrolled private Telegram inbound did not route to trusted work")
        if private_semantics["telegram_thread_mode"] != "private":
            raise RuntimeError("Private Telegram thread semantics were not stamped")

        household = store.insert(
            "shared_contexts",
            {
                "name": "V1 Chunk 3 Household",
                "context_type": "household",
                "visibility_model": "shared-members",
                "status": "active",
            },
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        authority.add_shared_context_member(
            shared_context_id=household["shared_context_id"],
            member_user_id=primary["user_id"],
            role="administrator",
            actor_user_id=primary["user_id"],
        )
        shared_inbound = telegram.ingest_message(
            {
                "update_id": 13003,
                "bot_id": "v1-chunk3-bot",
                "bot_username": "agentfirst_v1_chunk3_bot",
                "message": {
                    "message_id": 503,
                    "date": 1776878520,
                    "chat": {"id": -913001, "type": "supergroup"},
                    "from": {"id": 880001, "is_bot": False, "first_name": "Pairing", "username": "pairing_user"},
                    "text": "/commit Capture this shared household request.",
                },
                "agentfirst": {
                    "telegram_thread_mode": "shared",
                    "shared_context_id": household["shared_context_id"],
                },
            }
        )
        shared_thread = shared_inbound["thread"]
        shared_semantics = shared_thread["participants_json"][-1]
        if shared_thread["ownership_context_type"] != "shared_context":
            raise RuntimeError("Shared Telegram thread was not owned by the shared context")
        if shared_semantics["telegram_thread_mode"] != "shared" or shared_thread["visibility_model"] != "shared-members":
            raise RuntimeError("Shared Telegram thread semantics were not explicit")

        monitored_inbound = telegram.ingest_message(
            {
                "update_id": 13004,
                "bot_id": "v1-chunk3-bot",
                "bot_username": "agentfirst_v1_chunk3_bot",
                "message": {
                    "message_id": 504,
                    "date": 1776878580,
                    "chat": {"id": -913002, "type": "group"},
                    "from": {"id": 880001, "is_bot": False, "first_name": "Pairing", "username": "pairing_user"},
                    "text": "/commit This monitored group message must not create work.",
                },
                "agentfirst": {"telegram_thread_mode": "monitored"},
            }
        )
        monitored_thread = monitored_inbound["thread"]
        monitored_semantics = monitored_thread["participants_json"][-1]
        if monitored_inbound["intent"] != "monitored_message_stored" or monitored_inbound["commitment"] is not None:
            raise RuntimeError("Monitored Telegram thread created trusted work")
        if monitored_semantics["telegram_thread_mode"] != "monitored":
            raise RuntimeError("Monitored Telegram thread semantics were not explicit")

        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": "telegram:chat:313001",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
        )
        allowed_outbound = telegram.create_outbound_message(
            thread_id=private_thread["thread_id"],
            text="Public status captured for the enrolled private Telegram thread.",
            actor_type="agent",
            actor_ref=private_inbound["agent"]["agent_id"],
            sponsoring_user_id=primary["user_id"],
            classification="public",
            provenance={"source": "v1-chunk3-validation-allowed"},
        )
        gated_outbound = telegram.create_outbound_message(
            thread_id=private_thread["thread_id"],
            text="Private details require policy approval before Telegram delivery.",
            actor_type="agent",
            actor_ref=private_inbound["agent"]["agent_id"],
            sponsoring_user_id=primary["user_id"],
            classification="private",
            provenance={"source": "v1-chunk3-validation-gated"},
        )
        if allowed_outbound["message"]["status"] != "telegram_request_prepared":
            raise RuntimeError("Allowed Telegram outbound did not prepare a Bot API request")
        if not allowed_outbound["message"]["provenance_json"].get("authority_policy_decision_id"):
            raise RuntimeError("Allowed Telegram outbound lacks authority decision linkage")
        if not allowed_outbound["message"]["provenance_json"].get("recipient_enrollment_refs"):
            raise RuntimeError("Allowed Telegram outbound lacks enrolled-recipient linkage")
        if gated_outbound["policy_result"]["decision"]["decision"] not in {
            "require_owner_approval",
            "require_primary_user_approval",
        }:
            raise RuntimeError("Private Telegram outbound was not policy-gated")

        try:
            telegram.create_outbound_message(
                thread_id=monitored_thread["thread_id"],
                text="This monitored thread must not allow outbound send.",
                actor_type="agent",
                actor_ref=monitored_inbound["agent"]["agent_id"],
                sponsoring_user_id=primary["user_id"],
                classification="public",
            )
        except PermissionError:
            monitored_outbound_blocked = True
        else:
            monitored_outbound_blocked = False
        if not monitored_outbound_blocked:
            raise RuntimeError("Monitored Telegram outbound was not blocked")

        suspended = telegram.suspend_enrollment(
            enrolled["enrollment"]["enrollment_id"],
            actor_ref=primary["user_id"],
            reason="v1 chunk3 validation suspension",
        )
        suspended_inbound = telegram.ingest_message(
            {
                "update_id": 13005,
                "message": {
                    "message_id": 505,
                    "date": 1776878640,
                    "chat": {"id": 313001, "type": "private"},
                    "from": {"id": 880001, "is_bot": False, "first_name": "Pairing", "username": "pairing_user"},
                    "text": "/commit Suspended enrollment must not route.",
                },
            }
        )
        try:
            telegram.create_outbound_message(
                thread_id=private_thread["thread_id"],
                text="This suspended binding must not receive outbound Telegram traffic.",
                actor_type="agent",
                actor_ref=private_inbound["agent"]["agent_id"],
                sponsoring_user_id=primary["user_id"],
                classification="public",
            )
        except PermissionError:
            suspended_outbound_blocked = True
        else:
            suspended_outbound_blocked = False
        if suspended["state"] != "suspended" or suspended_inbound["intent"] != "enrollment_required":
            raise RuntimeError("Suspended Telegram enrollment did not block trusted inbound")
        if not suspended_outbound_blocked:
            raise RuntimeError("Suspended Telegram enrollment did not block outbound")

        audits = store.list_records("audit_events", 1000)
        authority_audits = [audit for audit in audits if audit["event_type"] == "authority_evaluated"]
        policy_audits = [audit for audit in audits if audit["event_type"] == "policy_evaluated"]
        pairing_audits = [audit for audit in audits if audit["event_type"] == "telegram_pairing_requested"]
        if not authority_audits:
            raise RuntimeError("Telegram hardening did not record authority audits")
        if not policy_audits:
            raise RuntimeError("Telegram hardening did not record policy audits")
        if not pairing_audits:
            raise RuntimeError("Pairing request audit event missing")

        output = {
            "ok": True,
            "pairing": {
                "intent": pairing["intent"],
                "enrollment_state": pairing["enrollment"]["state"],
                "trusted_tables_unchanged": after_pairing == before_pairing,
                "audit_event_id": pairing_audits[0]["audit_event_id"],
            },
            "inbound": {
                "private_thread_mode": private_semantics["telegram_thread_mode"],
                "private_commitment_id": private_inbound["commitment"]["commitment_id"],
                "shared_thread_mode": shared_semantics["telegram_thread_mode"],
                "shared_context_id": shared_thread["ownership_context_ref"],
                "monitored_thread_mode": monitored_semantics["telegram_thread_mode"],
                "monitored_intent": monitored_inbound["intent"],
                "suspended_inbound_contained": suspended_inbound["contained"],
            },
            "outbound": {
                "allowed_status": allowed_outbound["message"]["status"],
                "allowed_policy_decision": allowed_outbound["policy_result"]["decision"]["decision"],
                "gated_status": gated_outbound["message"]["status"],
                "gated_policy_decision": gated_outbound["policy_result"]["decision"]["decision"],
                "monitored_outbound_blocked": monitored_outbound_blocked,
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
