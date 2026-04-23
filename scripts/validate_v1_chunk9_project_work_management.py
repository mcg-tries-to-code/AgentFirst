#!/usr/bin/env python3
"""Validate V1 Chunk 9 project and work-management expansion."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import AgentFirstStore, GovernedAction, PolicyEngine, ProjectWorkService
from agentfirst_storage.store import new_id


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk9-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 9 Primary", "America/New_York")
        owner = store.create_user(
            display_name="Morgan Project Owner",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        contributor = store.create_user(
            display_name="Riley Project Contributor",
            authority_tier="standard",
            default_timezone="America/Chicago",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        outsider = store.create_user(
            display_name="Casey Project Outsider",
            authority_tier="standard",
            default_timezone="America/Denver",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        agent = store.insert(
            "agents",
            {
                "agent_id": new_id("agt"),
                "display_name": "Project Work Agent",
                "owner_user_id": owner["user_id"],
                "persona_profile_json": {"purpose": "chunk9 validation"},
                "capability_profile_json": {},
                "tool_policy_bindings_json": [],
                "memory_bindings_json": [],
                "model_routing_policy_json": {},
                "status": "active",
            },
            actor_type="user",
            actor_ref=owner["user_id"],
        )
        project_policy = store.insert(
            "policies",
            {
                "policy_id": new_id("pol"),
                "policy_type": "project",
                "owner_user_id": owner["user_id"],
                "priority": 20,
                "rules_json": [
                    {
                        "action": "export",
                        "classification_floor": "internal",
                        "decision": "deny",
                        "rationale": "Chunk 9 project artifacts cannot be exported during validation",
                    }
                ],
                "targets_json": ["project", "artifact", "commitment"],
                "status": "active",
            },
            actor_type="user",
            actor_ref=owner["user_id"],
        )
        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "external_workspace",
                "destination_identity": "public-reporting",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
            actor_type="system",
            actor_ref="v1_chunk9_validation",
        )

        work = ProjectWorkService(store)
        description_ref = store.write_artifact(
            "projects/chunk9/project-brief.md",
            "Chunk 9 project validates participants, milestones, artifacts, commitments, policy, and audit.",
        )
        project = work.create_project(
            name="Chunk 9 Operational Project",
            owner_scope_type="user",
            owner_scope_ref=owner["user_id"],
            actor_user_id=owner["user_id"],
            description_ref=description_ref,
            participants=[
                {
                    "subject_type": "user",
                    "subject_ref": contributor["user_id"],
                    "role": "contributor",
                    "permissions": ["read", "monitor", "intervene"],
                },
                {
                    "subject_type": "agent",
                    "subject_ref": agent["agent_id"],
                    "role": "agent",
                    "permissions": ["read", "monitor", "intervene"],
                },
            ],
            goals=["Prove project-centered work is authority-aware and audit-linked."],
            milestones=[
                {
                    "title": "Validation scenario assembled",
                    "status": "active",
                    "due_at": "2026-04-30T17:00:00Z",
                }
            ],
            policy_refs=[project_policy["policy_id"]],
        )
        if project["policy_refs_json"] != [project_policy["policy_id"]]:
            raise RuntimeError("Project did not retain attached policy refs")
        if len(project["participants_json"]) != 3:
            raise RuntimeError("Project did not retain owner, contributor, and agent participants")
        if not any(item["subject_ref"] == contributor["user_id"] for item in project["participants_json"]):
            raise RuntimeError("Project contributor participant was not recorded")

        source_ref = store.write_artifact(
            "projects/chunk9/requirements.md",
            "Artifact linked to the Chunk 9 operational project.",
        )
        artifact = store.insert(
            "artifacts",
            {
                "artifact_id": new_id("art"),
                "name": "Chunk 9 Requirements Brief",
                "artifact_type": "document",
                "storage_ref": source_ref,
                "owner_scope_type": "user",
                "owner_scope_ref": owner["user_id"],
                "source_refs_json": [description_ref],
                "project_refs_json": [],
                "classification": "internal",
                "provenance_json": {"created_for": "v1-chunk9-validation"},
                "status": "created",
            },
            actor_type="user",
            actor_ref=owner["user_id"],
        )
        linked_artifact = work.link_artifact(
            project["project_id"],
            artifact["artifact_id"],
            actor_user_id=owner["user_id"],
            link_reason="requirements source for validation milestone",
        )
        if project["project_id"] not in linked_artifact["project_refs_json"]:
            raise RuntimeError("Artifact was not linked back to the project")
        if not linked_artifact["provenance_json"].get("project_links"):
            raise RuntimeError("Artifact project linkage lost provenance")

        commitment = work.create_project_commitment(
            project["project_id"],
            title="Complete Chunk 9 project scenario validation",
            commitment_type="delivery",
            actor_user_id=contributor["user_id"],
            next_action="Run validation and inspect audit linkage",
            due_at="2026-04-30T17:00:00Z",
            review_at="2026-04-25T15:00:00Z",
            completion_criteria={
                "proof_required": True,
                "artifact_id": linked_artifact["artifact_id"],
                "scenario": "participants-artifacts-commitments-policy",
            },
        )
        if commitment["owner_scope_type"] != "project" or commitment["owner_scope_ref"] != project["project_id"]:
            raise RuntimeError("Project commitment is not project-owned")
        if commitment["project_id"] != project["project_id"]:
            raise RuntimeError("Commitment did not retain project_id linkage")
        if project_policy["policy_id"] not in commitment["policy_refs_json"]:
            raise RuntimeError("Project policy refs were not inherited by project commitment")

        milestone = work.add_milestone(
            project["project_id"],
            title="Commitment and artifact linked",
            actor_user_id=contributor["user_id"],
            artifact_refs=[linked_artifact["artifact_id"]],
            commitment_refs=[commitment["commitment_id"]],
            status="active",
        )
        if commitment["commitment_id"] not in milestone["commitment_refs"]:
            raise RuntimeError("Milestone did not retain commitment linkage")
        if linked_artifact["artifact_id"] not in milestone["artifact_refs"]:
            raise RuntimeError("Milestone did not retain artifact linkage")

        bundle = work.get_project_work_bundle(project["project_id"], actor_user_id=contributor["user_id"])
        if bundle["project"]["project_id"] != project["project_id"]:
            raise RuntimeError("Participant could not read the project work bundle")
        if len(bundle["artifacts"]) != 1 or bundle["artifacts"][0]["artifact_id"] != linked_artifact["artifact_id"]:
            raise RuntimeError("Project bundle did not include linked artifact")
        if len(bundle["commitments"]) != 1 or bundle["commitments"][0]["commitment_id"] != commitment["commitment_id"]:
            raise RuntimeError("Project bundle did not include project commitment")
        if not bundle["authority_policy_decision_id"]:
            raise RuntimeError("Project bundle read was not authority-linked")

        outsider_denied = False
        try:
            work.get_project_work_bundle(project["project_id"], actor_user_id=outsider["user_id"])
        except PermissionError:
            outsider_denied = True
        if not outsider_denied:
            raise RuntimeError("Nonparticipant project read was not denied")

        policy_result = PolicyEngine(store).evaluate_and_record(
            GovernedAction(
                action_type="export",
                actor_type="user",
                actor_ref=contributor["user_id"],
                sponsoring_user_id=contributor["user_id"],
                object_type="artifact",
                object_ref=linked_artifact["artifact_id"],
                destination_type="external_workspace",
                destination_identity="public-reporting",
                content_classification="internal",
                metadata={"project_id": project["project_id"]},
            )
        )
        policy_decision = policy_result["decision"]
        if policy_decision["decision"] != "deny":
            raise RuntimeError("Project-attached policy did not govern artifact export")
        if project_policy["policy_id"] not in policy_decision["applicable_policy_refs_json"]:
            raise RuntimeError("Project-attached policy ref was not recorded on the policy decision")

        audits = store.list_records("audit_events", 1000)
        expected_project_audits = {
            "project_created",
            "project_artifact_linked",
            "project_commitment_created",
            "project_milestone_added",
        }
        project_audit_types = {
            audit["event_type"] for audit in audits if audit["object_type"] == "project" and audit["object_ref"] == project["project_id"]
        }
        missing = expected_project_audits - project_audit_types
        if missing:
            raise RuntimeError(f"Missing project audit event(s): {sorted(missing)}")
        authority_audits = [audit for audit in audits if audit["event_type"] == "authority_evaluated"]
        policy_audits = [audit for audit in audits if audit["event_type"] == "policy_evaluated"]
        if len(authority_audits) < 4:
            raise RuntimeError("Project work scenario did not record enough authority audits")
        if not policy_audits:
            raise RuntimeError("Project work scenario did not record policy audit")

        output = {
            "ok": True,
            "project": {
                "project_id": project["project_id"],
                "owner_scope": f"{project['owner_scope_type']}:{project['owner_scope_ref']}",
                "participant_count": len(project["participants_json"]),
                "initial_milestone_count": len(project["milestones_json"]),
                "policy_refs": project["policy_refs_json"],
            },
            "linked_artifact": {
                "artifact_id": linked_artifact["artifact_id"],
                "project_refs": linked_artifact["project_refs_json"],
                "provenance": linked_artifact["provenance_json"],
            },
            "project_commitment": {
                "commitment_id": commitment["commitment_id"],
                "owner_scope": f"{commitment['owner_scope_type']}:{commitment['owner_scope_ref']}",
                "project_id": commitment["project_id"],
                "policy_refs": commitment["policy_refs_json"],
            },
            "milestone": {
                "milestone_id": milestone["milestone_id"],
                "artifact_refs": milestone["artifact_refs"],
                "commitment_refs": milestone["commitment_refs"],
            },
            "authority": {
                "participant_bundle_read_decision_id": bundle["authority_policy_decision_id"],
                "outsider_denied": outsider_denied,
                "authority_audit_count": len(authority_audits),
            },
            "policy": {
                "decision_id": policy_decision["policy_decision_id"],
                "decision": policy_decision["decision"],
                "applicable_policy_refs": policy_decision["applicable_policy_refs_json"],
            },
            "audit": {
                "project_audit_types": sorted(project_audit_types),
                "policy_audit_count": len(policy_audits),
                "policy_decision_count": count(store, "policy_decisions"),
                "event_log_count": len(store.list_records("event_log", 1000)),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
