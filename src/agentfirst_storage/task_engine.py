"""Commitment-first task ownership engine for AgentFirst v0 Stage 3."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .store import AgentFirstStore, new_id


COMMITMENT_STATES = {
    "captured",
    "active",
    "waiting",
    "blocked",
    "delegated",
    "completed",
    "failed",
    "canceled",
}

TERMINAL_STATES = {"completed", "failed", "canceled"}

ALLOWED_TRANSITIONS = {
    "captured": {"active", "waiting", "blocked", "delegated", "canceled", "failed"},
    "active": {"waiting", "blocked", "delegated", "completed", "failed", "canceled"},
    "waiting": {"active", "blocked", "completed", "failed", "canceled"},
    "blocked": {"active", "waiting", "completed", "failed", "canceled"},
    "delegated": {"active", "waiting", "blocked", "completed", "failed", "canceled"},
    "completed": set(),
    "failed": set(),
    "canceled": set(),
}

PROOF_REQUIRED_TYPES = {"consequential", "external_action", "tool_execution", "research", "delivery"}


class TaskEngine:
    """Small explicit lifecycle layer over the canonical Stage 1 store."""

    def __init__(self, store: AgentFirstStore):
        self.store = store

    def create_commitment(
        self,
        *,
        title: str,
        commitment_type: str,
        owner_scope_type: str,
        owner_scope_ref: str,
        origin_ref_type: str | None = None,
        origin_ref: str | None = None,
        project_id: str | None = None,
        priority: int = 3,
        next_action: str | None = None,
        due_at: str | None = None,
        review_at: str | None = None,
        completion_criteria: dict[str, Any] | None = None,
        proof_required: bool | None = None,
        policy_refs: list[str] | None = None,
        actor_type: str = "system",
        actor_ref: str = "task_engine",
    ) -> dict[str, Any]:
        criteria = dict(completion_criteria or {})
        if proof_required is None:
            proof_required = bool(criteria.get("proof_required")) or commitment_type in PROOF_REQUIRED_TYPES
        criteria["proof_required"] = bool(proof_required)

        self.store.initialize()
        with self.store.connect() as conn:
            commitment = self.store.insert(
                "commitments",
                {
                    "title": title,
                    "commitment_type": commitment_type,
                    "owner_scope_type": owner_scope_type,
                    "owner_scope_ref": owner_scope_ref,
                    "origin_ref_type": origin_ref_type,
                    "origin_ref": origin_ref,
                    "project_id": project_id,
                    "status": "captured",
                    "priority": priority,
                    "next_action": next_action,
                    "due_at": due_at,
                    "review_at": review_at,
                    "completion_criteria_json": criteria,
                    "policy_refs_json": policy_refs or [],
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            audit = self._audit(
                conn,
                "commitment_created",
                actor_type,
                actor_ref,
                commitment["commitment_id"],
                f"Captured commitment: {title}",
                "captured",
                {"owner_scope_type": owner_scope_type, "owner_scope_ref": owner_scope_ref},
            )
            self.store.append_event(
                "commitment_captured",
                "commitment",
                commitment["commitment_id"],
                actor_type,
                actor_ref,
                {"status": "captured", "next_action": next_action},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return commitment

    def activate_commitment(
        self,
        commitment_id: str,
        *,
        next_action: str,
        review_at: str | None,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            commitment = self._transition(
                conn,
                commitment_id,
                "active",
                actor_type,
                actor_ref,
                reason="work started",
                updates={"next_action": next_action, "review_at": review_at},
            )
            self._open_or_update_attention(
                conn,
                commitment,
                "active",
                review_at,
                last_activity_at=self._now(),
            )
            self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                "Commitment is active.",
                {"from": "captured", "to": "active", "next_action": next_action},
                visibility="internal",
            )
            return commitment

    def enter_waiting(
        self,
        commitment_id: str,
        *,
        waiting_on_type: str,
        waiting_on_ref: str | None = None,
        expected_resolution_at: str | None = None,
        review_at: str | None = None,
        timeout_policy_ref: str | None = None,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            waiting = self.store.insert(
                "waiting_conditions",
                {
                    "commitment_id": commitment_id,
                    "waiting_on_type": waiting_on_type,
                    "waiting_on_ref": waiting_on_ref,
                    "expected_resolution_at": expected_resolution_at,
                    "review_at": review_at,
                    "timeout_policy_ref": timeout_policy_ref,
                    "status": "active",
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            current = self._require_commitment(conn, commitment_id)
            waiting_refs = list(current.get("waiting_on_json", []))
            waiting_refs.append(waiting["waiting_condition_id"])
            commitment = self._transition(
                conn,
                commitment_id,
                "waiting",
                actor_type,
                actor_ref,
                reason=f"waiting on {waiting_on_type}",
                updates={"waiting_on_json": waiting_refs, "review_at": review_at},
            )
            self._open_or_update_attention(conn, commitment, "waiting", review_at, self._now())
            self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                "Commitment is waiting on an external condition.",
                {
                    "from": current["status"],
                    "to": "waiting",
                    "waiting_condition_id": waiting["waiting_condition_id"],
                    "expected_resolution_at": expected_resolution_at,
                    "review_at": review_at,
                },
                visibility="internal",
            )
            return waiting

    def open_blocker(
        self,
        commitment_id: str,
        *,
        blocker_type: str,
        summary: str,
        evidence_refs: list[str],
        resolution_options: list[str],
        requires_human_decision: bool = False,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        if not evidence_refs:
            raise ValueError("A blocker requires evidence_refs")
        if not resolution_options:
            raise ValueError("A blocker requires at least one resolution option")

        with self.store.connect() as conn:
            current = self._require_commitment(conn, commitment_id)
            blocker = self.store.insert(
                "blocker_records",
                {
                    "commitment_id": commitment_id,
                    "blocker_type": blocker_type,
                    "summary": summary,
                    "evidence_refs_json": evidence_refs,
                    "resolution_options_json": resolution_options,
                    "requires_human_decision": 1 if requires_human_decision else 0,
                    "status": "active",
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            commitment = self._transition(
                conn,
                commitment_id,
                "blocked",
                actor_type,
                actor_ref,
                reason=f"blocked by {blocker_type}",
                updates={"blocker_state_json": {"active_blocker_id": blocker["blocker_id"], "summary": summary}},
            )
            self._open_or_update_attention(conn, commitment, "blocked", current.get("review_at"), self._now())
            self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                "Commitment is blocked by a real impediment.",
                {
                    "from": current["status"],
                    "to": "blocked",
                    "blocker_id": blocker["blocker_id"],
                    "requires_human_decision": requires_human_decision,
                },
                visibility="user" if requires_human_decision else "internal",
            )
            if requires_human_decision:
                self._escalate(
                    conn,
                    commitment_id,
                    actor_type,
                    actor_ref,
                    "blocker_requires_human_decision",
                    summary,
                    {"blocker_id": blocker["blocker_id"], "resolution_options": resolution_options},
                )
            return blocker

    def delegate_to_sub_agent(
        self,
        commitment_id: str,
        *,
        parent_agent_id: str,
        sponsor_user_id: str,
        goal: str,
        scope: dict[str, Any] | None = None,
        authority_scope: dict[str, Any] | None = None,
        input_artifacts: list[str] | None = None,
        deliverable_expectation: dict[str, Any] | None = None,
        provenance_refs: list[str] | None = None,
        review_at: str | None = None,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            current = self._require_commitment(conn, commitment_id)
            sub_agent = self.store.insert(
                "sub_agent_runs",
                {
                    "parent_agent_id": parent_agent_id,
                    "sponsor_user_id": sponsor_user_id,
                    "goal": goal,
                    "scope_json": {"commitment_id": commitment_id, **(scope or {})},
                    "authority_scope_json": authority_scope or {},
                    "input_artifacts_json": input_artifacts or [],
                    "deliverable_expectation_json": deliverable_expectation or {},
                    "provenance_refs_json": provenance_refs or [],
                    "status": "running",
                    "started_at": self._now(),
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            commitment = self._transition(
                conn,
                commitment_id,
                "delegated",
                actor_type,
                actor_ref,
                reason="delegated to sub-agent",
                updates={"review_at": review_at},
            )
            self._open_or_update_attention(conn, commitment, "delegated", review_at, self._now())
            self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                "Commitment delegated to sub-agent.",
                {
                    "from": current["status"],
                    "to": "delegated",
                    "sub_agent_run_id": sub_agent["sub_agent_run_id"],
                },
                visibility="internal",
            )
            self.store.append_event(
                "sub_agent_run_started",
                "sub_agent_run",
                sub_agent["sub_agent_run_id"],
                actor_type,
                actor_ref,
                {"commitment_id": commitment_id, "goal": goal},
                conn=conn,
            )
            return sub_agent

    def reconcile_sub_agent_result(
        self,
        sub_agent_run_id: str,
        *,
        result_summary: str,
        output_refs: list[str] | None = None,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            sub_agent = self.store.get_by_id("sub_agent_runs", sub_agent_run_id, conn=conn)
            if sub_agent is None:
                raise ValueError(f"Sub-agent run not found: {sub_agent_run_id}")
            commitment_id = sub_agent.get("scope_json", {}).get("commitment_id")
            if not commitment_id:
                raise ValueError("Sub-agent run is missing commitment scope")
            current = self._require_commitment(conn, commitment_id)
            provenance = list(sub_agent.get("provenance_refs_json", []))
            provenance.extend(output_refs or [])
            completed_run = self.store.update(
                "sub_agent_runs",
                sub_agent_run_id,
                {
                    "result_summary": result_summary,
                    "provenance_refs_json": provenance,
                    "status": "completed",
                    "ended_at": self._now(),
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            commitment = self._transition(
                conn,
                commitment_id,
                "active",
                actor_type,
                actor_ref,
                reason="sub-agent result reconciled",
            )
            self._open_or_update_attention(conn, commitment, "active", current.get("review_at"), self._now())
            self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                f"Sub-agent result reconciled: {result_summary}",
                {
                    "from": current["status"],
                    "to": "active",
                    "sub_agent_run_id": sub_agent_run_id,
                    "output_refs": output_refs or [],
                },
                visibility="internal",
            )
            self.store.append_event(
                "sub_agent_run_reconciled",
                "sub_agent_run",
                sub_agent_run_id,
                actor_type,
                actor_ref,
                {"commitment_id": commitment_id, "output_refs": output_refs or []},
                conn=conn,
            )
            return completed_run

    def record_progress_update(
        self,
        commitment_id: str,
        *,
        summary: str,
        state_change: dict[str, Any],
        visibility: str = "internal",
        detail_ref: str | None = None,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            self._require_commitment(conn, commitment_id)
            return self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                summary,
                state_change,
                visibility=visibility,
                detail_ref=detail_ref,
            )

    def record_completion_proof(
        self,
        commitment_id: str,
        *,
        evidence_refs: list[str],
        verified_by_type: str,
        verified_by_ref: str,
        status: str = "verified",
        actor_type: str = "system",
        actor_ref: str = "task_engine",
    ) -> dict[str, Any]:
        if not evidence_refs:
            raise ValueError("Completion proof requires evidence_refs")
        if status not in {"drafted", "verified", "rejected"}:
            raise ValueError("Unsupported completion proof status")

        with self.store.connect() as conn:
            commitment = self._require_commitment(conn, commitment_id)
            verified_at = self._now() if status == "verified" else None
            proof = self.store.insert(
                "completion_proofs",
                {
                    "commitment_id": commitment_id,
                    "completion_criteria_snapshot_json": commitment["completion_criteria_json"],
                    "evidence_refs_json": evidence_refs,
                    "verified_by_type": verified_by_type,
                    "verified_by_ref": verified_by_ref,
                    "verified_at": verified_at,
                    "status": status,
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            self.store.append_event(
                "completion_proof_recorded",
                "commitment",
                commitment_id,
                actor_type,
                actor_ref,
                {"completion_proof_id": proof["completion_proof_id"], "status": status},
                conn=conn,
            )
            return proof

    def complete_commitment(
        self,
        commitment_id: str,
        *,
        proof_id: str | None = None,
        evidence_refs: list[str] | None = None,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            commitment = self._require_commitment(conn, commitment_id)
            proof_required = bool(commitment.get("completion_criteria_json", {}).get("proof_required"))
            proof = None
            if proof_id:
                proof = self.store.get_by_id("completion_proofs", proof_id, conn=conn)
                if proof is None or proof["commitment_id"] != commitment_id:
                    raise ValueError("completion proof does not belong to commitment")
            elif evidence_refs:
                proof = self.store.insert(
                    "completion_proofs",
                    {
                        "commitment_id": commitment_id,
                        "completion_criteria_snapshot_json": commitment["completion_criteria_json"],
                        "evidence_refs_json": evidence_refs,
                        "verified_by_type": actor_type if actor_type in {"user", "agent", "system"} else "system",
                        "verified_by_ref": actor_ref,
                        "verified_at": self._now(),
                        "status": "verified",
                    },
                    conn=conn,
                    emit_event=False,
                    actor_type=actor_type,
                    actor_ref=actor_ref,
                )
            elif proof_required:
                raise ValueError("Consequential commitments require verified completion proof")

            if proof_required and (proof is None or proof["status"] != "verified"):
                raise ValueError("Consequential commitments require verified completion proof")

            completed = self._transition(
                conn,
                commitment_id,
                "completed",
                actor_type,
                actor_ref,
                reason="completion criteria satisfied",
            )
            self._close_attention(conn, commitment_id, "closed")
            self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                "Commitment completed with proof.",
                {
                    "from": commitment["status"],
                    "to": "completed",
                    "completion_proof_id": proof["completion_proof_id"] if proof else None,
                },
                visibility="user",
            )
            return completed

    def mark_failed_or_canceled(
        self,
        commitment_id: str,
        *,
        final_state: str,
        reason: str,
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        if final_state not in {"failed", "canceled"}:
            raise ValueError("final_state must be failed or canceled")
        with self.store.connect() as conn:
            current = self._require_commitment(conn, commitment_id)
            updated = self._transition(conn, commitment_id, final_state, actor_type, actor_ref, reason=reason)
            self._close_attention(conn, commitment_id, final_state)
            self._progress(
                conn,
                commitment_id,
                actor_type,
                actor_ref,
                f"Commitment {final_state}.",
                {"from": current["status"], "to": final_state, "reason": reason},
                visibility="user",
            )
            return updated

    def review_due_commitments(
        self,
        *,
        now: str | None = None,
        stale_after_hours: int = 24,
        actor_type: str = "system",
        actor_ref: str = "task_review",
    ) -> list[dict[str, Any]]:
        now_text = now or self._now()
        now_dt = self._parse_time(now_text)
        signals: list[dict[str, Any]] = []

        with self.store.connect() as conn:
            attention_rows = conn.execute(
                """
                SELECT * FROM task_attention_records
                WHERE status = 'active'
                ORDER BY next_review_at, updated_at
                """
            ).fetchall()
            for row in attention_rows:
                attention = self.store._decode_row(row)
                commitment = self._require_commitment(conn, attention["commitment_id"])
                if commitment["status"] in TERMINAL_STATES:
                    continue

                next_review = attention.get("next_review_at")
                last_activity = attention.get("last_meaningful_activity_at")
                due = bool(next_review and self._parse_time(next_review) <= now_dt)
                stale = bool(
                    last_activity
                    and self._parse_time(last_activity) + timedelta(hours=stale_after_hours) <= now_dt
                )

                if due and commitment["status"] == "active":
                    signal = self._needs_review(conn, commitment, attention, actor_type, actor_ref)
                    signals.append(signal)
                if stale and commitment["status"] in {"active", "delegated"}:
                    signal = self._escalate(
                        conn,
                        commitment["commitment_id"],
                        actor_type,
                        actor_ref,
                        "commitment_stale",
                        "Commitment has exceeded the staleness threshold without meaningful activity.",
                        {
                            "attention_record_id": attention["attention_record_id"],
                            "last_meaningful_activity_at": last_activity,
                            "stale_after_hours": stale_after_hours,
                        },
                    )
                    signals.append(signal)

            waiting_rows = conn.execute(
                """
                SELECT * FROM waiting_conditions
                WHERE status = 'active'
                  AND (
                    (review_at IS NOT NULL AND review_at <= ?)
                    OR (expected_resolution_at IS NOT NULL AND expected_resolution_at <= ?)
                  )
                ORDER BY review_at, expected_resolution_at
                """,
                (now_text, now_text),
            ).fetchall()
            for row in waiting_rows:
                waiting = self.store._decode_row(row)
                signal = self._escalate(
                    conn,
                    waiting["commitment_id"],
                    actor_type,
                    actor_ref,
                    "waiting_condition_expired",
                    "Waiting condition has reached its review or expected resolution horizon.",
                    {
                        "waiting_condition_id": waiting["waiting_condition_id"],
                        "waiting_on_type": waiting["waiting_on_type"],
                        "review_at": waiting.get("review_at"),
                        "expected_resolution_at": waiting.get("expected_resolution_at"),
                    },
                )
                signals.append(signal)

            approval_rows = conn.execute(
                """
                SELECT ar.*, pd.object_type, pd.object_ref, pd.policy_decision_id
                FROM approval_records ar
                JOIN policy_decisions pd ON pd.policy_decision_id = ar.policy_decision_id
                WHERE ar.status = 'requested'
                  AND pd.object_type = 'commitment'
                ORDER BY ar.requested_at
                """
            ).fetchall()
            for row in approval_rows:
                approval = self.store._decode_row(row)
                signal = self._escalate(
                    conn,
                    approval["object_ref"],
                    actor_type,
                    actor_ref,
                    "approval_gated_policy_decision_stalled",
                    "Policy approval is still required before the commitment can finish.",
                    {
                        "approval_record_id": approval["approval_record_id"],
                        "policy_decision_id": approval["policy_decision_id"],
                        "requested_at": approval["requested_at"],
                    },
                )
                signals.append(signal)

        return signals

    def _transition(
        self,
        conn: Any,
        commitment_id: str,
        target_state: str,
        actor_type: str,
        actor_ref: str,
        *,
        reason: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if target_state not in COMMITMENT_STATES:
            raise ValueError(f"Unsupported commitment state: {target_state}")
        current = self._require_commitment(conn, commitment_id)
        source_state = current["status"]
        if target_state not in ALLOWED_TRANSITIONS[source_state]:
            raise ValueError(f"Invalid commitment transition: {source_state} -> {target_state}")

        values = {"status": target_state, "updated_at": self._now(), **(updates or {})}
        updated = self.store.update(
            "commitments",
            commitment_id,
            values,
            conn=conn,
            emit_event=False,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        audit = self._audit(
            conn,
            "commitment_transitioned",
            actor_type,
            actor_ref,
            commitment_id,
            f"Commitment transitioned {source_state} -> {target_state}: {reason}",
            target_state,
            {"from": source_state, "to": target_state, "reason": reason},
        )
        self.store.append_event(
            "commitment_transitioned",
            "commitment",
            commitment_id,
            actor_type,
            actor_ref,
            {"from": source_state, "to": target_state, "reason": reason},
            audit_event_id=audit["audit_event_id"],
            conn=conn,
        )
        return updated

    def _open_or_update_attention(
        self,
        conn: Any,
        commitment: dict[str, Any],
        attention_state: str,
        next_review_at: str | None,
        last_activity_at: str | None,
    ) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT * FROM task_attention_records
            WHERE commitment_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (commitment["commitment_id"],),
        ).fetchone()
        values = {
            "current_owner_type": commitment["owner_scope_type"],
            "current_owner_ref": commitment["owner_scope_ref"],
            "attention_state": attention_state,
            "next_review_at": next_review_at,
            "last_meaningful_activity_at": last_activity_at,
            "updated_at": self._now(),
        }
        if row:
            attention = self.store._decode_row(row)
            return self.store.update(
                "task_attention_records",
                attention["attention_record_id"],
                values,
                conn=conn,
                emit_event=False,
            )
        return self.store.insert(
            "task_attention_records",
            {
                "commitment_id": commitment["commitment_id"],
                **values,
                "urgency_score": self._urgency_score(commitment),
                "staleness_score": 0,
                "escalation_state": "none",
                "status": "active",
            },
            conn=conn,
            emit_event=False,
        )

    def _close_attention(self, conn: Any, commitment_id: str, state: str) -> None:
        rows = conn.execute(
            "SELECT attention_record_id FROM task_attention_records WHERE commitment_id = ? AND status = 'active'",
            (commitment_id,),
        ).fetchall()
        for row in rows:
            self.store.update(
                "task_attention_records",
                row["attention_record_id"],
                {"attention_state": state, "status": "closed", "updated_at": self._now()},
                conn=conn,
                emit_event=False,
            )

    def _progress(
        self,
        conn: Any,
        commitment_id: str,
        actor_type: str,
        actor_ref: str,
        summary: str,
        state_change: dict[str, Any],
        *,
        visibility: str,
        detail_ref: str | None = None,
    ) -> dict[str, Any]:
        if visibility not in {"internal", "user"}:
            raise ValueError("visibility must be internal or user")
        author = {"author_user_id": actor_ref} if actor_type == "user" else {"author_agent_id": actor_ref}
        if actor_type not in {"user", "agent"}:
            author = {"author_agent_id": self._system_agent(conn)}
        progress = self.store.insert(
            "progress_updates",
            {
                "parent_type": "commitment",
                "parent_ref": commitment_id,
                **author,
                "summary": summary,
                "detail_ref": detail_ref,
                "state_change_json": state_change,
                "visibility_policy_refs_json": [f"visibility:{visibility}"],
                "status": "posted",
            },
            conn=conn,
            emit_event=False,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        self.store.append_event(
            "progress_update_recorded",
            "commitment",
            commitment_id,
            actor_type,
            actor_ref,
            {"progress_update_id": progress["progress_update_id"], "visibility": visibility},
            conn=conn,
        )
        self._touch_attention(conn, commitment_id)
        return progress

    def _needs_review(
        self,
        conn: Any,
        commitment: dict[str, Any],
        attention: dict[str, Any],
        actor_type: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        self.store.update(
            "task_attention_records",
            attention["attention_record_id"],
            {"attention_state": "needs_review", "updated_at": self._now()},
            conn=conn,
            emit_event=False,
        )
        self._progress(
            conn,
            commitment["commitment_id"],
            actor_type,
            actor_ref,
            "Commitment review is due for continuation.",
            {
                "signal": "review_due",
                "attention_record_id": attention["attention_record_id"],
                "next_action": commitment.get("next_action"),
            },
            visibility="internal",
        )
        self.store.append_event(
            "commitment_review_due",
            "commitment",
            commitment["commitment_id"],
            actor_type,
            actor_ref,
            {"attention_record_id": attention["attention_record_id"]},
            conn=conn,
        )
        return {"signal": "review_due", "commitment_id": commitment["commitment_id"]}

    def _escalate(
        self,
        conn: Any,
        commitment_id: str,
        actor_type: str,
        actor_ref: str,
        escalation_type: str,
        summary: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        audit = self._audit(
            conn,
            "task_escalation",
            actor_type,
            actor_ref,
            commitment_id,
            summary,
            escalation_type,
            {"escalation_type": escalation_type, **metadata},
        )
        self._set_attention_escalated(conn, commitment_id, escalation_type)
        progress = self._progress(
            conn,
            commitment_id,
            actor_type,
            actor_ref,
            summary,
            {"signal": "escalation", "escalation_type": escalation_type, **metadata},
            visibility="user",
        )
        self.store.append_event(
            "task_escalation_recorded",
            "commitment",
            commitment_id,
            actor_type,
            actor_ref,
            {
                "escalation_type": escalation_type,
                "progress_update_id": progress["progress_update_id"],
                **metadata,
            },
            audit_event_id=audit["audit_event_id"],
            conn=conn,
        )
        return {
            "signal": "escalation",
            "escalation_type": escalation_type,
            "commitment_id": commitment_id,
            "audit_event_id": audit["audit_event_id"],
            "progress_update_id": progress["progress_update_id"],
        }

    def _set_attention_escalated(self, conn: Any, commitment_id: str, escalation_type: str) -> None:
        rows = conn.execute(
            "SELECT attention_record_id FROM task_attention_records WHERE commitment_id = ? AND status = 'active'",
            (commitment_id,),
        ).fetchall()
        for row in rows:
            self.store.update(
                "task_attention_records",
                row["attention_record_id"],
                {
                    "attention_state": "escalated",
                    "escalation_state": escalation_type,
                    "updated_at": self._now(),
                },
                conn=conn,
                emit_event=False,
            )

    def _touch_attention(self, conn: Any, commitment_id: str) -> None:
        rows = conn.execute(
            "SELECT attention_record_id FROM task_attention_records WHERE commitment_id = ? AND status = 'active'",
            (commitment_id,),
        ).fetchall()
        for row in rows:
            self.store.update(
                "task_attention_records",
                row["attention_record_id"],
                {"last_meaningful_activity_at": self._now(), "updated_at": self._now()},
                conn=conn,
                emit_event=False,
            )

    def _audit(
        self,
        conn: Any,
        event_type: str,
        actor_type: str,
        actor_ref: str,
        commitment_id: str,
        summary: str,
        outcome: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.insert(
            "audit_events",
            {
                "audit_event_id": new_id("aud"),
                "event_type": event_type,
                "actor_type": actor_type,
                "actor_ref": actor_ref,
                "object_type": "commitment",
                "object_ref": commitment_id,
                "action_summary": summary,
                "outcome": outcome,
                "metadata_json": metadata,
            },
            conn=conn,
            emit_event=False,
        )

    def _require_commitment(self, conn: Any, commitment_id: str) -> dict[str, Any]:
        commitment = self.store.get_by_id("commitments", commitment_id, conn=conn)
        if commitment is None:
            raise ValueError(f"Commitment not found: {commitment_id}")
        return commitment

    def _system_agent(self, conn: Any) -> str:
        row = conn.execute(
            """
            SELECT agent_id FROM agents
            WHERE display_name = 'AgentFirst System Task Engine'
            ORDER BY created_at
            LIMIT 1
            """
        ).fetchone()
        if row:
            return row["agent_id"]
        agent = self.store.insert(
            "agents",
            {
                "display_name": "AgentFirst System Task Engine",
                "shared_context_id": self._system_shared_context(conn),
                "persona_profile_json": {"role": "task-engine-system-author"},
                "capability_profile_json": {"system_progress_author": True},
            },
            conn=conn,
            emit_event=False,
        )
        return agent["agent_id"]

    def _system_shared_context(self, conn: Any) -> str:
        row = conn.execute(
            """
            SELECT shared_context_id FROM shared_contexts
            WHERE name = 'AgentFirst System'
            ORDER BY created_at
            LIMIT 1
            """
        ).fetchone()
        if row:
            return row["shared_context_id"]
        context = self.store.insert(
            "shared_contexts",
            {
                "name": "AgentFirst System",
                "context_type": "other",
                "visibility_model": "system",
                "status": "active",
            },
            conn=conn,
            emit_event=False,
        )
        return context["shared_context_id"]

    def _urgency_score(self, commitment: dict[str, Any]) -> float:
        priority = int(commitment.get("priority") or 3)
        return max(0.0, min(1.0, (6 - priority) / 5))

    def _parse_time(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _now(self) -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
