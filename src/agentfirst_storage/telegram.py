"""Telegram-first channel adapter for AgentFirst v0 Stage 4/5."""

from __future__ import annotations

import json
import hashlib
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .secret_broker import SecretBroker

from .authority import AuthorityEngine, AuthorityRequest
from .policy import GovernedAction, PolicyEngine
from .store import AgentFirstStore, new_id
from .task_engine import TERMINAL_STATES, TaskEngine


@dataclass(frozen=True)
class TelegramInboundMessage:
    """Normalized Telegram-shaped inbound message."""

    chat_id: str
    chat_type: str
    message_id: str
    sender_id: str
    sender_display_name: str
    text: str
    date: int | None = None
    username: str | None = None
    bot_id: str | None = None
    bot_username: str | None = None
    reply_to_message_id: str | None = None
    raw_update: dict[str, Any] | None = None


@dataclass(frozen=True)
class TelegramBotApiTransport:
    """Narrow Telegram Bot API boundary for preparing or executing sendMessage."""

    bot_token: str | None = None
    bot_token_secret_id: str | None = None
    secret_broker: SecretBroker | None = None
    secret_actor_type: str = "system"
    secret_actor_ref: str = "telegram_bot_api_transport"
    execute_live: bool = False
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: float = 10.0

    def prepare_send_message(self, *, chat_id: str, text: str) -> dict[str, Any]:
        token_marker = "<bot-token-present>" if self._token_available() else "<bot-token-missing>"
        return {
            "method": "POST",
            "url_template": f"{self.api_base_url}/bot{token_marker}/sendMessage",
            "telegram_method": "sendMessage",
            "json_body": {"chat_id": chat_id, "text": text},
            "headers": {"Content-Type": "application/json"},
            "token_present": self._token_available(),
            "bot_token_secret_id": self.bot_token_secret_id,
            "execute_live": self.execute_live,
        }

    def send_message(self, *, chat_id: str, text: str) -> dict[str, Any]:
        request = self.prepare_send_message(chat_id=chat_id, text=text)
        if not self.execute_live:
            return {
                "status": "prepared_not_sent",
                "request": request,
                "response": None,
                "live_transport": False,
                "reason": "execute_live is false",
            }
        bot_token = self._resolve_bot_token()
        if not bot_token:
            return {
                "status": "not_sent_missing_token",
                "request": request,
                "response": None,
                "live_transport": False,
                "reason": "brokered bot token is required for live Telegram transport",
            }

        url = f"{self.api_base_url}/bot{bot_token}/sendMessage"
        body = json.dumps(request["json_body"]).encode("utf-8")
        http_request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                parsed = json.loads(payload) if payload else {}
                return {
                    "status": "sent",
                    "request": request,
                    "response": parsed,
                    "live_transport": True,
                    "http_status": response.status,
                }
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            return {
                "status": "send_failed",
                "request": request,
                "response": {"body": payload},
                "live_transport": True,
                "http_status": exc.code,
                "reason": str(exc),
            }
        except urllib.error.URLError as exc:
            return {
                "status": "send_failed",
                "request": request,
                "response": None,
                "live_transport": True,
                "reason": str(exc.reason),
            }

    def _token_available(self) -> bool:
        return bool(self.bot_token or (self.secret_broker and self.bot_token_secret_id))

    def _resolve_bot_token(self) -> str | None:
        if self.bot_token is not None:
            return self.bot_token
        if self.secret_broker and self.bot_token_secret_id:
            return self.secret_broker.resolve_secret_text(
                self.bot_token_secret_id,
                actor_type=self.secret_actor_type,
                actor_ref=self.secret_actor_ref,
                purpose="telegram_send_message",
                integration_type="telegram",
            )
        return None


class TelegramChannelService:
    """Narrow Telegram adapter that maps channel events into canonical objects."""

    def __init__(
        self,
        store: AgentFirstStore,
        *,
        policy_engine: PolicyEngine | None = None,
        task_engine: TaskEngine | None = None,
        authority_engine: AuthorityEngine | None = None,
        bot_api_transport: TelegramBotApiTransport | None = None,
    ):
        self.store = store
        self.policy_engine = policy_engine or PolicyEngine(store)
        self.task_engine = task_engine or TaskEngine(store)
        self.authority_engine = authority_engine or AuthorityEngine(store)
        self.bot_api_transport = bot_api_transport

    def ingest_message(self, update: dict[str, Any]) -> dict[str, Any]:
        """Persist an inbound Telegram-shaped message and apply explicit task intent."""
        inbound = self.normalize_update(update)
        self.store.initialize()

        sender_identity = self._resolve_enrolled_sender_identity(inbound)
        if sender_identity is None:
            return self._contain_unauthorized_inbound(inbound, update)

        user_id = sender_identity["user_id"]
        self._assert_trusted_inbound_authority(user_id, sender_identity)
        agent = self._resolve_or_create_user_agent(user_id)
        bot_identity = self._resolve_or_create_agent_identity(agent["agent_id"], inbound)
        thread = self._resolve_or_create_thread(inbound, sender_identity, bot_identity, agent, update)
        thread_semantics = self._thread_semantics(thread)

        content_ref = self.store.write_artifact(
            f"messages/telegram/inbound-{inbound.chat_id}-{inbound.message_id}.txt",
            inbound.text,
        )
        message = self.store.insert(
            "messages",
            {
                "thread_id": thread["thread_id"],
                "direction": "inbound",
                "sender_identity_json": {
                    "channel_identity_id": sender_identity["channel_identity_id"],
                    "user_id": user_id,
                    "channel_type": "telegram",
                    "address": sender_identity["address"],
                },
                "recipient_identities_json": [
                    {
                        "channel_identity_id": bot_identity["channel_identity_id"],
                        "agent_id": agent["agent_id"],
                        "channel_type": "telegram",
                        "address": bot_identity["address"],
                    }
                ],
                "content_ref": content_ref,
                "classification": self._classification_from_update(update),
                "provenance_json": {
                    "channel_type": "telegram",
                    "telegram_chat_id": inbound.chat_id,
                    "telegram_chat_type": inbound.chat_type,
                    "telegram_thread_mode": thread_semantics["mode"],
                    "telegram_thread_behavior": thread_semantics["behavior"],
                    "telegram_message_id": inbound.message_id,
                    "telegram_date": inbound.date,
                    "raw_update": inbound.raw_update or update,
                },
                "status": "received",
            },
            actor_type="user",
            actor_ref=user_id,
        )

        result: dict[str, Any] = {
            "channel_identity": sender_identity,
            "agent_channel_identity": bot_identity,
            "thread": thread,
            "message": message,
            "agent": agent,
            "commitment": None,
            "progress_update": None,
            "intent": "stored_message",
        }
        if thread_semantics["behavior"] == "monitor_only":
            result["intent"] = "monitored_message_stored"
            return result
        task_result = self._apply_message_to_commitment(inbound, message, thread, agent, user_id)
        result.update(task_result)
        return result

    def issue_enrollment_challenge(
        self,
        *,
        telegram_user_id: str,
        display_name: str,
        username: str | None = None,
        requested_by_type: str = "system",
        requested_by_ref: str = "telegram_channel_service",
    ) -> dict[str, Any]:
        """Create or advance a Telegram enrollment to challenge-issued state."""
        self.store.initialize()
        address = f"telegram:user:{telegram_user_id}"
        challenge_secret = secrets.token_urlsafe(12)
        challenge_nonce = new_id("nonce")
        issued_at = self._now_iso()
        expires_at = self._expires_at(minutes=15)
        discovery = self._resolve_or_create_discovery(
            address=address,
            display_name=display_name,
            metadata={
                "telegram_user_id": str(telegram_user_id),
                "telegram_username": username,
                "display_name": display_name,
                "source": "explicit_pairing_request",
            },
            raw_update=None,
        )
        enrollment = self._active_enrollment_by_address(address)
        challenge_ref = self.store.write_artifact(
            f"enrollment/telegram/challenge-{new_id('challenge')}.txt",
            json.dumps(
                {
                    "channel_type": "telegram",
                    "address": address,
                    "challenge_nonce": challenge_nonce,
                    "issued_at": issued_at,
                    "expires_at": expires_at,
                    "verification_requirement": "submit matching challenge_secret and challenge_nonce before expiry",
                },
                indent=2,
                sort_keys=True,
            ),
        )
        values = {
            "channel_type": "telegram",
            "address": address,
            "discovery_id": discovery["discovery_id"],
            "state": "challenge_issued",
            "challenge_ref": challenge_ref,
            "challenge_status": "issued",
            "owner_approval_status": "not_requested",
            "metadata_json": {
                "telegram_user_id": str(telegram_user_id),
                "telegram_username": username,
                "display_name": display_name,
                "challenge_nonce": challenge_nonce,
                "challenge_secret_hash": self._challenge_secret_hash(
                    enrollment_id=(enrollment or {}).get("enrollment_id") or "pending_enrollment",
                    address=address,
                    nonce=challenge_nonce,
                    secret=challenge_secret,
                ),
                "challenge_issued_at": issued_at,
                "challenge_expires_at": expires_at,
                "challenge_max_attempts": 5,
                "challenge_attempt_count": 0,
                "required_steps": ["challenge_verification", "owner_approval"],
                "recovery_policy": "owner_approval_required",
                "rebinding_policy": "suspend_old_binding_then_owner_approve_new_binding",
            },
        }
        if enrollment is None:
            enrollment = self.store.insert(
                "channel_enrollments",
                values,
                actor_type=requested_by_type,
                actor_ref=requested_by_ref,
            )
        elif enrollment["state"] not in {"enrolled", "revoked"}:
            enrollment = self.store.update(
                "channel_enrollments",
                enrollment["enrollment_id"],
                {
                    **values,
                    "status": "active",
                },
                actor_type=requested_by_type,
                actor_ref=requested_by_ref,
                event_type="channel_enrollment_challenge_issued",
            )
        else:
            raise ValueError(f"Cannot issue challenge for enrollment in state {enrollment['state']}")
        enrollment = self._refresh_enrollment_challenge_hash(enrollment, challenge_secret, challenge_nonce)
        self._link_discovery_enrollment(discovery, enrollment, status="pairing_requested")
        self._audit_enrollment(
            "telegram_enrollment_challenge_issued",
            enrollment,
            requested_by_type,
            requested_by_ref,
            "challenge_issued",
        )
        return {
            **enrollment,
            "challenge_material": {
                "challenge_secret": challenge_secret,
                "challenge_nonce": challenge_nonce,
                "expires_at": expires_at,
            },
        }

    def verify_enrollment_challenge(
        self,
        enrollment_id: str,
        *,
        challenge_secret: str | None = None,
        challenge_nonce: str | None = None,
        actor_type: str = "system",
        actor_ref: str = "telegram_channel_service",
    ) -> dict[str, Any]:
        """Verify bounded challenge-response material and move to owner-approval gate."""
        enrollment = self._get_enrollment(enrollment_id)
        if enrollment["state"] != "challenge_issued" or enrollment["challenge_status"] != "issued":
            raise ValueError("Enrollment challenge is not in an issuable state")
        metadata = dict(enrollment.get("metadata_json", {}))
        self._assert_valid_challenge_material(
            enrollment,
            metadata,
            challenge_secret=challenge_secret,
            challenge_nonce=challenge_nonce,
        )
        approval = self._create_enrollment_approval_request(
            enrollment,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        now = self._now_iso()
        updated = self.store.update(
            "channel_enrollments",
            enrollment_id,
            {
                "state": "awaiting_owner_approval",
                "challenge_status": "verified",
                "owner_approval_status": "requested",
                "metadata_json": {
                    **metadata,
                    "challenge_attempt_count": int(metadata.get("challenge_attempt_count", 0)) + 1,
                    "challenge_verified_at": now,
                    "approval_record_id": approval["approval_record_id"],
                    "approval_requested_at": now,
                    "requested_approver_user_id": approval.get("approver_user_id"),
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="channel_enrollment_challenge_verified",
        )
        self._audit_enrollment(
            "telegram_enrollment_challenge_verified",
            updated,
            actor_type,
            actor_ref,
            "awaiting_owner_approval",
            {"approval_record_id": approval["approval_record_id"]},
        )
        return updated

    def approve_enrollment(
        self,
        enrollment_id: str,
        *,
        user_id: str,
        approver_user_id: str,
        actor_type: str = "user",
        actor_ref: str | None = None,
    ) -> dict[str, Any]:
        """Finalize a verified-and-approved enrollment into a trusted channel identity."""
        enrollment = self._get_enrollment(enrollment_id)
        if enrollment["state"] != "awaiting_owner_approval":
            raise ValueError("Enrollment must be awaiting owner approval")
        if enrollment["challenge_status"] != "verified":
            raise ValueError("Enrollment challenge must be verified before approval")

        actor_ref = actor_ref or approver_user_id
        approval_record = self._require_resolved_enrollment_approval(
            enrollment,
            approver_user_id=approver_user_id,
        )
        address = enrollment["address"]
        existing = self._channel_identity_by_address(address, enrolled_only=False)
        if existing and existing.get("enrollment_state") == "enrolled" and existing["status"] == "active":
            raise ValueError(f"Telegram address is already enrolled: {address}")

        metadata = dict(enrollment.get("metadata_json", {}))
        identity = self.store.insert(
            "channel_identities",
            {
                "user_id": user_id,
                "channel_type": "telegram",
                "address": address,
                "enrollment_id": enrollment_id,
                "enrollment_state": "enrolled",
                "binding_generation": enrollment.get("binding_generation", 1),
                "metadata_json": {
                    **metadata,
                    "approved_by_user_id": approver_user_id,
                    "approved_via_approval_record_id": approval_record["approval_record_id"],
                    "binding_state": "enrolled",
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        updated = self.store.update(
            "channel_enrollments",
            enrollment_id,
            {
                "user_id": user_id,
                "channel_identity_id": identity["channel_identity_id"],
                "state": "enrolled",
                "owner_approval_status": "approved",
                "approved_by_user_id": approver_user_id,
                "metadata_json": {
                    **metadata,
                    "approved_via_approval_record_id": approval_record["approval_record_id"],
                },
                "status": "completed",
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="channel_enrollment_owner_approved",
        )
        discovery = self.store.get_by_id("external_channel_discoveries", enrollment["discovery_id"])
        if discovery:
            self._link_discovery_enrollment(discovery, updated, status="promoted")
        self._audit_enrollment(
            "telegram_enrollment_owner_approved",
            updated,
            actor_type,
            actor_ref,
            "enrolled",
            {
                "channel_identity_id": identity["channel_identity_id"],
                "approval_record_id": approval_record["approval_record_id"],
            },
        )
        return {"enrollment": updated, "channel_identity": identity, "approval_record": approval_record}

    def suspend_enrollment(
        self,
        enrollment_id: str,
        *,
        actor_type: str = "user",
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._set_enrollment_terminal_or_hold(
            enrollment_id,
            state="suspended",
            status="suspended",
            identity_state="suspended",
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason=reason,
            event_type="telegram_enrollment_suspended",
        )

    def revoke_enrollment(
        self,
        enrollment_id: str,
        *,
        actor_type: str = "user",
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._set_enrollment_terminal_or_hold(
            enrollment_id,
            state="revoked",
            status="revoked",
            identity_state="revoked",
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason=reason,
            event_type="telegram_enrollment_revoked",
        )

    def require_rebinding(
        self,
        enrollment_id: str,
        *,
        actor_type: str = "user",
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._set_enrollment_terminal_or_hold(
            enrollment_id,
            state="rebinding_required",
            status="active",
            identity_state="rebinding_required",
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason=reason,
            event_type="telegram_enrollment_rebinding_required",
        )

    def request_recovery(
        self,
        enrollment_id: str,
        *,
        actor_type: str = "user",
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        enrollment = self._get_enrollment(enrollment_id)
        updated = self.store.update(
            "channel_enrollments",
            enrollment_id,
            {
                "state": "recovery_requested",
                "owner_approval_status": "requested",
                "metadata_json": {
                    **enrollment.get("metadata_json", {}),
                    "recovery_reason": reason,
                    "recovery_policy": "new challenge and owner approval required before trust is restored",
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="telegram_enrollment_recovery_requested",
        )
        self._audit_enrollment(
            "telegram_enrollment_recovery_requested",
            updated,
            actor_type,
            actor_ref,
            "recovery_requested",
        )
        return updated

    def create_outbound_message(
        self,
        *,
        thread_id: str,
        text: str,
        actor_type: str,
        actor_ref: str,
        sponsoring_user_id: str,
        classification: str = "internal",
        origin_entity_ref: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Telegram-ready outbound message after policy evaluation."""
        self.store.initialize()
        thread = self.store.get_by_id("threads", thread_id)
        if thread is None:
            raise ValueError(f"Thread not found: {thread_id}")
        if thread["channel_type"] != "telegram":
            raise ValueError("create_outbound_message only supports telegram threads")

        governance = self._validate_outbound_thread_governance(thread, sponsoring_user_id)
        destination_identity = self._destination_identity_for_thread(thread)
        message_event_id = new_id("msg")

        policy_result = self.policy_engine.evaluate_and_record(
            GovernedAction(
                action_type="share_external",
                actor_type=actor_type,
                actor_ref=actor_ref,
                sponsoring_user_id=sponsoring_user_id,
                object_type="message",
                object_ref=message_event_id,
                destination_type="channel",
                destination_identity=destination_identity,
                content_classification=classification,
                origin_entity_ref=origin_entity_ref,
                metadata={"thread_id": thread_id, "channel_type": "telegram"},
            )
        )
        decision = policy_result["decision"]["decision"]
        status = self._outbound_status_for_decision(decision)
        transport_result: dict[str, Any] = {
            "channel_type": "telegram",
            "destination_identity": destination_identity,
            "status": "stubbed" if status == "send_stubbed" else "not_sent",
            "live_transport": False,
        }
        send_request_ref = None
        if status == "send_stubbed" and self.bot_api_transport is not None:
            chat_id = self._telegram_chat_id_from_destination(destination_identity)
            transport_result = self.bot_api_transport.send_message(chat_id=chat_id, text=text)
            send_request_ref = self.store.write_artifact(
                f"transport/telegram/send-message-{message_event_id}.json",
                json.dumps(self._sanitized_transport_request(transport_result["request"]), indent=2, sort_keys=True),
            )
            status = self._status_for_transport_result(transport_result)

        content_ref, retention_mode, content_sha256 = self._persist_outbound_content(
            channel_type="telegram",
            thread_id=thread_id,
            message_id=message_event_id,
            text=text,
            status=status,
        )
        draft = self.store.insert(
            "messages",
            {
                "message_event_id": message_event_id,
                "thread_id": thread_id,
                "direction": "outbound",
                "sender_identity_json": self._sender_identity_for_actor(actor_type, actor_ref),
                "recipient_identities_json": [
                    {
                        "channel_type": "telegram",
                        "destination_type": "channel",
                        "destination_identity": destination_identity,
                    }
                ],
                "content_ref": content_ref,
                "classification": classification,
                "provenance_json": {
                    "channel_type": "telegram",
                    "transport": "stubbed",
                    "telegram_thread_mode": governance["thread_semantics"]["mode"],
                    "telegram_thread_behavior": governance["thread_semantics"]["behavior"],
                    "authority_policy_decision_id": governance["authority_decision"]["policy_decision"][
                        "policy_decision_id"
                    ],
                    "recipient_enrollment_refs": governance["recipient_enrollment_refs"],
                    "content_retention_mode": retention_mode,
                    "content_sha256": content_sha256,
                    "content_length": len(text),
                    **(provenance or {}),
                },
                "status": "drafted",
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )

        message = self.store.update(
            "messages",
            draft["message_event_id"],
            {
                "policy_decision_refs_json": [policy_result["decision"]["policy_decision_id"]],
                "status": status,
                "provenance_json": {
                    **draft["provenance_json"],
                    "transport": "telegram_bot_api" if self.bot_api_transport is not None else "stubbed",
                    "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                    "policy_outcome": decision,
                    "telegram_send_request_ref": send_request_ref,
                    "transport_status": transport_result["status"],
                    "live_transport": transport_result.get("live_transport", False),
                    "send_attempt": self._send_attempt_for_status(status),
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="telegram_outbound_message_policy_evaluated",
        )
        self.store.append_event(
            "telegram_outbound_message_ready",
            "message",
            message["message_event_id"],
            actor_type,
            actor_ref,
            {
                "thread_id": thread_id,
                "destination_identity": destination_identity,
                "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                "status": status,
                "transport_status": transport_result["status"],
                "telegram_send_request_ref": send_request_ref,
            },
            audit_event_id=policy_result["audit_event"]["audit_event_id"],
        )
        return {
            "message": message,
            "policy_result": policy_result,
            "transport": {
                **transport_result,
                "channel_type": "telegram",
                "destination_identity": destination_identity,
                "send_request_ref": send_request_ref,
            },
        }

    def surface_progress_update(
        self,
        progress_update_id: str,
        *,
        actor_type: str,
        actor_ref: str,
        sponsoring_user_id: str,
        classification: str = "internal",
        require_user_visible: bool = True,
    ) -> dict[str, Any]:
        """Transform a commitment progress update into a policy-gated Telegram update."""
        progress = self.store.get_by_id("progress_updates", progress_update_id)
        if progress is None:
            raise ValueError(f"Progress update not found: {progress_update_id}")
        if progress["parent_type"] != "commitment":
            raise ValueError("Only commitment progress updates can be surfaced in Stage 4")
        visibility = set(progress.get("visibility_policy_refs_json", []))
        if require_user_visible and "visibility:user" not in visibility:
            raise ValueError("Progress update is not marked user-visible")

        commitment = self.store.get_by_id("commitments", progress["parent_ref"])
        if commitment is None:
            raise ValueError(f"Commitment not found: {progress['parent_ref']}")
        thread = self._thread_for_commitment(commitment)
        text = self._format_progress_message(commitment, progress)
        return self.create_outbound_message(
            thread_id=thread["thread_id"],
            text=text,
            actor_type=actor_type,
            actor_ref=actor_ref,
            sponsoring_user_id=sponsoring_user_id,
            classification=classification,
            provenance={
                "source_progress_update_id": progress_update_id,
                "source_commitment_id": commitment["commitment_id"],
            },
        )

    def normalize_update(self, update: dict[str, Any]) -> TelegramInboundMessage:
        message = update.get("message") or update.get("edited_message") or update
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if "id" not in chat:
            raise ValueError("Telegram update is missing chat.id")
        if "id" not in sender:
            raise ValueError("Telegram update is missing from.id")
        text = message.get("text") or message.get("caption") or ""
        if not text.strip():
            raise ValueError("Telegram update is missing text/caption content")

        reply_to = message.get("reply_to_message") or {}
        display = self._display_name(sender)
        return TelegramInboundMessage(
            chat_id=str(chat["id"]),
            chat_type=str(chat.get("type") or "private"),
            message_id=str(message.get("message_id") or update.get("update_id") or new_id("telegram_msg")),
            sender_id=str(sender["id"]),
            sender_display_name=display,
            text=text.strip(),
            date=message.get("date"),
            username=sender.get("username"),
            bot_id=str(update.get("bot_id")) if update.get("bot_id") is not None else None,
            bot_username=update.get("bot_username"),
            reply_to_message_id=str(reply_to["message_id"]) if reply_to.get("message_id") is not None else None,
            raw_update=update,
        )

    def _apply_message_to_commitment(
        self,
        inbound: TelegramInboundMessage,
        message: dict[str, Any],
        thread: dict[str, Any],
        agent: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        intent = self._parse_intent(inbound.text)
        if intent["kind"] == "create_commitment":
            commitment = self.task_engine.create_commitment(
                title=intent["title"],
                commitment_type="telegram_request",
                owner_scope_type="agent",
                owner_scope_ref=agent["agent_id"],
                origin_ref_type="message",
                origin_ref=message["message_event_id"],
                priority=intent["priority"],
                next_action=intent["next_action"],
                completion_criteria={
                    "required": ["request addressed or explicitly moved to waiting/blocked"],
                    "proof_required": False,
                    "source": "telegram",
                },
                actor_type="agent",
                actor_ref=agent["agent_id"],
            )
            activated = self.task_engine.activate_commitment(
                commitment["commitment_id"],
                next_action=intent["next_action"],
                review_at=None,
                actor_type="agent",
                actor_ref=agent["agent_id"],
            )
            self._link_thread_commitment(thread["thread_id"], activated["commitment_id"])
            self.store.update(
                "messages",
                message["message_event_id"],
                {
                    "provenance_json": {
                        **message["provenance_json"],
                        "commitment_id": activated["commitment_id"],
                        "message_to_commitment_intent": intent["kind"],
                    }
                },
                actor_type="agent",
                actor_ref=agent["agent_id"],
                event_type="telegram_inbound_message_linked_to_commitment",
            )
            return {"commitment": activated, "intent": intent["kind"], "progress_update": None}

        if intent["kind"] == "update_commitment":
            commitment = self._resolve_update_commitment(intent, thread, inbound)
            if commitment is None:
                return {"commitment": None, "intent": "stored_message_no_matching_commitment", "progress_update": None}
            progress = self.task_engine.record_progress_update(
                commitment["commitment_id"],
                summary=intent["summary"],
                state_change={
                    "source": "telegram_inbound_update",
                    "message_event_id": message["message_event_id"],
                    "telegram_message_id": inbound.message_id,
                },
                visibility="internal",
                actor_type="user",
                actor_ref=user_id,
            )
            self.store.update(
                "messages",
                message["message_event_id"],
                {
                    "provenance_json": {
                        **message["provenance_json"],
                        "commitment_id": commitment["commitment_id"],
                        "progress_update_id": progress["progress_update_id"],
                        "message_to_commitment_intent": intent["kind"],
                    }
                },
                actor_type="user",
                actor_ref=user_id,
                event_type="telegram_inbound_message_updated_commitment",
            )
            return {"commitment": commitment, "intent": intent["kind"], "progress_update": progress}

        return {"commitment": None, "intent": intent["kind"], "progress_update": None}

    def _parse_intent(self, text: str) -> dict[str, Any]:
        lowered = text.lower().strip()
        create_prefixes = ("/commit", "commit:", "todo:", "task:")
        update_prefixes = ("/update", "update:", "progress:")

        for prefix in create_prefixes:
            if lowered.startswith(prefix):
                title = text[len(prefix) :].strip(" :-")
                title = title or "Telegram commitment"
                return {
                    "kind": "create_commitment",
                    "title": title[:160],
                    "next_action": f"Clarify and act on Telegram request: {title[:180]}",
                    "priority": 3,
                }
        for prefix in update_prefixes:
            if lowered.startswith(prefix):
                body = text[len(prefix) :].strip(" :-")
                commitment_id = None
                parts = body.split(maxsplit=1)
                if parts and parts[0].startswith("commitment_"):
                    commitment_id = parts[0]
                    body = parts[1] if len(parts) > 1 else ""
                return {
                    "kind": "update_commitment",
                    "commitment_id": commitment_id,
                    "summary": body or "Telegram update received.",
                }

        if lowered.startswith("please ") or lowered.startswith("remind me ") or lowered.startswith("can you "):
            return {
                "kind": "create_commitment",
                "title": text[:160],
                "next_action": f"Handle Telegram request: {text[:180]}",
                "priority": 3,
            }
        return {"kind": "stored_message"}

    def _resolve_update_commitment(
        self,
        intent: dict[str, Any],
        thread: dict[str, Any],
        inbound: TelegramInboundMessage,
    ) -> dict[str, Any] | None:
        if intent.get("commitment_id"):
            commitment = self.store.get_by_id("commitments", intent["commitment_id"])
            if commitment:
                return commitment

        if inbound.reply_to_message_id:
            message = self._message_by_telegram_id(inbound.chat_id, inbound.reply_to_message_id)
            if message:
                commitment_id = message.get("provenance_json", {}).get("commitment_id")
                if commitment_id:
                    commitment = self.store.get_by_id("commitments", commitment_id)
                    if commitment:
                        return commitment

        for commitment_id in reversed(thread.get("linked_commitment_ids_json", [])):
            commitment = self.store.get_by_id("commitments", commitment_id)
            if commitment and commitment["status"] not in TERMINAL_STATES:
                return commitment
        return None

    def _resolve_enrolled_sender_identity(self, inbound: TelegramInboundMessage) -> dict[str, Any] | None:
        address = f"telegram:user:{inbound.sender_id}"
        identity = self._channel_identity_by_address(address, enrolled_only=True)
        if identity and identity.get("user_id"):
            user = self.store.get_by_id("users", identity["user_id"])
            if user is None or user["status"] != "active":
                return None
            return identity
        return None

    def _contain_unauthorized_inbound(self, inbound: TelegramInboundMessage, update: dict[str, Any]) -> dict[str, Any]:
        address = f"telegram:user:{inbound.sender_id}"
        pairing_requested = self._is_pairing_request(inbound.text)
        discovery = self._resolve_or_create_discovery(
            address=address,
            display_name=inbound.sender_display_name,
            metadata={
                "telegram_user_id": inbound.sender_id,
                "telegram_username": inbound.username,
                "display_name": inbound.sender_display_name,
                "telegram_chat_id": inbound.chat_id,
                "telegram_chat_type": inbound.chat_type,
                "telegram_message_id": inbound.message_id,
                "telegram_date": inbound.date,
            },
            raw_update=update,
        )
        enrollment = self._latest_enrollment_by_address(address)
        if enrollment is None:
            enrollment = self.store.insert(
                "channel_enrollments",
                {
                    "channel_type": "telegram",
                    "address": address,
                    "discovery_id": discovery["discovery_id"],
                    "state": "pairing_requested" if pairing_requested else "discovered",
                    "challenge_status": "not_issued",
                    "owner_approval_status": "not_requested",
                    "metadata_json": {
                        "telegram_user_id": inbound.sender_id,
                        "telegram_username": inbound.username,
                        "display_name": inbound.sender_display_name,
                        "required_steps": ["pairing_request", "challenge_verification", "owner_approval"],
                        "first_contact_policy": "contained_until_enrolled",
                        "pairing_requested_from_adapter": pairing_requested,
                    },
                },
                actor_type="system",
                actor_ref="telegram_channel_service",
            )
            discovery_status = "pairing_requested" if pairing_requested else "discovered"
            self._link_discovery_enrollment(discovery, enrollment, status=discovery_status)
        elif enrollment["state"] != "enrolled":
            next_state = (
                "pairing_requested"
                if pairing_requested and enrollment["state"] == "discovered"
                else enrollment["state"]
            )
            self.store.update(
                "channel_enrollments",
                enrollment["enrollment_id"],
                {
                    "state": next_state,
                    "metadata_json": {
                        **enrollment.get("metadata_json", {}),
                        "last_unauthorized_telegram_message_id": inbound.message_id,
                        "last_unauthorized_chat_id": inbound.chat_id,
                        "pairing_requested_from_adapter": pairing_requested
                        or enrollment.get("metadata_json", {}).get("pairing_requested_from_adapter", False),
                    }
                },
                actor_type="system",
                actor_ref="telegram_channel_service",
                event_type="telegram_unauthorized_inbound_seen",
            )
            enrollment = self._get_enrollment(enrollment["enrollment_id"])
            if pairing_requested:
                self._link_discovery_enrollment(discovery, enrollment, status="pairing_requested")

        content_ref, content_preview = self._persist_pretrust_payload(
            channel_type="telegram",
            logical_id=f"{inbound.chat_id}-{inbound.message_id}",
            text=inbound.text,
            raw_payload=inbound.raw_update or update,
        )
        audit_event_type = (
            "telegram_pairing_requested" if pairing_requested else "telegram_unauthorized_inbound_contained"
        )
        audit = self.store.insert(
            "audit_events",
            {
                "event_type": audit_event_type,
                "actor_type": "system",
                "actor_ref": "telegram_channel_service",
                "object_type": "channel_enrollment",
                "object_ref": enrollment["enrollment_id"] if enrollment else discovery["discovery_id"],
                "action_summary": "Contained unauthorized Telegram inbound before trusted binding",
                "outcome": "pairing_requested" if pairing_requested else "contained",
                "metadata_json": {
                    "channel_type": "telegram",
                    "address": address,
                    "discovery_id": discovery["discovery_id"],
                    "enrollment_id": enrollment["enrollment_id"] if enrollment else None,
                    "content_ref": content_ref,
                    "content_preview": content_preview,
                    "telegram_chat_id": inbound.chat_id,
                    "telegram_message_id": inbound.message_id,
                    "raw_payload_retained": False,
                },
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
        )
        self.store.append_event(
            "telegram_pairing_requested" if pairing_requested else "telegram_unauthorized_inbound_contained",
            "channel_enrollment",
            enrollment["enrollment_id"] if enrollment else discovery["discovery_id"],
            "system",
            "telegram_channel_service",
            {
                "address": address,
                "discovery_id": discovery["discovery_id"],
                "content_ref": content_ref,
                "content_preview": content_preview,
                "trusted_thread_created": False,
                "canonical_user_created": False,
            },
            audit_event_id=audit["audit_event_id"],
        )
        return {
            "intent": "pairing_requested" if pairing_requested else "enrollment_required",
            "trusted": False,
            "contained": True,
            "reason": "telegram_sender_not_enrolled",
            "discovery": discovery,
            "enrollment": enrollment,
            "audit_event": audit,
            "content_ref": content_ref,
            "channel_identity": None,
            "agent_channel_identity": None,
            "thread": None,
            "message": None,
            "agent": None,
            "commitment": None,
            "progress_update": None,
        }

    def _assert_trusted_inbound_authority(self, user_id: str, sender_identity: dict[str, Any]) -> None:
        decision = self.authority_engine.evaluate(
            AuthorityRequest(
                actor_user_id=user_id,
                action="read",
                object_type="channel_identity",
                object_ref=sender_identity["channel_identity_id"],
                metadata={
                    "channel_type": "telegram",
                    "boundary": "trusted_inbound",
                    "enrollment_state": sender_identity.get("enrollment_state"),
                },
            )
        )
        if not decision["allowed"]:
            raise PermissionError("Enrolled Telegram sender lacks authority for its channel identity")

    def _validate_outbound_thread_governance(
        self,
        thread: dict[str, Any],
        sponsoring_user_id: str,
    ) -> dict[str, Any]:
        semantics = self._thread_semantics(thread)
        authority_decision = self.authority_engine.evaluate(
            AuthorityRequest(
                actor_user_id=sponsoring_user_id,
                action="read",
                object_type="thread",
                object_ref=thread["thread_id"],
                metadata={
                    "channel_type": "telegram",
                    "boundary": "outbound_send",
                    "telegram_thread_mode": semantics["mode"],
                },
            )
        )
        if not authority_decision["allowed"]:
            raise PermissionError("Sponsoring user lacks authority for Telegram thread")

        recipient_enrollment_refs = []
        for participant in thread.get("participants_json", []):
            identity_id = participant.get("channel_identity_id")
            if not identity_id:
                continue
            identity = self.store.get_by_id("channel_identities", identity_id)
            if (
                identity
                and identity.get("user_id")
                and identity["channel_type"] == "telegram"
                and identity["status"] == "active"
                and identity.get("enrollment_state") == "enrolled"
            ):
                recipient_enrollment_refs.append(
                    {
                        "channel_identity_id": identity["channel_identity_id"],
                        "user_id": identity["user_id"],
                        "enrollment_id": identity.get("enrollment_id"),
                        "binding_generation": identity.get("binding_generation"),
                    }
                )

        if not recipient_enrollment_refs:
            raise PermissionError("Telegram outbound thread has no active enrolled user recipient")
        if semantics["behavior"] == "monitor_only":
            raise PermissionError("Monitored Telegram threads do not permit outbound sends in V1 Chunk 3")

        return {
            "thread_semantics": semantics,
            "authority_decision": authority_decision,
            "recipient_enrollment_refs": recipient_enrollment_refs,
        }

    def _resolve_thread_semantics(
        self,
        inbound: TelegramInboundMessage,
        update: dict[str, Any],
        sender_identity: dict[str, Any],
    ) -> dict[str, str]:
        requested = ((update.get("agentfirst") or {}).get("telegram_thread_mode") or "").strip().lower()
        shared_context_id = (update.get("agentfirst") or {}).get("shared_context_id")
        if requested and requested not in {"private", "shared", "monitored"}:
            raise ValueError(f"Unsupported Telegram thread mode: {requested}")

        if requested == "shared" or (
            not requested and inbound.chat_type in {"group", "supergroup"} and shared_context_id
        ):
            if not shared_context_id:
                raise ValueError("Shared Telegram thread mode requires agentfirst.shared_context_id")
            context = self.store.get_by_id("shared_contexts", shared_context_id)
            if context is None or context["status"] != "active":
                raise ValueError(f"Shared context not active for Telegram thread: {shared_context_id}")
            decision = self.authority_engine.evaluate(
                AuthorityRequest(
                    actor_user_id=sender_identity["user_id"],
                    action="read",
                    object_type="shared_context",
                    object_ref=shared_context_id,
                    metadata={"channel_type": "telegram", "boundary": "shared_thread_inbound"},
                )
            )
            if not decision["allowed"]:
                raise PermissionError("Telegram sender lacks shared-context authority")
            return {
                "mode": "shared",
                "behavior": "shared_commitment_enabled",
                "visibility_model": "shared-members",
                "ownership_context_type": "shared_context",
                "ownership_context_ref": shared_context_id,
            }

        if requested == "monitored" or inbound.chat_type in {"group", "supergroup", "channel"}:
            return {
                "mode": "monitored",
                "behavior": "monitor_only",
                "visibility_model": "monitored",
                "ownership_context_type": "user",
                "ownership_context_ref": sender_identity["user_id"],
            }

        return {
            "mode": "private",
            "behavior": "private_commitment_enabled",
            "visibility_model": "private",
            "ownership_context_type": "user",
            "ownership_context_ref": sender_identity["user_id"],
        }

    def _thread_semantics(self, thread: dict[str, Any]) -> dict[str, str]:
        for participant in thread.get("participants_json", []):
            mode = participant.get("telegram_thread_mode")
            if mode:
                return {
                    "mode": mode,
                    "behavior": participant.get("telegram_thread_behavior") or "private_commitment_enabled",
                    "visibility_model": thread.get("visibility_model", "private"),
                }
        visibility = thread.get("visibility_model", "private")
        if visibility == "shared-members":
            return {"mode": "shared", "behavior": "shared_commitment_enabled", "visibility_model": visibility}
        if visibility == "monitored":
            return {"mode": "monitored", "behavior": "monitor_only", "visibility_model": visibility}
        return {"mode": "private", "behavior": "private_commitment_enabled", "visibility_model": visibility}

    def _is_pairing_request(self, text: str) -> bool:
        lowered = text.strip().lower()
        return lowered in {"/pair", "/pairing", "/start pair", "/start pairing"} or lowered.startswith("/pair ")

    def _resolve_or_create_agent_identity(
        self,
        agent_id: str,
        inbound: TelegramInboundMessage,
    ) -> dict[str, Any]:
        bot_ref = inbound.bot_id or inbound.bot_username or "agentfirst"
        address = f"telegram:bot:{bot_ref}:agent:{agent_id}"
        identity = self._channel_identity_by_address(address, enrolled_only=False)
        if identity:
            return identity
        return self.store.insert(
            "channel_identities",
            {
                "agent_id": agent_id,
                "channel_type": "telegram",
                "address": address,
                "metadata_json": {
                    "telegram_bot_id": inbound.bot_id,
                    "telegram_bot_username": inbound.bot_username,
                    "transport_role": "bot",
                },
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
        )

    def _resolve_or_create_user_agent(self, user_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agents
                WHERE owner_user_id = ? AND display_name = 'AgentFirst Telegram Agent' AND status = 'active'
                ORDER BY created_at
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if row:
                return self.store._decode_row(row)
        return self.store.insert(
            "agents",
            {
                "display_name": "AgentFirst Telegram Agent",
                "owner_user_id": user_id,
                "persona_profile_json": {"channel_surface": "telegram"},
                "capability_profile_json": {"telegram_channel_adapter": True, "commitment_first": True},
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
        )

    def _resolve_or_create_thread(
        self,
        inbound: TelegramInboundMessage,
        sender_identity: dict[str, Any],
        bot_identity: dict[str, Any],
        agent: dict[str, Any],
        update: dict[str, Any],
    ) -> dict[str, Any]:
        semantics = self._resolve_thread_semantics(inbound, update, sender_identity)
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM threads
                WHERE channel_type = 'telegram' AND status = 'active'
                ORDER BY created_at
                """
            ).fetchall()
            for row in rows:
                thread = self.store._decode_row(row)
                existing = self._thread_semantics(thread)
                if (
                    self._thread_has_telegram_chat(thread, inbound.chat_id)
                    and existing["mode"] == semantics["mode"]
                    and thread["ownership_context_type"] == semantics["ownership_context_type"]
                    and thread["ownership_context_ref"] == semantics["ownership_context_ref"]
                ):
                    return thread

        return self.store.insert(
            "threads",
            {
                "channel_type": "telegram",
                "ownership_context_type": semantics["ownership_context_type"],
                "ownership_context_ref": semantics["ownership_context_ref"],
                "participants_json": [
                    {
                        "channel_identity_id": sender_identity["channel_identity_id"],
                        "participant_role": "enrolled_sender",
                    },
                    {"channel_identity_id": bot_identity["channel_identity_id"]},
                    {"agent_id": agent["agent_id"]},
                    {
                        "telegram_chat_id": inbound.chat_id,
                        "telegram_chat_type": inbound.chat_type,
                        "telegram_thread_mode": semantics["mode"],
                        "telegram_thread_behavior": semantics["behavior"],
                        "destination_identity": f"telegram:chat:{inbound.chat_id}",
                    },
                ],
                "visibility_model": semantics["visibility_model"],
                "linked_commitment_ids_json": [],
                "status": "active",
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
        )

    def _link_thread_commitment(self, thread_id: str, commitment_id: str) -> None:
        thread = self.store.get_by_id("threads", thread_id)
        if thread is None:
            raise ValueError(f"Thread not found: {thread_id}")
        linked = list(thread.get("linked_commitment_ids_json", []))
        if commitment_id not in linked:
            linked.append(commitment_id)
            self.store.update(
                "threads",
                thread_id,
                {"linked_commitment_ids_json": linked},
                actor_type="system",
                actor_ref="telegram_channel_service",
                event_type="telegram_thread_linked_commitment",
            )

    def _thread_for_commitment(self, commitment: dict[str, Any]) -> dict[str, Any]:
        if commitment.get("origin_ref_type") == "message" and commitment.get("origin_ref"):
            message = self.store.get_by_id("messages", commitment["origin_ref"])
            if message:
                thread = self.store.get_by_id("threads", message["thread_id"])
                if thread:
                    return thread

        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE channel_type = 'telegram' AND status = 'active'"
            ).fetchall()
            for row in rows:
                thread = self.store._decode_row(row)
                if commitment["commitment_id"] in thread.get("linked_commitment_ids_json", []):
                    return thread
        raise ValueError(f"No Telegram thread found for commitment: {commitment['commitment_id']}")

    def _message_by_telegram_id(self, chat_id: str, telegram_message_id: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE direction = 'inbound'
                ORDER BY timestamp DESC
                """
            ).fetchall()
            for row in rows:
                message = self.store._decode_row(row)
                provenance = message.get("provenance_json", {})
                if (
                    provenance.get("channel_type") == "telegram"
                    and str(provenance.get("telegram_chat_id")) == str(chat_id)
                    and str(provenance.get("telegram_message_id")) == str(telegram_message_id)
                ):
                    return message
        return None

    def _resolve_or_create_discovery(
        self,
        *,
        address: str,
        display_name: str,
        metadata: dict[str, Any],
        raw_update: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM external_channel_discoveries
                WHERE channel_type = 'telegram' AND address = ?
                """,
                (address,),
            ).fetchone()
            discovery = self.store._decode_row(row) if row else None
        metadata_payload = self._discovery_metadata(metadata, raw_update)
        if discovery:
            return self.store.update(
                "external_channel_discoveries",
                discovery["discovery_id"],
                {
                    "display_name": display_name,
                    "last_seen_metadata_json": metadata_payload,
                    "last_seen_at": self._sqlite_now(),
                },
                actor_type="system",
                actor_ref="telegram_channel_service",
                event_type="external_channel_discovery_observed",
            )
        return self.store.insert(
            "external_channel_discoveries",
            {
                "channel_type": "telegram",
                "address": address,
                "display_name": display_name,
                "first_seen_metadata_json": metadata_payload,
                "last_seen_metadata_json": metadata_payload,
                "status": "discovered",
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
        )

    def _active_enrollment_by_address(self, address: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_enrollments
                WHERE channel_type = 'telegram' AND address = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            return self.store._decode_row(row) if row else None

    def _latest_enrollment_by_address(self, address: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_enrollments
                WHERE channel_type = 'telegram' AND address = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            return self.store._decode_row(row) if row else None

    def _get_enrollment(self, enrollment_id: str) -> dict[str, Any]:
        enrollment = self.store.get_by_id("channel_enrollments", enrollment_id)
        if enrollment is None:
            raise ValueError(f"Enrollment not found: {enrollment_id}")
        return enrollment

    def _link_discovery_enrollment(
        self,
        discovery: dict[str, Any],
        enrollment: dict[str, Any],
        *,
        status: str,
    ) -> None:
        self.store.update(
            "external_channel_discoveries",
            discovery["discovery_id"],
            {
                "enrollment_id": enrollment["enrollment_id"],
                "status": status,
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
            event_type="external_channel_discovery_enrollment_linked",
        )

    def _set_enrollment_terminal_or_hold(
        self,
        enrollment_id: str,
        *,
        state: str,
        status: str,
        identity_state: str,
        actor_type: str,
        actor_ref: str,
        reason: str,
        event_type: str,
    ) -> dict[str, Any]:
        enrollment = self._get_enrollment(enrollment_id)
        updated = self.store.update(
            "channel_enrollments",
            enrollment_id,
            {
                "state": state,
                "status": status,
                "owner_approval_status": "revoked" if state == "revoked" else enrollment["owner_approval_status"],
                "metadata_json": {
                    **enrollment.get("metadata_json", {}),
                    f"{state}_reason": reason,
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type=event_type,
        )
        identity_id = enrollment.get("channel_identity_id")
        if identity_id:
            identity_status = "revoked" if identity_state == "revoked" else "active"
            self.store.update(
                "channel_identities",
                identity_id,
                {
                    "enrollment_state": identity_state,
                    "status": identity_status,
                    "metadata_json": {
                        **(self.store.get_by_id("channel_identities", identity_id) or {}).get("metadata_json", {}),
                        f"{state}_reason": reason,
                    },
                },
                actor_type=actor_type,
                actor_ref=actor_ref,
                event_type=f"channel_identity_{identity_state}",
            )
        self._audit_enrollment(event_type, updated, actor_type, actor_ref, state, {"reason": reason})
        return updated

    def _audit_enrollment(
        self,
        event_type: str,
        enrollment: dict[str, Any],
        actor_type: str,
        actor_ref: str,
        outcome: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit = self.store.insert(
            "audit_events",
            {
                "event_type": event_type,
                "actor_type": actor_type,
                "actor_ref": actor_ref,
                "object_type": "channel_enrollment",
                "object_ref": enrollment["enrollment_id"],
                "action_summary": f"Telegram channel enrollment {outcome}",
                "outcome": outcome,
                "metadata_json": {
                    "channel_type": enrollment["channel_type"],
                    "address": enrollment["address"],
                    "state": enrollment["state"],
                    **(metadata or {}),
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        self.store.append_event(
            event_type,
            "channel_enrollment",
            enrollment["enrollment_id"],
            actor_type,
            actor_ref,
            {"outcome": outcome, **(metadata or {})},
            audit_event_id=audit["audit_event_id"],
        )
        return audit

    def _sqlite_now(self) -> str:
        with self.store.connect() as conn:
            row = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS now").fetchone()
            return str(row["now"])

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _expires_at(self, *, minutes: int) -> str:
        return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )

    def _challenge_secret_hash(self, *, enrollment_id: str, address: str, nonce: str, secret: str) -> str:
        return hashlib.sha256(f"{enrollment_id}|{address}|{nonce}|{secret}".encode("utf-8")).hexdigest()

    def _refresh_enrollment_challenge_hash(
        self,
        enrollment: dict[str, Any],
        challenge_secret: str,
        challenge_nonce: str,
    ) -> dict[str, Any]:
        metadata = dict(enrollment.get("metadata_json", {}))
        metadata["challenge_secret_hash"] = self._challenge_secret_hash(
            enrollment_id=enrollment["enrollment_id"],
            address=enrollment["address"],
            nonce=challenge_nonce,
            secret=challenge_secret,
        )
        return self.store.update(
            "channel_enrollments",
            enrollment["enrollment_id"],
            {"metadata_json": metadata},
            actor_type="system",
            actor_ref="telegram_channel_service",
            event_type="telegram_enrollment_challenge_material_hardened",
        )

    def _assert_valid_challenge_material(
        self,
        enrollment: dict[str, Any],
        metadata: dict[str, Any],
        *,
        challenge_secret: str | None,
        challenge_nonce: str | None,
    ) -> None:
        if not challenge_secret or not challenge_nonce:
            raise ValueError("Challenge verification requires challenge_secret and challenge_nonce")
        expected_nonce = metadata.get("challenge_nonce")
        expected_hash = metadata.get("challenge_secret_hash")
        expires_at = metadata.get("challenge_expires_at")
        attempt_count = int(metadata.get("challenge_attempt_count", 0))
        max_attempts = int(metadata.get("challenge_max_attempts", 5))
        if not expected_nonce or not expected_hash or not expires_at:
            raise ValueError("Enrollment challenge material is incomplete")
        if attempt_count >= max_attempts:
            raise PermissionError("Enrollment challenge attempt budget exhausted")
        if challenge_nonce != expected_nonce:
            self._record_challenge_failure(enrollment, metadata, "nonce_mismatch")
            raise PermissionError("Challenge nonce did not match the issued enrollment challenge")
        if datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(UTC):
            self._expire_enrollment(enrollment, metadata, reason="challenge_expired")
            raise PermissionError("Enrollment challenge has expired")
        actual_hash = self._challenge_secret_hash(
            enrollment_id=enrollment["enrollment_id"],
            address=enrollment["address"],
            nonce=challenge_nonce,
            secret=challenge_secret,
        )
        if actual_hash != expected_hash:
            self._record_challenge_failure(enrollment, metadata, "secret_mismatch")
            raise PermissionError("Challenge secret did not match the issued enrollment challenge")

    def _record_challenge_failure(self, enrollment: dict[str, Any], metadata: dict[str, Any], reason: str) -> None:
        self.store.update(
            "channel_enrollments",
            enrollment["enrollment_id"],
            {
                "metadata_json": {
                    **metadata,
                    "challenge_attempt_count": int(metadata.get("challenge_attempt_count", 0)) + 1,
                    "last_challenge_failure_reason": reason,
                    "last_challenge_failure_at": self._now_iso(),
                }
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
            event_type="telegram_enrollment_challenge_failed",
        )

    def _expire_enrollment(self, enrollment: dict[str, Any], metadata: dict[str, Any], *, reason: str) -> None:
        self.store.update(
            "channel_enrollments",
            enrollment["enrollment_id"],
            {
                "state": "expired",
                "status": "expired",
                "challenge_status": "expired",
                "metadata_json": {
                    **metadata,
                    "expired_reason": reason,
                    "expired_at": self._now_iso(),
                },
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
            event_type="telegram_enrollment_challenge_expired",
        )

    def _create_enrollment_approval_request(
        self,
        enrollment: dict[str, Any],
        *,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        approver_user_id = self._primary_user_id()
        if approver_user_id is None:
            raise PermissionError("No primary user exists to own enrollment approval")
        decision = self.store.insert(
            "policy_decisions",
            {
                "actor_type": actor_type,
                "actor_ref": actor_ref,
                "sponsoring_user_id": approver_user_id,
                "action_type": "enrollment:approve_channel_binding",
                "object_type": "channel_enrollment",
                "object_ref": enrollment["enrollment_id"],
                "destination_type": "channel_address",
                "destination_identity": enrollment["address"],
                "destination_trust_tier": 0,
                "content_classification": "private",
                "applicable_policy_refs_json": [],
                "decision": "require_owner_approval",
                "rationale_summary": "Verified external-channel enrollment requires explicit owner approval before trust promotion",
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        return self.store.insert(
            "approval_records",
            {
                "policy_decision_id": decision["policy_decision_id"],
                "requested_by_type": actor_type,
                "requested_by_ref": actor_ref,
                "approver_user_id": approver_user_id,
                "approval_type": "owner",
                "scope_json": {
                    "channel_type": enrollment["channel_type"],
                    "address": enrollment["address"],
                    "enrollment_id": enrollment["enrollment_id"],
                    "challenge_status": enrollment["challenge_status"],
                },
                "justification_summary": "External channel binding verified, pending owner approval before enrollment promotion",
                "status": "requested",
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )

    def _require_resolved_enrollment_approval(
        self,
        enrollment: dict[str, Any],
        *,
        approver_user_id: str,
    ) -> dict[str, Any]:
        approval_record_id = enrollment.get("metadata_json", {}).get("approval_record_id")
        if not approval_record_id:
            raise PermissionError("Enrollment is missing its canonical approval record")
        approval = self.store.get_by_id("approval_records", approval_record_id)
        if approval is None:
            raise PermissionError("Enrollment approval record not found")
        approver = self.store.get_by_id("users", approver_user_id)
        if approver is None or approver["status"] != "active":
            raise PermissionError("Enrollment approver is not an active user")
        if approval.get("approver_user_id") not in {None, approver_user_id} and not approver["primary_user_flag"]:
            raise PermissionError("Enrollment approval actor is not the assigned approver")
        if approval["status"] == "denied":
            self.store.update(
                "channel_enrollments",
                enrollment["enrollment_id"],
                {"state": "denied", "status": "denied", "owner_approval_status": "denied"},
                actor_type="user",
                actor_ref=approver_user_id,
                event_type="telegram_enrollment_owner_denied",
            )
            raise PermissionError("Enrollment approval was denied")
        if approval["status"] != "approved":
            raise PermissionError("Enrollment approval record must be approved before promotion")
        return approval

    def _primary_user_id(self) -> str | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE primary_user_flag = 1 AND status = 'active'").fetchone()
            return str(row["user_id"]) if row else None

    def _discovery_metadata(self, metadata: dict[str, Any], raw_update: dict[str, Any] | None) -> dict[str, Any]:
        forensic = bool(((raw_update or {}).get("agentfirst") or {}).get("forensic_retain_raw"))
        if not forensic:
            return {**metadata, "raw_payload_retained": False}
        raw_ref = self.store.write_artifact(
            f"quarantine/telegram/discovery-{new_id('raw')}.json",
            json.dumps(raw_update or {}, indent=2, sort_keys=True),
        )
        return {**metadata, "raw_payload_retained": True, "raw_payload_ref": raw_ref}

    def _persist_pretrust_payload(
        self,
        *,
        channel_type: str,
        logical_id: str,
        text: str,
        raw_payload: dict[str, Any] | None,
    ) -> tuple[str | None, str]:
        forensic = bool(((raw_payload or {}).get("agentfirst") or {}).get("forensic_retain_raw"))
        preview = text[:120]
        if not forensic:
            return None, preview
        content_ref = self.store.write_artifact(
            f"quarantine/{channel_type}/contained-inbound-{logical_id}.txt",
            text,
        )
        return content_ref, preview

    def _persist_outbound_content(
        self,
        *,
        channel_type: str,
        thread_id: str,
        message_id: str,
        text: str,
        status: str,
    ) -> tuple[str, str, str]:
        sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if status == "sent":
            return (
                self.store.write_artifact(f"messages/{channel_type}/outbound-{thread_id}-{message_id}.txt", text),
                "full_plaintext",
                sha256,
            )
        preview = {"preview": text[:120], "truncated": len(text) > 120, "sha256": sha256}
        return (
            self.store.write_artifact(
                f"messages/{channel_type}/outbound-preview-{thread_id}-{message_id}.json",
                json.dumps(preview, indent=2, sort_keys=True),
            ),
            "preview_only",
            sha256,
        )

    def _sanitized_transport_request(self, request: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(request)
        body = dict(sanitized.get("json_body", {}))
        if "text" in body:
            text = str(body["text"])
            body["text_preview"] = text[:120]
            body["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            body["text"] = "<redacted_unsent_body>"
        sanitized["json_body"] = body
        return sanitized

    def _channel_identity_by_address(self, address: str, *, enrolled_only: bool = True) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            enrollment_clause = "AND enrollment_state = 'enrolled'" if enrolled_only else ""
            row = conn.execute(
                f"""
                SELECT * FROM channel_identities
                WHERE channel_type = 'telegram' AND address = ? AND status = 'active'
                {enrollment_clause}
                """,
                (address,),
            ).fetchone()
            return self.store._decode_row(row) if row else None

    def _thread_has_telegram_chat(self, thread: dict[str, Any], chat_id: str) -> bool:
        for participant in thread.get("participants_json", []):
            if str(participant.get("telegram_chat_id")) == str(chat_id):
                return True
        return False

    def _destination_identity_for_thread(self, thread: dict[str, Any]) -> str:
        for participant in thread.get("participants_json", []):
            if participant.get("destination_identity"):
                return participant["destination_identity"]
            if participant.get("telegram_chat_id") is not None:
                return f"telegram:chat:{participant['telegram_chat_id']}"
        raise ValueError(f"Telegram thread is missing destination identity: {thread['thread_id']}")

    def _telegram_chat_id_from_destination(self, destination_identity: str) -> str:
        prefix = "telegram:chat:"
        if not destination_identity.startswith(prefix):
            raise ValueError(f"Unsupported Telegram destination identity: {destination_identity}")
        return destination_identity.removeprefix(prefix)

    def _sender_identity_for_actor(self, actor_type: str, actor_ref: str) -> dict[str, Any]:
        if actor_type == "agent":
            with self.store.connect() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM channel_identities
                    WHERE channel_type = 'telegram' AND agent_id = ? AND status = 'active'
                    ORDER BY created_at
                    LIMIT 1
                    """,
                    (actor_ref,),
                ).fetchone()
                if row:
                    identity = self.store._decode_row(row)
                    return {
                        "channel_identity_id": identity["channel_identity_id"],
                        "agent_id": actor_ref,
                        "channel_type": "telegram",
                        "address": identity["address"],
                    }
        return {"actor_type": actor_type, "actor_ref": actor_ref, "channel_type": "telegram"}

    def _format_progress_message(self, commitment: dict[str, Any], progress: dict[str, Any]) -> str:
        return f"Update on {commitment['title']}: {progress['summary']}"

    def _classification_from_update(self, update: dict[str, Any]) -> str:
        classification = (update.get("agentfirst") or {}).get("classification")
        if classification:
            return classification
        return "private"

    def _outbound_status_for_decision(self, decision: str) -> str:
        if decision in {"allow", "allow_with_logging", "allow_with_redaction"}:
            return "send_stubbed"
        if decision in {"require_primary_user_approval", "require_owner_approval"}:
            return "awaiting_policy_approval"
        return "blocked_by_policy"

    def _status_for_transport_result(self, transport_result: dict[str, Any]) -> str:
        if transport_result["status"] == "sent":
            return "sent"
        if transport_result["status"] == "prepared_not_sent":
            return "telegram_request_prepared"
        if transport_result["status"] == "not_sent_missing_token":
            return "telegram_request_blocked_missing_token"
        return "telegram_send_failed"

    def _send_attempt_for_status(self, status: str) -> str:
        if status == "send_stubbed":
            return "stubbed"
        if status == "telegram_request_prepared":
            return "prepared_not_sent"
        if status == "sent":
            return "live_sent"
        if status.startswith("telegram_"):
            return "telegram_transport_not_completed"
        return "not_attempted"

    def _display_name(self, sender: dict[str, Any]) -> str:
        if sender.get("first_name") or sender.get("last_name"):
            return " ".join(part for part in [sender.get("first_name"), sender.get("last_name")] if part)
        if sender.get("username"):
            return f"@{sender['username']}"
        return f"Telegram User {sender.get('id', 'unknown')}"

    def _challenge_secret_hash(self, *, enrollment_id: str, address: str, nonce: str, secret: str) -> str:
        material = "|".join([enrollment_id, address, nonce, secret]).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def _refresh_enrollment_challenge_hash(
        self,
        enrollment: dict[str, Any],
        challenge_secret: str,
        challenge_nonce: str,
    ) -> dict[str, Any]:
        metadata = dict(enrollment.get("metadata_json", {}))
        metadata["challenge_secret_hash"] = self._challenge_secret_hash(
            enrollment_id=enrollment["enrollment_id"],
            address=enrollment["address"],
            nonce=challenge_nonce,
            secret=challenge_secret,
        )
        return self.store.update(
            "channel_enrollments",
            enrollment["enrollment_id"],
            {"metadata_json": metadata},
            actor_type="system",
            actor_ref="telegram_channel_service",
            event_type="telegram_enrollment_challenge_material_bound",
        )

    def _assert_valid_challenge_material(
        self,
        enrollment: dict[str, Any],
        metadata: dict[str, Any],
        *,
        challenge_secret: str | None,
        challenge_nonce: str | None,
    ) -> None:
        expected_nonce = metadata.get("challenge_nonce")
        stored_hash = metadata.get("challenge_secret_hash")
        expires_at = metadata.get("challenge_expires_at")
        max_attempts = int(metadata.get("challenge_max_attempts", 5))
        attempts = int(metadata.get("challenge_attempt_count", 0))

        if attempts >= max_attempts:
            self._record_challenge_failure(enrollment, metadata, "max_attempts_exceeded")
            raise PermissionError("Challenge verification blocked after too many failed attempts")
        if not challenge_secret or not challenge_nonce:
            self._record_challenge_failure(enrollment, metadata, "missing_challenge_material")
            raise PermissionError("Challenge verification requires challenge_secret and challenge_nonce")
        if not expected_nonce or not stored_hash or challenge_nonce != expected_nonce:
            self._record_challenge_failure(enrollment, metadata, "challenge_nonce_mismatch")
            raise PermissionError("Challenge nonce mismatch")
        if expires_at and self._parse_iso(expires_at) <= datetime.now(UTC):
            self._record_challenge_failure(enrollment, metadata, "challenge_expired", expired=True)
            raise PermissionError("Challenge expired")

        computed = self._challenge_secret_hash(
            enrollment_id=enrollment["enrollment_id"],
            address=enrollment["address"],
            nonce=challenge_nonce,
            secret=challenge_secret,
        )
        if not secrets.compare_digest(computed, stored_hash):
            self._record_challenge_failure(enrollment, metadata, "challenge_secret_mismatch")
            raise PermissionError("Challenge secret mismatch")

    def _record_challenge_failure(
        self,
        enrollment: dict[str, Any],
        metadata: dict[str, Any],
        reason: str,
        *,
        expired: bool = False,
    ) -> None:
        attempts = int(metadata.get("challenge_attempt_count", 0)) + 1
        max_attempts = int(metadata.get("challenge_max_attempts", 5))
        new_state = enrollment["state"]
        new_status = enrollment["status"]
        challenge_status = enrollment["challenge_status"]
        if expired:
            new_state = "expired"
            new_status = "expired"
            challenge_status = "expired"
        elif attempts >= max_attempts:
            challenge_status = "revoked"
            new_state = "denied"
            new_status = "denied"
        updated = self.store.update(
            "channel_enrollments",
            enrollment["enrollment_id"],
            {
                "state": new_state,
                "status": new_status,
                "challenge_status": challenge_status,
                "metadata_json": {
                    **metadata,
                    "challenge_attempt_count": attempts,
                    "last_challenge_failure_reason": reason,
                    "last_challenge_failure_at": self._now_iso(),
                },
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
            event_type="telegram_enrollment_challenge_failed",
        )
        self._audit_enrollment(
            "telegram_enrollment_challenge_failed",
            updated,
            "system",
            "telegram_channel_service",
            "denied",
            {"reason": reason, "challenge_status": challenge_status},
        )

    def _create_enrollment_approval_request(
        self,
        enrollment: dict[str, Any],
        *,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            primary_user_id = self.policy_engine._primary_user_id(conn)
            if not primary_user_id:
                raise PermissionError("Enrollment approval requires a configured primary user")
            policy_decision = self.store.insert(
                "policy_decisions",
                {
                    "policy_decision_id": new_id("pdec"),
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "sponsoring_user_id": primary_user_id,
                    "action_type": "channel_enrollment_approval",
                    "object_type": "channel_enrollment",
                    "object_ref": enrollment["enrollment_id"],
                    "destination_type": "channel",
                    "destination_identity": enrollment["address"],
                    "destination_trust_tier": 0,
                    "content_classification": "private",
                    "applicable_policy_refs_json": [],
                    "decision": "require_primary_user_approval",
                    "rationale_summary": "Channel enrollment promotion requires explicit primary-user approval",
                },
                conn=conn,
                emit_event=False,
            )
            approval = self.store.insert(
                "approval_records",
                {
                    "approval_record_id": new_id("apr"),
                    "policy_decision_id": policy_decision["policy_decision_id"],
                    "requested_by_type": actor_type,
                    "requested_by_ref": actor_ref,
                    "approver_user_id": primary_user_id,
                    "approval_type": "primary_user",
                    "scope_json": {
                        "enrollment_id": enrollment["enrollment_id"],
                        "channel_type": enrollment["channel_type"],
                        "address": enrollment["address"],
                        "required_gate": "verified_challenge_and_primary_user_approval",
                    },
                    "justification_summary": "Promoting a channel enrollment to trusted identity requires explicit approval",
                    "status": "requested",
                },
                conn=conn,
                emit_event=False,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "telegram_enrollment_approval_requested",
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "object_type": "channel_enrollment",
                    "object_ref": enrollment["enrollment_id"],
                    "action_summary": "Telegram enrollment advanced to explicit approval gate",
                    "outcome": "requested",
                    "policy_decision_id": policy_decision["policy_decision_id"],
                    "metadata_json": {
                        "approval_record_id": approval["approval_record_id"],
                        "approver_user_id": primary_user_id,
                    },
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "telegram_enrollment_approval_requested",
                "channel_enrollment",
                enrollment["enrollment_id"],
                actor_type,
                actor_ref,
                {
                    "approval_record_id": approval["approval_record_id"],
                    "policy_decision_id": policy_decision["policy_decision_id"],
                },
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return approval

    def _require_resolved_enrollment_approval(
        self,
        enrollment: dict[str, Any],
        *,
        approver_user_id: str,
    ) -> dict[str, Any]:
        approval_record_id = enrollment.get("metadata_json", {}).get("approval_record_id")
        if not approval_record_id:
            raise PermissionError("Enrollment is missing explicit approval linkage")
        approval = self.store.get_by_id("approval_records", approval_record_id)
        if approval is None:
            raise PermissionError("Enrollment approval record not found")
        if approval["status"] != "approved":
            raise PermissionError("Enrollment approval has not been approved")
        if approval.get("approver_user_id") != approver_user_id:
            raise PermissionError("Enrollment approval was not resolved by the supplied approver")
        if approval.get("scope_json", {}).get("enrollment_id") != enrollment["enrollment_id"]:
            raise PermissionError("Enrollment approval scope mismatch")
        return approval

    def _persist_pretrust_payload(
        self,
        *,
        channel_type: str,
        logical_id: str,
        text: str,
        raw_payload: dict[str, Any] | None,
    ) -> tuple[str, str]:
        preview = self._preview_text(text)
        artifact = {
            "channel_type": channel_type,
            "retention_mode": "preview_only",
            "content_preview": preview,
            "content_length": len(text),
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "raw_payload_sha256": self._payload_sha256(raw_payload),
            "raw_payload_retained": False,
        }
        content_ref = self.store.write_artifact(
            f"enrollment/{channel_type}/contained-preview-{logical_id}.json",
            json.dumps(artifact, indent=2, sort_keys=True),
        )
        return content_ref, preview

    def _persist_outbound_content(
        self,
        *,
        channel_type: str,
        thread_id: str,
        message_id: str,
        text: str,
        status: str,
    ) -> tuple[str, str, str]:
        sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if status == "sent":
            retention_mode = "full_text"
            content_ref = self.store.write_artifact(
                f"messages/{channel_type}/outbound-{thread_id}-{message_id}.txt",
                text,
            )
        else:
            retention_mode = "preview_only"
            payload = {
                "channel_type": channel_type,
                "thread_id": thread_id,
                "message_id": message_id,
                "retention_mode": retention_mode,
                "content_preview": self._preview_text(text),
                "content_length": len(text),
                "content_sha256": sha256,
                "status": status,
            }
            content_ref = self.store.write_artifact(
                f"messages/{channel_type}/outbound-preview-{message_id}.json",
                json.dumps(payload, indent=2, sort_keys=True),
            )
        return content_ref, retention_mode, sha256

    def _sanitized_transport_request(self, request: dict[str, Any]) -> dict[str, Any]:
        sanitized = {
            **request,
            "headers": {
                key: value
                for key, value in (request.get("headers") or {}).items()
                if key.lower() != "authorization"
            },
        }
        body = dict(sanitized.get("json_body", {}))
        if "text" in body:
            text = str(body["text"])
            body["text_preview"] = self._preview_text(text, limit=120)
            body["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            body["text"] = "<redacted_unsent_body>"
        sanitized["json_body"] = body
        return sanitized

    def _discovery_metadata(self, metadata: dict[str, Any], raw_update: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(metadata)
        payload.update(
            {
                "raw_payload_retained": False,
                "raw_payload_sha256": self._payload_sha256(raw_update),
            }
        )
        return payload

    def _payload_sha256(self, payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _preview_text(self, text: str, limit: int = 96) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _expires_at(self, *, minutes: int) -> str:
        return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )

    def _parse_iso(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
