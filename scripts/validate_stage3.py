#!/usr/bin/env python3
"""Run Stage 3 commitment and task-engine validation flows."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import AgentFirstStore, GovernedAction, PolicyEngine, TaskEngine


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-stage3-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        admin = store.bootstrap_admin("Stage 3 Primary", "America/New_York")
        user = store.create_user(
            "Stage 3 User",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=admin["user_id"],
        )
        agent = store.insert(
            "agents",
            {
                "display_name": "Stage 3 Agent",
                "owner_user_id": user["user_id"],
                "persona_profile_json": {"stage": 3},
                "capability_profile_json": {"commitment_first_task_engine": True},
            },
        )
        thread = store.insert(
            "threads",
            {
                "channel_type": "internal-validation",
                "ownership_context_type": "user",
                "ownership_context_ref": user["user_id"],
                "participants_json": [{"user_id": user["user_id"]}, {"agent_id": agent["agent_id"]}],
            },
        )
        inbound_ref = store.write_artifact(
            "messages/stage3-inbound.txt",
            "Please complete the Stage 3 task-engine proof and show me evidence.",
        )
        message = store.insert(
            "messages",
            {
                "thread_id": thread["thread_id"],
                "direction": "inbound",
                "sender_identity_json": {"user_id": user["user_id"]},
                "recipient_identities_json": [{"agent_id": agent["agent_id"]}],
                "content_ref": inbound_ref,
                "classification": "internal",
                "provenance_json": {"source": "stage3-validation"},
            },
        )

        task_engine = TaskEngine(store)
        commitment = task_engine.create_commitment(
            title="Complete Stage 3 task-engine proof",
            commitment_type="consequential",
            owner_scope_type="agent",
            owner_scope_ref=agent["agent_id"],
            origin_ref_type="message",
            origin_ref=message["message_event_id"],
            priority=2,
            next_action="Activate the commitment and create attention record",
            review_at="2026-04-21T12:00:00Z",
            completion_criteria={
                "required": [
                    "lifecycle transitions persisted",
                    "waiting and blocked remain distinct",
                    "verified proof recorded",
                ]
            },
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        active = task_engine.activate_commitment(
            commitment["commitment_id"],
            next_action="Record meaningful progress and waiting condition",
            review_at="2026-04-21T12:00:00Z",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        task_engine.record_progress_update(
            commitment["commitment_id"],
            summary="Stage 3 validation path has started.",
            state_change={"meaningful_movement": "validation fixtures created"},
            visibility="internal",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        waiting = task_engine.enter_waiting(
            commitment["commitment_id"],
            waiting_on_type="scheduled_review",
            waiting_on_ref="validation-clock",
            expected_resolution_at="2026-04-21T12:30:00Z",
            review_at="2026-04-21T12:15:00Z",
            timeout_policy_ref="stage3-validation-timeout",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        waiting_signals = task_engine.review_due_commitments(
            now="2026-04-21T12:45:00Z",
            actor_type="system",
            actor_ref="stage3-validation-review",
        )
        blocker = task_engine.open_blocker(
            commitment["commitment_id"],
            blocker_type="ambiguity",
            summary="A human decision is needed to choose the final validation evidence level.",
            evidence_refs=[waiting["waiting_condition_id"]],
            resolution_options=["accept validation script output", "request deeper manual review"],
            requires_human_decision=True,
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )

        proof_gate_rejected = False
        try:
            task_engine.complete_commitment(
                commitment["commitment_id"],
                actor_type="agent",
                actor_ref=agent["agent_id"],
            )
        except ValueError:
            proof_gate_rejected = True

        proof_ref = store.write_artifact(
            "proofs/stage3-completion-proof.txt",
            "Lifecycle, waiting, blocker, progress, escalation, and proof paths validated.",
        )
        proof = task_engine.record_completion_proof(
            commitment["commitment_id"],
            evidence_refs=[proof_ref, blocker["blocker_id"]],
            verified_by_type="system",
            verified_by_ref="stage3-validation",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        completed = task_engine.complete_commitment(
            commitment["commitment_id"],
            proof_id=proof["completion_proof_id"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )

        stale_commitment = task_engine.create_commitment(
            title="Review-driven continuation commitment",
            commitment_type="validation",
            owner_scope_type="agent",
            owner_scope_ref=agent["agent_id"],
            next_action="Continue when review is due",
            review_at="2026-04-20T10:00:00Z",
            completion_criteria={"required": ["review signal emitted"], "proof_required": False},
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        task_engine.activate_commitment(
            stale_commitment["commitment_id"],
            next_action="Continue the stale validation task",
            review_at="2026-04-20T10:00:00Z",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        with store.connect() as conn:
            attention = conn.execute(
                """
                SELECT attention_record_id FROM task_attention_records
                WHERE commitment_id = ? AND status = 'active'
                """,
                (stale_commitment["commitment_id"],),
            ).fetchone()
            assert attention is not None
            store.update(
                "task_attention_records",
                attention["attention_record_id"],
                {
                    "next_review_at": "2026-04-20T10:00:00Z",
                    "last_meaningful_activity_at": "2026-04-20T09:00:00Z",
                },
                conn=conn,
                emit_event=False,
            )
        stale_signals = task_engine.review_due_commitments(
            now="2026-04-21T12:00:00Z",
            stale_after_hours=24,
            actor_type="system",
            actor_ref="stage3-validation-review",
        )

        policy_engine = PolicyEngine(store)
        approval_commitment = task_engine.create_commitment(
            title="Approval-gated policy task",
            commitment_type="external_action",
            owner_scope_type="agent",
            owner_scope_ref=agent["agent_id"],
            next_action="Wait for policy approval before completion",
            completion_criteria={"required": ["approval decision resolved"], "proof_required": True},
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        task_engine.activate_commitment(
            approval_commitment["commitment_id"],
            next_action="Request policy approval",
            review_at="2026-04-21T13:00:00Z",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        approval_result = policy_engine.evaluate_and_record(
            GovernedAction(
                action_type="share_external",
                actor_type="agent",
                actor_ref=agent["agent_id"],
                sponsoring_user_id=user["user_id"],
                object_type="commitment",
                object_ref=approval_commitment["commitment_id"],
                destination_type="channel",
                destination_identity="unapproved-external-recipient",
                content_classification="private",
            )
        )
        approval_signals = task_engine.review_due_commitments(
            now="2026-04-21T13:30:00Z",
            actor_type="system",
            actor_ref="stage3-validation-review",
        )

        if active["status"] != "active":
            raise RuntimeError("Commitment did not activate")
        if completed["status"] != "completed":
            raise RuntimeError("Commitment did not complete")
        if not proof_gate_rejected:
            raise RuntimeError("Proof gate did not reject completion without proof")
        if waiting["status"] != "active":
            raise RuntimeError("Waiting condition was not stored distinctly")
        if blocker["status"] != "active" or not blocker["requires_human_decision"]:
            raise RuntimeError("Blocker record was not stored distinctly")

        progress_updates = [
            row
            for row in store.list_records("progress_updates", 100)
            if row["parent_ref"] == commitment["commitment_id"]
        ]
        user_visible = [
            row for row in progress_updates if "visibility:user" in row["visibility_policy_refs_json"]
        ]
        internal = [
            row for row in progress_updates if "visibility:internal" in row["visibility_policy_refs_json"]
        ]
        if not user_visible or not internal:
            raise RuntimeError("Expected both user-visible and internal progress updates")

        signals = waiting_signals + stale_signals + approval_signals
        signal_types = [signal.get("escalation_type") or signal.get("signal") for signal in signals]
        required_signal_types = {
            "waiting_condition_expired",
            "blocker_requires_human_decision",
            "review_due",
            "commitment_stale",
            "approval_gated_policy_decision_stalled",
        }
        event_rows = store.list_records("event_log", 300)
        event_signal_types = {
            row["payload_json"].get("escalation_type")
            for row in event_rows
            if row["event_type"] == "task_escalation_recorded"
        }
        observed_signal_types = set(signal_types) | event_signal_types
        missing = required_signal_types - observed_signal_types
        if missing:
            raise RuntimeError(f"Missing Stage 3 signals: {sorted(missing)}")

        print(
            json.dumps(
                {
                    "ok": True,
                    "db": str(store.db_path),
                    "artifact_root": str(store.artifact_root),
                    "commitment_lifecycle": ["captured", "active", "waiting", "blocked", "completed"],
                    "completed_commitment_id": completed["commitment_id"],
                    "waiting_condition_id": waiting["waiting_condition_id"],
                    "blocker_id": blocker["blocker_id"],
                    "completion_proof_id": proof["completion_proof_id"],
                    "proof_gate_rejected_without_proof": proof_gate_rejected,
                    "approval_policy_decision": approval_result["decision"]["decision"],
                    "approval_record_id": approval_result["approval_record"]["approval_record_id"]
                    if approval_result["approval_record"]
                    else None,
                    "signal_types": sorted(observed_signal_types),
                    "progress_update_count": len(progress_updates),
                    "user_visible_progress_count": len(user_visible),
                    "internal_progress_count": len(internal),
                    "task_escalation_event_count": len(
                        [row for row in event_rows if row["event_type"] == "task_escalation_recorded"]
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
