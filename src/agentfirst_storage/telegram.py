"""Telegram-first channel adapter for AgentFirst v0 Stage 4/5."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

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
    execute_live: bool = False
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: float = 10.0

    def prepare_send_message(self, *, chat_id: str, text: str) -> dict[str, Any]:
        token_marker = "<bot-token-present>" if self.bot_token else "<bot-token-missing>"
        return {
            "method": "POST",
            "url_template": f"{self.api_base_url}/bot{token_marker}/sendMessage",
            "telegram_method": "sendMessage",
            "json_body": {"chat_id": chat_id, "text": text},
            "headers": {"Content-Type": "application/json"},
            "token_present": bool(self.bot_token),
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
        if not self.bot_token:
            return {
                "status": "not_sent_missing_token",
                "request": request,
                "response": None,
                "live_transport": False,
                "reason": "bot_token is required for live Telegram transport",
            }

        url = f"{self.api_base_url}/bot{self.bot_token}/sendMessage"
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


class TelegramChannelService:
    """Narrow Telegram adapter that maps channel events into canonical objects."""

    def __init__(
        self,
        store: AgentFirstStore,
        *,
        policy_engine: PolicyEngine | None = None,
        task_engine: TaskEngine | None = None,
        bot_api_transport: TelegramBotApiTransport | None = None,
    ):
        self.store = store
        self.policy_engine = policy_engine or PolicyEngine(store)
        self.task_engine = task_engine or TaskEngine(store)
        self.bot_api_transport = bot_api_transport

    def ingest_message(self, update: dict[str, Any]) -> dict[str, Any]:
        """Persist an inbound Telegram-shaped message and apply explicit task intent."""
        inbound = self.normalize_update(update)
        self.store.initialize()

        sender_identity = self._resolve_or_create_sender_identity(inbound)
        user_id = sender_identity["user_id"]
        agent = self._resolve_or_create_user_agent(user_id)
        bot_identity = self._resolve_or_create_agent_identity(agent["agent_id"], inbound)
        thread = self._resolve_or_create_thread(inbound, sender_identity, bot_identity, agent)

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
        task_result = self._apply_message_to_commitment(inbound, message, thread, agent, user_id)
        result.update(task_result)
        return result

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

        destination_identity = self._destination_identity_for_thread(thread)
        content_ref = self.store.write_artifact(
            f"messages/telegram/outbound-{thread_id}-{new_id('msgbody')}.txt",
            text,
        )
        draft = self.store.insert(
            "messages",
            {
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
                    **(provenance or {}),
                },
                "status": "drafted",
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )

        policy_result = self.policy_engine.evaluate_and_record(
            GovernedAction(
                action_type="share_external",
                actor_type=actor_type,
                actor_ref=actor_ref,
                sponsoring_user_id=sponsoring_user_id,
                object_type="message",
                object_ref=draft["message_event_id"],
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
                f"transport/telegram/send-message-{draft['message_event_id']}.json",
                json.dumps(transport_result["request"], indent=2, sort_keys=True),
            )
            status = self._status_for_transport_result(transport_result)

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

    def _resolve_or_create_sender_identity(self, inbound: TelegramInboundMessage) -> dict[str, Any]:
        address = f"telegram:user:{inbound.sender_id}"
        identity = self._channel_identity_by_address(address)
        if identity:
            return identity

        user = self.store.create_user(
            inbound.sender_display_name,
            authority_tier="standard",
            contact_identities=[
                {
                    "channel_type": "telegram",
                    "address": address,
                    "username": inbound.username,
                }
            ],
            actor_type="system",
            actor_ref="telegram_channel_service",
        )
        return self.store.insert(
            "channel_identities",
            {
                "user_id": user["user_id"],
                "channel_type": "telegram",
                "address": address,
                "metadata_json": {
                    "telegram_user_id": inbound.sender_id,
                    "telegram_username": inbound.username,
                    "display_name": inbound.sender_display_name,
                },
            },
            actor_type="system",
            actor_ref="telegram_channel_service",
        )

    def _resolve_or_create_agent_identity(
        self,
        agent_id: str,
        inbound: TelegramInboundMessage,
    ) -> dict[str, Any]:
        bot_ref = inbound.bot_id or inbound.bot_username or "agentfirst"
        address = f"telegram:bot:{bot_ref}:agent:{agent_id}"
        identity = self._channel_identity_by_address(address)
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
    ) -> dict[str, Any]:
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
                if self._thread_has_telegram_chat(thread, inbound.chat_id):
                    return thread

        return self.store.insert(
            "threads",
            {
                "channel_type": "telegram",
                "ownership_context_type": "user",
                "ownership_context_ref": sender_identity["user_id"],
                "participants_json": [
                    {"channel_identity_id": sender_identity["channel_identity_id"]},
                    {"channel_identity_id": bot_identity["channel_identity_id"]},
                    {"agent_id": agent["agent_id"]},
                    {
                        "telegram_chat_id": inbound.chat_id,
                        "telegram_chat_type": inbound.chat_type,
                        "destination_identity": f"telegram:chat:{inbound.chat_id}",
                    },
                ],
                "visibility_model": "private",
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

    def _channel_identity_by_address(self, address: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_identities
                WHERE channel_type = 'telegram' AND address = ? AND status = 'active'
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
