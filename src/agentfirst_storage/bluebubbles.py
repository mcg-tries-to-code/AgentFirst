"""BlueBubbles/iMessage channel adapter for bounded AgentFirst V1 direct threads."""

from __future__ import annotations

import json
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .authority import AuthorityEngine, AuthorityRequest
from .policy import GovernedAction, PolicyEngine
from .store import AgentFirstStore, new_id
from .task_engine import TERMINAL_STATES, TaskEngine


@dataclass(frozen=True)
class BlueBubblesInboundMessage:
    """Normalized BlueBubbles/iMessage inbound message."""

    chat_guid: str
    message_guid: str
    sender_address: str
    sender_display_name: str
    text: str
    thread_class: str = "direct_1to1"
    handle_type: str = "phone"
    date_created: int | float | str | None = None
    raw_event: dict[str, Any] | None = None


@dataclass(frozen=True)
class BlueBubblesApiTransport:
    """Narrow BlueBubbles API boundary for preparing or executing a text send."""

    server_url: str = "http://localhost:1234"
    api_password: str | None = None
    execute_live: bool = False

    def prepare_send_message(self, *, chat_guid: str, text: str) -> dict[str, Any]:
        return {
            "method": "POST",
            "url_template": f"{self.server_url.rstrip('/')}/api/v1/message/text",
            "bluebubbles_method": "sendText",
            "json_body": {"chatGuid": chat_guid, "message": text},
            "headers": {"Content-Type": "application/json"},
            "password_present": bool(self.api_password),
            "execute_live": self.execute_live,
        }

    def send_message(self, *, chat_guid: str, text: str) -> dict[str, Any]:
        request = self.prepare_send_message(chat_guid=chat_guid, text=text)
        if not self.execute_live:
            return {
                "status": "prepared_not_sent",
                "request": request,
                "response": None,
                "live_transport": False,
                "reason": "execute_live is false",
            }
        return {
            "status": "not_sent_live_not_implemented",
            "request": request,
            "response": None,
            "live_transport": False,
            "reason": "Live BlueBubbles transport is intentionally out of scope for V1 Chunk 4 validation",
        }


class BlueBubblesChannelService:
    """Map BlueBubbles/iMessage events into enrolled, authority-aware core objects."""

    def __init__(
        self,
        store: AgentFirstStore,
        *,
        policy_engine: PolicyEngine | None = None,
        task_engine: TaskEngine | None = None,
        authority_engine: AuthorityEngine | None = None,
        api_transport: BlueBubblesApiTransport | None = None,
    ):
        self.store = store
        self.policy_engine = policy_engine or PolicyEngine(store)
        self.task_engine = task_engine or TaskEngine(store)
        self.authority_engine = authority_engine or AuthorityEngine(store)
        self.api_transport = api_transport

    def ingest_message(self, event: dict[str, Any]) -> dict[str, Any]:
        """Persist an inbound BlueBubbles event only after enrolled sender resolution."""
        inbound = self.normalize_event(event)
        self.store.initialize()

        sender_identity = self._resolve_enrolled_sender_identity(inbound)
        if sender_identity is None:
            return self._contain_unauthorized_inbound(inbound, event)

        if inbound.thread_class != "direct_1to1":
            return self._contain_unsupported_thread(inbound, sender_identity, event)

        user_id = sender_identity["user_id"]
        self._assert_trusted_inbound_authority(user_id, sender_identity)
        agent = self._resolve_or_create_user_agent(user_id)
        agent_identity = self._resolve_or_create_agent_identity(agent["agent_id"])
        thread = self._resolve_or_create_thread(inbound, sender_identity, agent_identity, agent)
        semantics = self._thread_semantics(thread)

        content_ref = self.store.write_artifact(
            f"messages/bluebubbles/inbound-{self._artifact_safe(inbound.chat_guid)}-{self._artifact_safe(inbound.message_guid)}.txt",
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
                    "channel_type": "bluebubbles",
                    "address": sender_identity["address"],
                },
                "recipient_identities_json": [
                    {
                        "channel_identity_id": agent_identity["channel_identity_id"],
                        "agent_id": agent["agent_id"],
                        "channel_type": "bluebubbles",
                        "address": agent_identity["address"],
                    }
                ],
                "content_ref": content_ref,
                "classification": self._classification_from_event(event),
                "provenance_json": {
                    "channel_type": "bluebubbles",
                    "imessage_chat_guid": inbound.chat_guid,
                    "imessage_message_guid": inbound.message_guid,
                    "imessage_sender_address": inbound.sender_address,
                    "imessage_handle_type": inbound.handle_type,
                    "imessage_thread_class": inbound.thread_class,
                    "bluebubbles_thread_mode": semantics["mode"],
                    "bluebubbles_thread_behavior": semantics["behavior"],
                    "date_created": inbound.date_created,
                    "raw_event": inbound.raw_event or event,
                },
                "status": "received",
            },
            actor_type="user",
            actor_ref=user_id,
        )

        result: dict[str, Any] = {
            "channel_identity": sender_identity,
            "agent_channel_identity": agent_identity,
            "thread": thread,
            "message": message,
            "agent": agent,
            "commitment": None,
            "progress_update": None,
            "intent": "stored_message",
        }
        task_result = self._apply_message_to_commitment(inbound, message, thread, agent, user_id)
        result.update(task_result)
        return result

    def issue_enrollment_challenge(
        self,
        *,
        sender_address: str,
        display_name: str,
        handle_type: str | None = None,
        requested_by_type: str = "system",
        requested_by_ref: str = "bluebubbles_channel_service",
    ) -> dict[str, Any]:
        """Create or advance a BlueBubbles enrollment to challenge-issued state."""
        self.store.initialize()
        normalized = self._normalize_address(sender_address)
        resolved_handle_type = handle_type or self._handle_type(normalized)
        address = self._channel_address(normalized, resolved_handle_type)
        discovery = self._resolve_or_create_discovery(
            address=address,
            display_name=display_name,
            metadata={
                "sender_address": normalized,
                "handle_type": resolved_handle_type,
                "display_name": display_name,
                "source": "explicit_pairing_request",
            },
            raw_event=None,
        )
        enrollment = self._active_enrollment_by_address(address)
        challenge_secret = secrets.token_urlsafe(12)
        challenge_nonce = new_id("nonce")
        issued_at = self._now_iso()
        expires_at = self._expires_at(minutes=15)
        challenge_ref = self.store.write_artifact(
            f"enrollment/bluebubbles/challenge-{new_id('challenge')}.txt",
            json.dumps(
                {
                    "channel_type": "bluebubbles",
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
            "channel_type": "bluebubbles",
            "address": address,
            "discovery_id": discovery["discovery_id"],
            "state": "challenge_issued",
            "challenge_ref": challenge_ref,
            "challenge_status": "issued",
            "owner_approval_status": "not_requested",
            "metadata_json": {
                "sender_address": normalized,
                "handle_type": resolved_handle_type,
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
                "thread_scope": "direct_1to1_only",
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
                {**values, "status": "active"},
                actor_type=requested_by_type,
                actor_ref=requested_by_ref,
                event_type="channel_enrollment_challenge_issued",
            )
        else:
            raise ValueError(f"Cannot issue challenge for enrollment in state {enrollment['state']}")
        enrollment = self._refresh_enrollment_challenge_hash(enrollment, challenge_secret, challenge_nonce)
        self._link_discovery_enrollment(discovery, enrollment, status="pairing_requested")
        self._audit_enrollment(
            "bluebubbles_enrollment_challenge_issued",
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
        actor_ref: str = "bluebubbles_channel_service",
    ) -> dict[str, Any]:
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
            "bluebubbles_enrollment_challenge_verified",
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
        existing = self._channel_identity_by_address(enrollment["address"], enrolled_only=False)
        if existing and existing.get("enrollment_state") == "enrolled" and existing["status"] == "active":
            raise ValueError(f"BlueBubbles address is already enrolled: {enrollment['address']}")

        metadata = dict(enrollment.get("metadata_json", {}))
        identity = self.store.insert(
            "channel_identities",
            {
                "user_id": user_id,
                "channel_type": "bluebubbles",
                "address": enrollment["address"],
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
            "bluebubbles_enrollment_owner_approved",
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
            event_type="bluebubbles_enrollment_suspended",
        )

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
        """Create a BlueBubbles-ready outbound message after authority and policy evaluation."""
        self.store.initialize()
        thread = self.store.get_by_id("threads", thread_id)
        if thread is None:
            raise ValueError(f"Thread not found: {thread_id}")
        if thread["channel_type"] != "bluebubbles":
            raise ValueError("create_outbound_message only supports bluebubbles threads")

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
                metadata={"thread_id": thread_id, "channel_type": "bluebubbles"},
            )
        )
        decision = policy_result["decision"]["decision"]
        status = self._outbound_status_for_decision(decision)
        transport_result: dict[str, Any] = {
            "channel_type": "bluebubbles",
            "destination_identity": destination_identity,
            "status": "stubbed" if status == "send_stubbed" else "not_sent",
            "live_transport": False,
        }
        send_request_ref = None
        if status == "send_stubbed" and self.api_transport is not None:
            chat_guid = self._chat_guid_from_destination(destination_identity)
            transport_result = self.api_transport.send_message(chat_guid=chat_guid, text=text)
            send_request_ref = self.store.write_artifact(
                f"transport/bluebubbles/send-message-{message_event_id}.json",
                json.dumps(self._sanitized_transport_request(transport_result["request"]), indent=2, sort_keys=True),
            )
            status = self._status_for_transport_result(transport_result)

        content_ref, retention_mode, content_sha256 = self._persist_outbound_content(
            channel_type="bluebubbles",
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
                        "channel_type": "bluebubbles",
                        "destination_type": "channel",
                        "destination_identity": destination_identity,
                    }
                ],
                "content_ref": content_ref,
                "classification": classification,
                "provenance_json": {
                    "channel_type": "bluebubbles",
                    "transport": "stubbed",
                    "bluebubbles_thread_mode": governance["thread_semantics"]["mode"],
                    "bluebubbles_thread_behavior": governance["thread_semantics"]["behavior"],
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
                    "transport": "bluebubbles_api" if self.api_transport is not None else "stubbed",
                    "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                    "policy_outcome": decision,
                    "bluebubbles_send_request_ref": send_request_ref,
                    "transport_status": transport_result["status"],
                    "live_transport": transport_result.get("live_transport", False),
                    "send_attempt": self._send_attempt_for_status(status),
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="bluebubbles_outbound_message_policy_evaluated",
        )
        self.store.append_event(
            "bluebubbles_outbound_message_ready",
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
                "bluebubbles_send_request_ref": send_request_ref,
            },
            audit_event_id=policy_result["audit_event"]["audit_event_id"],
        )
        return {
            "message": message,
            "policy_result": policy_result,
            "transport": {
                **transport_result,
                "channel_type": "bluebubbles",
                "destination_identity": destination_identity,
                "send_request_ref": send_request_ref,
            },
        }

    def normalize_event(self, event: dict[str, Any]) -> BlueBubblesInboundMessage:
        message = event.get("message") or event
        handle = message.get("handle") or event.get("handle") or {}
        chat = message.get("chat") or event.get("chat") or {}
        sender_address = (
            handle.get("address")
            or message.get("senderAddress")
            or message.get("address")
            or event.get("senderAddress")
            or event.get("address")
        )
        if not sender_address:
            raise ValueError("BlueBubbles event is missing sender address")
        if message.get("isFromMe") is True:
            raise ValueError("BlueBubbles inbound adapter does not process isFromMe messages")
        text = message.get("text") or message.get("message") or event.get("text") or ""
        if not str(text).strip():
            raise ValueError("BlueBubbles event is missing text/message content")

        participants = chat.get("participants") or event.get("participants") or []
        explicit_thread_class = (event.get("agentfirst") or {}).get("thread_class") or message.get("threadClass")
        thread_class = self._normalize_thread_class(explicit_thread_class, participants)
        normalized_address = self._normalize_address(str(sender_address))
        handle_type = str(handle.get("type") or event.get("handleType") or self._handle_type(normalized_address))
        display_name = (
            handle.get("displayName")
            or handle.get("uncanonicalizedId")
            or event.get("displayName")
            or normalized_address
        )
        chat_guid = str(chat.get("guid") or message.get("chatGuid") or event.get("chatGuid") or f"direct:{normalized_address}")
        message_guid = str(message.get("guid") or message.get("messageGuid") or event.get("guid") or new_id("bb_msg"))
        return BlueBubblesInboundMessage(
            chat_guid=chat_guid,
            message_guid=message_guid,
            sender_address=normalized_address,
            sender_display_name=str(display_name),
            text=str(text).strip(),
            thread_class=thread_class,
            handle_type=handle_type,
            date_created=message.get("dateCreated") or event.get("dateCreated"),
            raw_event=event,
        )

    def _apply_message_to_commitment(
        self,
        inbound: BlueBubblesInboundMessage,
        message: dict[str, Any],
        thread: dict[str, Any],
        agent: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        intent = self._parse_intent(inbound.text)
        if intent["kind"] == "create_commitment":
            commitment = self.task_engine.create_commitment(
                title=intent["title"],
                commitment_type="bluebubbles_request",
                owner_scope_type="agent",
                owner_scope_ref=agent["agent_id"],
                origin_ref_type="message",
                origin_ref=message["message_event_id"],
                priority=intent["priority"],
                next_action=intent["next_action"],
                completion_criteria={
                    "required": ["request addressed or explicitly moved to waiting/blocked"],
                    "proof_required": False,
                    "source": "bluebubbles",
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
                event_type="bluebubbles_inbound_message_linked_to_commitment",
            )
            return {"commitment": activated, "intent": intent["kind"], "progress_update": None}

        if intent["kind"] == "update_commitment":
            commitment = self._resolve_update_commitment(intent, thread)
            if commitment is None:
                return {"commitment": None, "intent": "stored_message_no_matching_commitment", "progress_update": None}
            progress = self.task_engine.record_progress_update(
                commitment["commitment_id"],
                summary=intent["summary"],
                state_change={
                    "source": "bluebubbles_inbound_update",
                    "message_event_id": message["message_event_id"],
                    "imessage_message_guid": inbound.message_guid,
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
                event_type="bluebubbles_inbound_message_updated_commitment",
            )
            return {"commitment": commitment, "intent": intent["kind"], "progress_update": progress}

        return {"commitment": None, "intent": intent["kind"], "progress_update": None}

    def _parse_intent(self, text: str) -> dict[str, Any]:
        lowered = text.lower().strip()
        create_prefixes = ("/commit", "commit:", "todo:", "task:")
        update_prefixes = ("/update", "update:", "progress:")
        for prefix in create_prefixes:
            if lowered.startswith(prefix):
                title = text[len(prefix) :].strip(" :-") or "BlueBubbles commitment"
                return {
                    "kind": "create_commitment",
                    "title": title[:160],
                    "next_action": f"Clarify and act on BlueBubbles/iMessage request: {title[:180]}",
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
                    "summary": body or "BlueBubbles/iMessage update received.",
                }
        if lowered.startswith("please ") or lowered.startswith("remind me ") or lowered.startswith("can you "):
            return {
                "kind": "create_commitment",
                "title": text[:160],
                "next_action": f"Handle BlueBubbles/iMessage request: {text[:180]}",
                "priority": 3,
            }
        return {"kind": "stored_message"}

    def _resolve_update_commitment(self, intent: dict[str, Any], thread: dict[str, Any]) -> dict[str, Any] | None:
        if intent.get("commitment_id"):
            commitment = self.store.get_by_id("commitments", intent["commitment_id"])
            if commitment:
                return commitment
        for commitment_id in reversed(thread.get("linked_commitment_ids_json", [])):
            commitment = self.store.get_by_id("commitments", commitment_id)
            if commitment and commitment["status"] not in TERMINAL_STATES:
                return commitment
        return None

    def _resolve_enrolled_sender_identity(self, inbound: BlueBubblesInboundMessage) -> dict[str, Any] | None:
        identity = self._channel_identity_by_address(
            self._channel_address(inbound.sender_address, inbound.handle_type),
            enrolled_only=True,
        )
        if identity and identity.get("user_id"):
            user = self.store.get_by_id("users", identity["user_id"])
            if user is None or user["status"] != "active":
                return None
            return identity
        return None

    def _contain_unauthorized_inbound(
        self,
        inbound: BlueBubblesInboundMessage,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        address = self._channel_address(inbound.sender_address, inbound.handle_type)
        pairing_requested = self._is_pairing_request(inbound.text)
        discovery = self._resolve_or_create_discovery(
            address=address,
            display_name=inbound.sender_display_name,
            metadata={
                "sender_address": inbound.sender_address,
                "handle_type": inbound.handle_type,
                "display_name": inbound.sender_display_name,
                "imessage_chat_guid": inbound.chat_guid,
                "imessage_message_guid": inbound.message_guid,
                "imessage_thread_class": inbound.thread_class,
                "date_created": inbound.date_created,
            },
            raw_event=event,
        )
        enrollment = self._latest_enrollment_by_address(address)
        if enrollment is None:
            enrollment = self.store.insert(
                "channel_enrollments",
                {
                    "channel_type": "bluebubbles",
                    "address": address,
                    "discovery_id": discovery["discovery_id"],
                    "state": "pairing_requested" if pairing_requested else "discovered",
                    "challenge_status": "not_issued",
                    "owner_approval_status": "not_requested",
                    "metadata_json": {
                        "sender_address": inbound.sender_address,
                        "handle_type": inbound.handle_type,
                        "display_name": inbound.sender_display_name,
                        "required_steps": ["pairing_request", "challenge_verification", "owner_approval"],
                        "first_contact_policy": "contained_until_enrolled",
                        "thread_scope": "direct_1to1_only",
                        "pairing_requested_from_adapter": pairing_requested,
                    },
                },
                actor_type="system",
                actor_ref="bluebubbles_channel_service",
            )
            self._link_discovery_enrollment(
                discovery,
                enrollment,
                status="pairing_requested" if pairing_requested else "discovered",
            )
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
                        "last_unauthorized_imessage_message_guid": inbound.message_guid,
                        "last_unauthorized_imessage_chat_guid": inbound.chat_guid,
                        "pairing_requested_from_adapter": pairing_requested
                        or enrollment.get("metadata_json", {}).get("pairing_requested_from_adapter", False),
                    },
                },
                actor_type="system",
                actor_ref="bluebubbles_channel_service",
                event_type="bluebubbles_unauthorized_inbound_seen",
            )
            enrollment = self._get_enrollment(enrollment["enrollment_id"])
            if pairing_requested:
                self._link_discovery_enrollment(discovery, enrollment, status="pairing_requested")

        return self._write_containment_result(
            inbound,
            event,
            discovery,
            enrollment,
            "bluebubbles_pairing_requested" if pairing_requested else "bluebubbles_unauthorized_inbound_contained",
            "pairing_requested" if pairing_requested else "contained",
            "pairing_requested" if pairing_requested else "enrollment_required",
            "bluebubbles_sender_not_enrolled",
        )

    def _contain_unsupported_thread(
        self,
        inbound: BlueBubblesInboundMessage,
        sender_identity: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any]:
        discovery = self._resolve_or_create_discovery(
            address=sender_identity["address"],
            display_name=inbound.sender_display_name,
            metadata={
                "sender_address": inbound.sender_address,
                "imessage_chat_guid": inbound.chat_guid,
                "imessage_message_guid": inbound.message_guid,
                "imessage_thread_class": inbound.thread_class,
                "unsupported_thread_policy": "suppressed_until_explicit_shared_or_group_semantics_exist",
            },
            raw_event=event,
        )
        audit_result = self._write_containment_result(
            inbound,
            event,
            discovery,
            None,
            "bluebubbles_unsupported_thread_contained",
            "contained",
            "unsupported_thread_contained",
            "bluebubbles_thread_class_not_enabled",
        )
        return {**audit_result, "channel_identity": sender_identity}

    def _write_containment_result(
        self,
        inbound: BlueBubblesInboundMessage,
        event: dict[str, Any],
        discovery: dict[str, Any],
        enrollment: dict[str, Any] | None,
        audit_event_type: str,
        audit_outcome: str,
        intent: str,
        reason: str,
    ) -> dict[str, Any]:
        content_ref, content_preview = self._persist_pretrust_payload(
            channel_type="bluebubbles",
            logical_id=f"{self._artifact_safe(inbound.chat_guid)}-{self._artifact_safe(inbound.message_guid)}",
            text=inbound.text,
            raw_payload=inbound.raw_event or event,
        )
        object_ref = enrollment["enrollment_id"] if enrollment else discovery["discovery_id"]
        audit = self.store.insert(
            "audit_events",
            {
                "event_type": audit_event_type,
                "actor_type": "system",
                "actor_ref": "bluebubbles_channel_service",
                "object_type": "channel_enrollment" if enrollment else "external_channel_discovery",
                "object_ref": object_ref,
                "action_summary": "Contained BlueBubbles/iMessage inbound before trusted direct-thread handling",
                "outcome": audit_outcome,
                "metadata_json": {
                    "channel_type": "bluebubbles",
                    "address": enrollment["address"] if enrollment else discovery["address"],
                    "discovery_id": discovery["discovery_id"],
                    "enrollment_id": enrollment["enrollment_id"] if enrollment else None,
                    "content_ref": content_ref,
                    "content_preview": content_preview,
                    "imessage_chat_guid": inbound.chat_guid,
                    "imessage_message_guid": inbound.message_guid,
                    "imessage_thread_class": inbound.thread_class,
                    "raw_payload_retained": bool(content_ref),
                },
            },
            actor_type="system",
            actor_ref="bluebubbles_channel_service",
        )
        self.store.append_event(
            audit_event_type,
            "channel_enrollment" if enrollment else "external_channel_discovery",
            object_ref,
            "system",
            "bluebubbles_channel_service",
            {
                "content_ref": content_ref,
                "content_preview": content_preview,
                "trusted_thread_created": False,
                "canonical_user_created": False,
            },
            audit_event_id=audit["audit_event_id"],
        )
        return {
            "intent": intent,
            "trusted": False,
            "contained": True,
            "reason": reason,
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
                    "channel_type": "bluebubbles",
                    "boundary": "trusted_inbound",
                    "enrollment_state": sender_identity.get("enrollment_state"),
                },
            )
        )
        if not decision["allowed"]:
            raise PermissionError("Enrolled BlueBubbles sender lacks authority for its channel identity")

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
                    "channel_type": "bluebubbles",
                    "boundary": "outbound_send",
                    "bluebubbles_thread_mode": semantics["mode"],
                },
            )
        )
        if not authority_decision["allowed"]:
            raise PermissionError("Sponsoring user lacks authority for BlueBubbles thread")
        if semantics["mode"] != "direct":
            raise PermissionError("Only direct BlueBubbles/iMessage threads permit outbound sends in V1 Chunk 4")

        recipient_enrollment_refs = []
        for participant in thread.get("participants_json", []):
            identity_id = participant.get("channel_identity_id")
            if not identity_id:
                continue
            identity = self.store.get_by_id("channel_identities", identity_id)
            if (
                identity
                and identity.get("user_id")
                and identity["channel_type"] == "bluebubbles"
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
            raise PermissionError("BlueBubbles outbound thread has no active enrolled user recipient")
        return {
            "thread_semantics": semantics,
            "authority_decision": authority_decision,
            "recipient_enrollment_refs": recipient_enrollment_refs,
        }

    def _resolve_or_create_agent_identity(self, agent_id: str) -> dict[str, Any]:
        address = f"bluebubbles:agent:{agent_id}"
        identity = self._channel_identity_by_address(address, enrolled_only=False)
        if identity:
            return identity
        return self.store.insert(
            "channel_identities",
            {
                "agent_id": agent_id,
                "channel_type": "bluebubbles",
                "address": address,
                "metadata_json": {"transport_role": "bluebubbles_sender", "thread_scope": "direct_1to1_only"},
            },
            actor_type="system",
            actor_ref="bluebubbles_channel_service",
        )

    def _resolve_or_create_user_agent(self, user_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agents
                WHERE owner_user_id = ? AND display_name = 'AgentFirst BlueBubbles Agent' AND status = 'active'
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
                "display_name": "AgentFirst BlueBubbles Agent",
                "owner_user_id": user_id,
                "persona_profile_json": {"channel_surface": "bluebubbles"},
                "capability_profile_json": {
                    "bluebubbles_channel_adapter": True,
                    "imessage_direct_threads": True,
                    "commitment_first": True,
                },
            },
            actor_type="system",
            actor_ref="bluebubbles_channel_service",
        )

    def _resolve_or_create_thread(
        self,
        inbound: BlueBubblesInboundMessage,
        sender_identity: dict[str, Any],
        agent_identity: dict[str, Any],
        agent: dict[str, Any],
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM threads
                WHERE channel_type = 'bluebubbles' AND status = 'active'
                ORDER BY created_at
                """
            ).fetchall()
            for row in rows:
                thread = self.store._decode_row(row)
                if (
                    self._thread_has_chat_guid(thread, inbound.chat_guid)
                    and thread["ownership_context_type"] == "user"
                    and thread["ownership_context_ref"] == sender_identity["user_id"]
                ):
                    return thread

        return self.store.insert(
            "threads",
            {
                "channel_type": "bluebubbles",
                "ownership_context_type": "user",
                "ownership_context_ref": sender_identity["user_id"],
                "participants_json": [
                    {
                        "channel_identity_id": sender_identity["channel_identity_id"],
                        "participant_role": "enrolled_sender",
                    },
                    {"channel_identity_id": agent_identity["channel_identity_id"]},
                    {"agent_id": agent["agent_id"]},
                    {
                        "imessage_chat_guid": inbound.chat_guid,
                        "imessage_thread_class": inbound.thread_class,
                        "bluebubbles_thread_mode": "direct",
                        "bluebubbles_thread_behavior": "direct_commitment_enabled",
                        "destination_identity": f"bluebubbles:chat:{inbound.chat_guid}",
                    },
                ],
                "visibility_model": "private",
                "linked_commitment_ids_json": [],
                "status": "active",
            },
            actor_type="system",
            actor_ref="bluebubbles_channel_service",
        )

    def _thread_semantics(self, thread: dict[str, Any]) -> dict[str, str]:
        for participant in thread.get("participants_json", []):
            mode = participant.get("bluebubbles_thread_mode")
            if mode:
                return {
                    "mode": mode,
                    "behavior": participant.get("bluebubbles_thread_behavior") or "direct_commitment_enabled",
                    "visibility_model": thread.get("visibility_model", "private"),
                }
        return {
            "mode": "direct",
            "behavior": "direct_commitment_enabled",
            "visibility_model": thread.get("visibility_model", "private"),
        }

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
                actor_ref="bluebubbles_channel_service",
                event_type="bluebubbles_thread_linked_commitment",
            )

    def _resolve_or_create_discovery(
        self,
        *,
        address: str,
        display_name: str,
        metadata: dict[str, Any],
        raw_event: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM external_channel_discoveries
                WHERE channel_type = 'bluebubbles' AND address = ?
                """,
                (address,),
            ).fetchone()
            discovery = self.store._decode_row(row) if row else None
        metadata_payload = self._discovery_metadata(metadata, raw_event)
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
                actor_ref="bluebubbles_channel_service",
                event_type="external_channel_discovery_observed",
            )
        return self.store.insert(
            "external_channel_discoveries",
            {
                "channel_type": "bluebubbles",
                "address": address,
                "display_name": display_name,
                "first_seen_metadata_json": metadata_payload,
                "last_seen_metadata_json": metadata_payload,
                "status": "discovered",
            },
            actor_type="system",
            actor_ref="bluebubbles_channel_service",
        )

    def _active_enrollment_by_address(self, address: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_enrollments
                WHERE channel_type = 'bluebubbles' AND address = ? AND status = 'active'
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
                WHERE channel_type = 'bluebubbles' AND address = ?
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
            {"enrollment_id": enrollment["enrollment_id"], "status": status},
            actor_type="system",
            actor_ref="bluebubbles_channel_service",
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
                "metadata_json": {**enrollment.get("metadata_json", {}), f"{state}_reason": reason},
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
                "action_summary": f"BlueBubbles/iMessage channel enrollment {outcome}",
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
            actor_ref="bluebubbles_channel_service",
            event_type="bluebubbles_enrollment_challenge_material_hardened",
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
            actor_ref="bluebubbles_channel_service",
            event_type="bluebubbles_enrollment_challenge_failed",
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
            actor_ref="bluebubbles_channel_service",
            event_type="bluebubbles_enrollment_challenge_expired",
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
                "decision": "require_primary_user_approval",
                "rationale_summary": "Verified external-channel enrollment requires explicit primary-user approval before trust promotion",
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
                "approval_type": "primary_user",
                "scope_json": {
                    "channel_type": enrollment["channel_type"],
                    "address": enrollment["address"],
                    "enrollment_id": enrollment["enrollment_id"],
                    "challenge_status": enrollment["challenge_status"],
                },
                "justification_summary": "External channel binding verified, pending primary-user approval before enrollment promotion",
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
                event_type="bluebubbles_enrollment_owner_denied",
            )
            raise PermissionError("Enrollment approval was denied")
        if approval["status"] != "approved":
            raise PermissionError("Enrollment approval record must be approved before promotion")
        return approval

    def _primary_user_id(self) -> str | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE primary_user_flag = 1 AND status = 'active'").fetchone()
            return str(row["user_id"]) if row else None

    def _discovery_metadata(self, metadata: dict[str, Any], raw_event: dict[str, Any] | None) -> dict[str, Any]:
        forensic = bool(((raw_event or {}).get("agentfirst") or {}).get("forensic_retain_raw"))
        if not forensic:
            return {**metadata, "raw_payload_retained": False}
        raw_ref = self.store.write_artifact(
            f"quarantine/bluebubbles/discovery-{new_id('raw')}.json",
            json.dumps(raw_event or {}, indent=2, sort_keys=True),
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
        message = body.get("message")
        if message is not None:
            text = str(message)
            body["message_preview"] = text[:120]
            body["message_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            body["message"] = "<redacted_unsent_body>"
        sanitized["json_body"] = body
        return sanitized

    def _channel_identity_by_address(self, address: str, *, enrolled_only: bool = True) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            enrollment_clause = "AND enrollment_state = 'enrolled'" if enrolled_only else ""
            row = conn.execute(
                f"""
                SELECT * FROM channel_identities
                WHERE channel_type = 'bluebubbles' AND address = ? AND status = 'active'
                {enrollment_clause}
                """,
                (address,),
            ).fetchone()
            return self.store._decode_row(row) if row else None

    def _sender_identity_for_actor(self, actor_type: str, actor_ref: str) -> dict[str, Any]:
        if actor_type == "agent":
            with self.store.connect() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM channel_identities
                    WHERE channel_type = 'bluebubbles' AND agent_id = ? AND status = 'active'
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
                        "channel_type": "bluebubbles",
                        "address": identity["address"],
                    }
        return {"actor_type": actor_type, "actor_ref": actor_ref, "channel_type": "bluebubbles"}

    def _thread_has_chat_guid(self, thread: dict[str, Any], chat_guid: str) -> bool:
        for participant in thread.get("participants_json", []):
            if str(participant.get("imessage_chat_guid")) == str(chat_guid):
                return True
        return False

    def _destination_identity_for_thread(self, thread: dict[str, Any]) -> str:
        for participant in thread.get("participants_json", []):
            if participant.get("destination_identity"):
                return participant["destination_identity"]
            if participant.get("imessage_chat_guid") is not None:
                return f"bluebubbles:chat:{participant['imessage_chat_guid']}"
        raise ValueError(f"BlueBubbles thread is missing destination identity: {thread['thread_id']}")

    def _chat_guid_from_destination(self, destination_identity: str) -> str:
        prefix = "bluebubbles:chat:"
        if not destination_identity.startswith(prefix):
            raise ValueError(f"Unsupported BlueBubbles destination identity: {destination_identity}")
        return destination_identity.removeprefix(prefix)

    def _normalize_thread_class(self, explicit: str | None, participants: list[Any]) -> str:
        if explicit:
            value = explicit.strip().lower()
            if value in {"direct", "dm", "1to1", "direct_1to1"}:
                return "direct_1to1"
            if value in {"group", "shared"}:
                return "group"
            return value
        return "direct_1to1" if len(participants) <= 1 else "group"

    def _normalize_address(self, address: str) -> str:
        value = address.strip()
        if "@" in value:
            return value.lower()
        digits = re.sub(r"\D", "", value)
        if len(digits) == 10:
            return f"+1{digits}"
        if digits:
            return f"+{digits}" if value.startswith("+") or len(digits) > 10 else digits
        return value

    def _handle_type(self, address: str) -> str:
        return "email" if "@" in address else "phone"

    def _channel_address(self, normalized_address: str, handle_type: str) -> str:
        return f"bluebubbles:{handle_type}:{normalized_address}"

    def _is_pairing_request(self, text: str) -> bool:
        lowered = text.strip().lower()
        return lowered in {"pair", "/pair", "pairing", "/pairing", "start pair", "/start pair"}

    def _classification_from_event(self, event: dict[str, Any]) -> str:
        return (event.get("agentfirst") or {}).get("classification") or "private"

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
            return "bluebubbles_request_prepared"
        if transport_result["status"].startswith("not_sent"):
            return "bluebubbles_request_blocked"
        return "bluebubbles_send_failed"

    def _send_attempt_for_status(self, status: str) -> str:
        if status == "send_stubbed":
            return "stubbed"
        if status == "bluebubbles_request_prepared":
            return "prepared_not_sent"
        if status == "sent":
            return "live_sent"
        if status.startswith("bluebubbles_"):
            return "bluebubbles_transport_not_completed"
        return "not_attempted"

    def _sqlite_now(self) -> str:
        with self.store.connect() as conn:
            row = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS now").fetchone()
            return str(row["now"])

    def _artifact_safe(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120] or "unknown"
