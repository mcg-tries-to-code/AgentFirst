"""Governable V1 memory and retrieval service."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .authority import AuthorityEngine, AuthorityRequest
from .store import AgentFirstStore, new_id


MEMORY_SCOPE_TYPES = {"user", "shared_context", "project", "agent"}
DEFAULT_LANE_KEY = "operator-default"


@dataclass(frozen=True)
class MemoryScope:
    """An explicit memory retrieval boundary."""

    scope_type: str
    scope_ref: str

    def as_dict(self) -> dict[str, str]:
        return {"scope_type": self.scope_type, "scope_ref": self.scope_ref}


@dataclass(frozen=True)
class MemoryRetrievalRequest:
    """A bounded V1 memory retrieval request."""

    actor_user_id: str
    sponsoring_user_id: str
    query: str
    scopes: list[MemoryScope]
    limit: int = 5
    canonicalities: set[str] = field(default_factory=lambda: {"canonical", "derived", "mirror"})


class MemoryService:
    """Create scoped memories and retrieve them under explicit authority checks."""

    def __init__(self, store: AgentFirstStore, authority_engine: AuthorityEngine | None = None):
        self.store = store
        self.authority_engine = authority_engine or AuthorityEngine(store)

    def ensure_lane(
        self,
        *,
        owner_scope_type: str | None = None,
        owner_scope_ref: str | None = None,
        lane_key: str = DEFAULT_LANE_KEY,
        display_name: str = "Operator Default Lane",
        role: str = "general",
        behavior: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        actor_type: str = "system",
        actor_ref: str = "memory_service",
    ) -> dict[str, Any]:
        """Create or return the bounded canonical identity for a conversational lane."""
        scope_type, scope_ref = self._resolve_owner_scope(owner_scope_type, owner_scope_ref)
        self._validate_scope(scope_type, scope_ref)
        self.store.initialize()
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM conversation_lanes
                WHERE owner_scope_type = ? AND owner_scope_ref = ? AND lane_key = ?
                """,
                (scope_type, scope_ref, lane_key),
            ).fetchone()
            if row:
                lane = self.store._decode_row(row)
            else:
                lane = self.store.insert(
                    "conversation_lanes",
                    {
                        "lane_id": new_id("lane"),
                        "owner_scope_type": scope_type,
                        "owner_scope_ref": scope_ref,
                        "lane_key": lane_key,
                        "display_name": display_name,
                        "role": role,
                        "behavior_json": behavior
                        or {
                            "bounded_role": role,
                            "reset_policy": "checkpoint_before_reset",
                            "telegram_mapping_status": "future_metadata_shape_only",
                        },
                        "metadata_json": metadata
                        or {
                            "created_for": "v1_feature4_lane_reset_scaffold",
                            "channel_mapping": {"telegram": "not_bound_in_this_slice"},
                        },
                        "status": "active",
                    },
                    conn=conn,
                    emit_event=False,
                    actor_type=actor_type,
                    actor_ref=actor_ref,
                )
                self.store.append_event(
                    "conversation_lane_created",
                    "conversation_lane",
                    lane["lane_id"],
                    actor_type,
                    actor_ref,
                    {"lane_key": lane_key, "owner_scope_type": scope_type, "owner_scope_ref": scope_ref},
                    conn=conn,
                )
            active = self._get_active_context(lane["lane_id"], conn=conn)
            if active is None:
                active = self._create_active_context(lane["lane_id"], 1, actor_type, actor_ref, conn=conn)
            return {"lane": lane, "active_context": active}

    def lane_snapshot(
        self,
        *,
        owner_scope_type: str | None = None,
        owner_scope_ref: str | None = None,
        lane_key: str = DEFAULT_LANE_KEY,
    ) -> dict[str, Any]:
        """Return lane identity, short-term active context, and recent checkpoint metadata."""
        lane_state = self.ensure_lane(
            owner_scope_type=owner_scope_type,
            owner_scope_ref=owner_scope_ref,
            lane_key=lane_key,
            actor_ref="memory_service.lane_snapshot",
        )
        lane = lane_state["lane"]
        with self.store.connect() as conn:
            checkpoint_rows = conn.execute(
                """
                SELECT * FROM lane_checkpoints
                WHERE lane_id = ?
                ORDER BY created_at DESC, checkpoint_id DESC
                LIMIT 5
                """,
                (lane["lane_id"],),
            ).fetchall()
        return {
            **lane_state,
            "recent_checkpoints": [self.store._decode_row(row) for row in checkpoint_rows],
            "lifecycle_layers": {
                "short_term": "lane_active_contexts",
                "mid_term": "lane_checkpoints",
                "long_term": "memory_records via later promotion; not implemented in Feature 4",
            },
        }

    def add_active_context_item(
        self,
        *,
        text: str,
        kind: str = "working_note",
        retention_intent: str = "ephemeral",
        owner_scope_type: str | None = None,
        owner_scope_ref: str | None = None,
        lane_key: str = DEFAULT_LANE_KEY,
        source_ref: str | None = None,
        actor_type: str = "system",
        actor_ref: str = "memory_service",
    ) -> dict[str, Any]:
        """Append a bounded short-term context item for validation and future channel adapters."""
        if not text.strip():
            raise ValueError("Active context text is required")
        lane_state = self.ensure_lane(
            owner_scope_type=owner_scope_type,
            owner_scope_ref=owner_scope_ref,
            lane_key=lane_key,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        active = lane_state["active_context"]
        context = active["context_json"] or {}
        items = list(context.get("items", []))
        item = {
            "item_id": new_id("ctxitem"),
            "kind": kind,
            "text": text.strip(),
            "retention_intent": retention_intent,
            "source_ref": source_ref or f"lane:{lane_state['lane']['lane_id']}",
            "captured_at": _now(),
        }
        items.append(item)
        context = {
            **context,
            "lifecycle_layer": "short_term_active_context",
            "items": items,
            "item_count": len(items),
        }
        source_refs = list(active["source_refs_json"] or [])
        if item["source_ref"] not in source_refs:
            source_refs.append(item["source_ref"])
        updated = self.store.update(
            "lane_active_contexts",
            active["active_context_id"],
            {"context_json": context, "source_refs_json": source_refs, "updated_at": _now()},
            emit_event=True,
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="lane_active_context_item_added",
        )
        return {"lane": lane_state["lane"], "active_context": updated, "item": item}

    def reset_lane(
        self,
        *,
        command: str,
        owner_scope_type: str | None = None,
        owner_scope_ref: str | None = None,
        lane_key: str = DEFAULT_LANE_KEY,
        actor_type: str = "system",
        actor_ref: str = "command_surface",
    ) -> dict[str, Any]:
        """Checkpoint selected short-term signal, then reset `/new` or `/restart` lane state."""
        if command not in {"/new", "/restart"}:
            raise ValueError("reset command must be /new or /restart")
        lane_state = self.ensure_lane(
            owner_scope_type=owner_scope_type,
            owner_scope_ref=owner_scope_ref,
            lane_key=lane_key,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        lane = lane_state["lane"]
        active = lane_state["active_context"]
        preserved, dropped = self._partition_checkpoint_items(active["context_json"].get("items", []))
        checkpoint_id = new_id("chk")
        checkpoint_payload = self._checkpoint_payload(command, lane, active, preserved, dropped)
        summary_ref = self.store.write_artifact(
            f"memory/lane_checkpoints/{lane['lane_id']}/{checkpoint_id}.json",
            json.dumps(checkpoint_payload, indent=2, sort_keys=True),
        )
        memory_record_id = None
        with self.store.connect() as conn:
            if preserved:
                memory_record = self.store.insert(
                    "memory_records",
                    {
                        "memory_type": "summary",
                        "owner_scope_type": lane["owner_scope_type"],
                        "owner_scope_ref": lane["owner_scope_ref"],
                        "visibility_policy_refs_json": [],
                        "source_refs_json": [
                            f"conversation_lane:{lane['lane_id']}",
                            f"lane_active_context:{active['active_context_id']}",
                            f"lane_checkpoint:{checkpoint_id}",
                        ],
                        "content_ref": summary_ref,
                        "confidence": 0.75,
                        "canonicality": "derived",
                        "status": "active",
                    },
                    conn=conn,
                    emit_event=False,
                    actor_type=actor_type,
                    actor_ref=actor_ref,
                )
                memory_record_id = memory_record["memory_id"]
            checkpoint = self.store.insert(
                "lane_checkpoints",
                {
                    "checkpoint_id": checkpoint_id,
                    "lane_id": lane["lane_id"],
                    "active_context_id": active["active_context_id"],
                    "reset_command": command,
                    "owner_scope_type": lane["owner_scope_type"],
                    "owner_scope_ref": lane["owner_scope_ref"],
                    "lifecycle_layer": "mid_term_checkpoint",
                    "summary_ref": summary_ref,
                    "checkpoint_payload_json": checkpoint_payload,
                    "preserved_refs_json": [item["item_id"] for item in preserved],
                    "dropped_ephemeral_json": [
                        {"item_id": item["item_id"], "kind": item["kind"], "reason": "ephemeral_or_low_signal"}
                        for item in dropped
                    ],
                    "memory_record_id": memory_record_id,
                    "wiki_candidate_refs_json": [],
                    "status": "captured" if preserved else "empty",
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            old_status = "cleared" if command == "/new" else "reinitialized"
            self.store.update(
                "lane_active_contexts",
                active["active_context_id"],
                {
                    "status": old_status,
                    "runtime_state_json": {
                        **(active["runtime_state_json"] or {}),
                        "closed_by": command,
                        "checkpoint_id": checkpoint_id,
                        "closed_at": _now(),
                    },
                    "updated_at": _now(),
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            new_runtime = {
                "initialized_by": command,
                "checkpoint_id": checkpoint_id,
                "previous_active_context_id": active["active_context_id"],
                "reset_semantics": (
                    "fresh_conversation_working_set" if command == "/new" else "same_lane_runtime_reinitialized"
                ),
            }
            new_active = self._create_active_context(
                lane["lane_id"],
                int(active["session_generation"]) + 1,
                actor_type,
                actor_ref,
                runtime_state=new_runtime,
                conn=conn,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "lane_checkpoint_before_reset",
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "object_type": "conversation_lane",
                    "object_ref": lane["lane_id"],
                    "action_summary": f"{command} checkpointed lane context before reset",
                    "outcome": checkpoint["status"],
                    "metadata_json": {
                        "checkpoint_id": checkpoint_id,
                        "active_context_id": active["active_context_id"],
                        "new_active_context_id": new_active["active_context_id"],
                        "preserved_count": len(preserved),
                        "dropped_ephemeral_count": len(dropped),
                        "memory_record_id": memory_record_id,
                        "wiki_mutation": "not_performed",
                    },
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "lane_reset_checkpointed",
                "conversation_lane",
                lane["lane_id"],
                actor_type,
                actor_ref,
                {
                    "command": command,
                    "checkpoint_id": checkpoint_id,
                    "audit_event_id": audit["audit_event_id"],
                    "new_active_context_id": new_active["active_context_id"],
                },
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
        return {
            "status": "checkpointed",
            "command": command,
            "lane": lane,
            "checkpoint": checkpoint,
            "new_active_context": new_active,
            "transparent_checkpoint_output": {
                "checkpointed": {
                    "count": len(preserved),
                    "item_refs": [item["item_id"] for item in preserved],
                    "summary_ref": summary_ref,
                    "memory_record_id": memory_record_id,
                    "lifecycle_layer": "mid_term_checkpoint",
                },
                "left_untouched": [
                    "canonical operational state",
                    "long-term memory records",
                    "knowledge/wiki store",
                    "shared guidance layer",
                ],
                "dropped_ephemeral": {
                    "count": len(dropped),
                    "item_refs": [item["item_id"] for item in dropped],
                    "reason": "ephemeral_or_low_signal",
                },
                "wiki_mutation": "not_performed",
                "reset_semantics": new_runtime["reset_semantics"],
            },
        }

    def create_memory(
        self,
        *,
        owner_scope_type: str,
        owner_scope_ref: str,
        memory_type: str,
        body: str,
        canonicality: str = "canonical",
        source_refs: list[str] | None = None,
        visibility_policy_refs: list[str] | None = None,
        confidence: float = 1.0,
        actor_type: str = "system",
        actor_ref: str = "memory_service",
    ) -> dict[str, Any]:
        """Persist a scoped memory record with content stored as an artifact."""
        self._validate_scope(owner_scope_type, owner_scope_ref)
        if canonicality not in {"canonical", "mirror", "derived", "speculative", "scratch"}:
            raise ValueError(f"Unsupported memory canonicality: {canonicality}")

        self.store.initialize()
        content_ref = self.store.write_artifact(
            f"memory/{owner_scope_type}/{owner_scope_ref}/{new_id('memcontent')}.txt",
            body,
        )
        return self.store.insert(
            "memory_records",
            {
                "memory_type": memory_type,
                "owner_scope_type": owner_scope_type,
                "owner_scope_ref": owner_scope_ref,
                "visibility_policy_refs_json": visibility_policy_refs or [],
                "source_refs_json": source_refs or [],
                "content_ref": content_ref,
                "confidence": confidence,
                "canonicality": canonicality,
                "status": "active",
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )

    def retrieve(self, request: MemoryRetrievalRequest) -> dict[str, Any]:
        """Retrieve memories only from explicitly requested and authority-allowed scopes."""
        if not request.query.strip():
            raise ValueError("Memory retrieval query is required")
        if not request.scopes:
            raise ValueError("At least one explicit memory scope is required")
        if request.limit < 1:
            raise ValueError("Memory retrieval limit must be positive")

        self.store.initialize()
        requested_scopes = [scope.as_dict() for scope in request.scopes]
        for scope in requested_scopes:
            self._validate_scope(scope["scope_type"], scope["scope_ref"])

        decisions = []
        allowed_scopes = []
        denied_scopes = []
        for scope in requested_scopes:
            decision = self.authority_engine.evaluate(
                AuthorityRequest(
                    actor_user_id=request.actor_user_id,
                    action="read",
                    object_type=self._authority_object_type(scope["scope_type"]),
                    object_ref=scope["scope_ref"],
                    metadata={
                        "retrieval_query": request.query,
                        "memory_scope_type": scope["scope_type"],
                        "sponsoring_user_id": request.sponsoring_user_id,
                    },
                )
            )
            decisions.append(decision)
            scope_with_decision = {
                **scope,
                "policy_decision_id": decision["policy_decision"]["policy_decision_id"],
                "rationale": decision["rationale"],
            }
            if decision["allowed"]:
                allowed_scopes.append(scope_with_decision)
            else:
                denied_scopes.append(scope_with_decision)

        if denied_scopes:
            retrieval = self._record_retrieval(
                request,
                requested_scopes=requested_scopes,
                allowed_scopes=allowed_scopes,
                denied_scopes=denied_scopes,
                decisions=decisions,
                results=[],
                status="denied",
            )
            return {"retrieval": retrieval, "results": [], "authority_decisions": decisions}

        results = self._search_allowed_memory(
            query=request.query,
            allowed_scopes=allowed_scopes,
            canonicalities=request.canonicalities,
            limit=request.limit,
        )
        retrieval = self._record_retrieval(
            request,
            requested_scopes=requested_scopes,
            allowed_scopes=allowed_scopes,
            denied_scopes=[],
            decisions=decisions,
            results=results,
            status="returned" if results else "empty",
        )
        return {"retrieval": retrieval, "results": results, "authority_decisions": decisions}

    def _search_allowed_memory(
        self,
        *,
        query: str,
        allowed_scopes: list[dict[str, Any]],
        canonicalities: set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        query_terms = [term for term in query.lower().split() if term]
        scopes = {(scope["scope_type"], scope["scope_ref"]) for scope in allowed_scopes}
        results = []
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_records
                WHERE status = 'active'
                ORDER BY updated_at DESC, memory_id
                """
            ).fetchall()
            for row in rows:
                memory = self.store._decode_row(row)
                if (memory["owner_scope_type"], memory["owner_scope_ref"]) not in scopes:
                    continue
                if memory["canonicality"] not in canonicalities:
                    continue
                body = self._read_content(memory["content_ref"])
                haystack = body.lower()
                score = sum(1 for term in query_terms if term in haystack)
                if score < 1:
                    continue
                results.append(
                    {
                        "memory_id": memory["memory_id"],
                        "memory_type": memory["memory_type"],
                        "owner_scope_type": memory["owner_scope_type"],
                        "owner_scope_ref": memory["owner_scope_ref"],
                        "canonicality": memory["canonicality"],
                        "confidence": memory["confidence"],
                        "source_refs": memory["source_refs_json"],
                        "content_ref": memory["content_ref"],
                        "snippet": self._snippet(body, query_terms),
                        "score": score,
                        "provenance": {
                            "record_type": "memory_record",
                            "memory_id": memory["memory_id"],
                            "content_ref": memory["content_ref"],
                            "source_refs": memory["source_refs_json"],
                            "scope": {
                                "type": memory["owner_scope_type"],
                                "ref": memory["owner_scope_ref"],
                            },
                            "canonicality": memory["canonicality"],
                        },
                    }
                )
        return sorted(results, key=lambda item: (-item["score"], item["memory_id"]))[:limit]

    def _record_retrieval(
        self,
        request: MemoryRetrievalRequest,
        *,
        requested_scopes: list[dict[str, str]],
        allowed_scopes: list[dict[str, Any]],
        denied_scopes: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        results: list[dict[str, Any]],
        status: str,
    ) -> dict[str, Any]:
        decision_ids = [decision["policy_decision"]["policy_decision_id"] for decision in decisions]
        result_refs = [result["memory_id"] for result in results]
        provenance = {
            "bounded_version": "v1-chunk8",
            "scope_count": len(requested_scopes),
            "authority_policy_decision_refs": decision_ids,
            "result_count": len(results),
            "no_cross_scope_leakage": not denied_scopes,
            "retrieval_strategy": "explicit_scope_authority_filter_then_simple_term_match",
        }
        with self.store.connect() as conn:
            retrieval = self.store.insert(
                "memory_retrievals",
                {
                    "retrieval_id": new_id("retr"),
                    "actor_user_id": request.actor_user_id,
                    "sponsoring_user_id": request.sponsoring_user_id,
                    "query": request.query,
                    "requested_scopes_json": requested_scopes,
                    "allowed_scopes_json": allowed_scopes,
                    "denied_scopes_json": denied_scopes,
                    "authority_policy_decision_refs_json": decision_ids,
                    "result_refs_json": result_refs,
                    "provenance_json": provenance,
                    "status": status,
                },
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=request.actor_user_id,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "memory_retrieval_recorded",
                    "actor_type": "user",
                    "actor_ref": request.actor_user_id,
                    "object_type": "memory_retrieval",
                    "object_ref": retrieval["retrieval_id"],
                    "action_summary": f"Memory retrieval recorded as {status}",
                    "outcome": status,
                    "policy_decision_id": decision_ids[0] if decision_ids else None,
                    "metadata_json": {
                        "requested_scopes": requested_scopes,
                        "allowed_scope_count": len(allowed_scopes),
                        "denied_scope_count": len(denied_scopes),
                        "result_count": len(results),
                        "authority_policy_decision_refs": decision_ids,
                    },
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "memory_retrieval_recorded",
                "memory_retrieval",
                retrieval["retrieval_id"],
                "user",
                request.actor_user_id,
                {"status": status, "audit_event_id": audit["audit_event_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return retrieval

    def _validate_scope(self, scope_type: str, scope_ref: str) -> None:
        if scope_type not in MEMORY_SCOPE_TYPES:
            raise ValueError(f"Unsupported memory scope_type: {scope_type}")
        if not scope_ref:
            raise ValueError("Memory scope_ref is required")

    def _resolve_owner_scope(self, scope_type: str | None, scope_ref: str | None) -> tuple[str, str]:
        if scope_type or scope_ref:
            if not scope_type or not scope_ref:
                raise ValueError("Both owner_scope_type and owner_scope_ref are required")
            return scope_type, scope_ref
        self.store.initialize()
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE primary_user_flag = 1").fetchone()
            if row:
                user = self.store._decode_row(row)
                return "user", user["user_id"]
        raise ValueError("No primary user exists; run /onboard bootstrap before lane commands")

    def _get_active_context(self, lane_id: str, *, conn: Any) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT * FROM lane_active_contexts
            WHERE lane_id = ? AND status = 'active'
            ORDER BY session_generation DESC, created_at DESC
            LIMIT 1
            """,
            (lane_id,),
        ).fetchone()
        return self.store._decode_row(row) if row else None

    def _create_active_context(
        self,
        lane_id: str,
        session_generation: int,
        actor_type: str,
        actor_ref: str,
        *,
        runtime_state: dict[str, Any] | None = None,
        conn: Any,
    ) -> dict[str, Any]:
        return self.store.insert(
            "lane_active_contexts",
            {
                "active_context_id": new_id("actx"),
                "lane_id": lane_id,
                "session_generation": session_generation,
                "context_json": {
                    "lifecycle_layer": "short_term_active_context",
                    "items": [],
                    "item_count": 0,
                    "retention_default": "ephemeral",
                },
                "runtime_state_json": runtime_state or {"initialized_by": "ensure_lane"},
                "source_refs_json": [f"conversation_lane:{lane_id}"],
                "status": "active",
            },
            conn=conn,
            emit_event=False,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )

    def _partition_checkpoint_items(self, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        durable_kinds = {"decision", "fact", "preference", "question", "open_question", "commitment", "summary"}
        durable_intents = {"durable_signal", "checkpoint", "mid_term", "long_term_candidate"}
        preserved = []
        dropped = []
        for item in items:
            if item.get("retention_intent") in durable_intents or item.get("kind") in durable_kinds:
                preserved.append(item)
            else:
                dropped.append(item)
        return preserved, dropped

    def _checkpoint_payload(
        self,
        command: str,
        lane: dict[str, Any],
        active: dict[str, Any],
        preserved: list[dict[str, Any]],
        dropped: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "bounded_version": "v1-feature4",
            "lifecycle_layer": "mid_term_checkpoint",
            "reset_command": command,
            "created_at": _now(),
            "lane": {
                "lane_id": lane["lane_id"],
                "lane_key": lane["lane_key"],
                "role": lane["role"],
                "owner_scope_type": lane["owner_scope_type"],
                "owner_scope_ref": lane["owner_scope_ref"],
            },
            "source_active_context_id": active["active_context_id"],
            "preserved_signal": [
                {
                    "item_id": item["item_id"],
                    "kind": item["kind"],
                    "text": item["text"],
                    "source_ref": item.get("source_ref"),
                    "retention_intent": item.get("retention_intent"),
                }
                for item in preserved
            ],
            "dropped_ephemeral_count": len(dropped),
            "confidence_state": "scaffolded_checkpoint_summary",
            "conflict_state": "not_evaluated_in_feature4",
            "supersession_state": "not_evaluated_in_feature4",
            "promotion_status": "not_promoted",
            "wiki_candidate_status": "not_emitted",
            "canonicality_classification": "derived",
            "summary": self._checkpoint_summary(command, preserved, dropped),
        }

    def _checkpoint_summary(self, command: str, preserved: list[dict[str, Any]], dropped: list[dict[str, Any]]) -> str:
        if not preserved:
            return f"{command} checkpoint captured no durable short-term signal; {len(dropped)} ephemeral items were dropped."
        lines = [f"{command} checkpoint preserved {len(preserved)} durable signal item(s)."]
        for item in preserved:
            lines.append(f"- {item['kind']}: {item['text']}")
        lines.append(f"Dropped ephemeral item count: {len(dropped)}.")
        return "\n".join(lines)

    def _authority_object_type(self, scope_type: str) -> str:
        if scope_type == "user":
            return "user"
        if scope_type == "shared_context":
            return "shared_context"
        if scope_type == "project":
            return "project"
        if scope_type == "agent":
            return "agent"
        raise ValueError(f"Unsupported memory scope_type: {scope_type}")

    def _read_content(self, content_ref: str) -> str:
        parsed = urlparse(content_ref)
        if parsed.scheme != "file":
            return ""
        path = Path(parsed.path)
        root = self.store.artifact_root.resolve()
        resolved = path.resolve()
        if not str(resolved).startswith(str(root)):
            raise ValueError("Memory content_ref must stay under artifact root")
        return resolved.read_text(encoding="utf-8")

    def _snippet(self, body: str, query_terms: list[str]) -> str:
        lower = body.lower()
        first_index = min((lower.find(term) for term in query_terms if term in lower), default=0)
        start = max(first_index - 48, 0)
        end = min(first_index + 180, len(body))
        return body[start:end].replace("\n", " ").strip()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
