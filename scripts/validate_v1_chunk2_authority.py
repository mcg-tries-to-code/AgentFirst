#!/usr/bin/env python3
"""Validate V1 Chunk 2 multi-user authority and supervisory isolation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import AgentFirstStore, AuthorityEngine, AuthorityRequest


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk2-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()
        authority = AuthorityEngine(store)

        primary = store.bootstrap_admin("V1 Primary User", "America/New_York")
        users = [primary]
        for index in range(2, 11):
            users.append(
                store.create_user(
                    display_name=f"V1 User {index}",
                    authority_tier="standard",
                    default_timezone="America/New_York",
                    actor_type="user",
                    actor_ref=primary["user_id"],
                )
            )
        if count(store, "users") != 10:
            raise RuntimeError("Validation did not create exactly ten canonical users")

        supervisor = users[1]
        supervised = users[2]
        outsider = users[3]
        context_member = users[4]

        supervised_channel = store.insert(
            "channel_identities",
            {
                "user_id": supervised["user_id"],
                "channel_type": "telegram",
                "address": "@v1_supervised",
                "enrollment_state": "enrolled",
            },
        )
        outsider_channel = store.insert(
            "channel_identities",
            {
                "user_id": outsider["user_id"],
                "channel_type": "telegram",
                "address": "@v1_outsider",
                "enrollment_state": "enrolled",
            },
        )
        supervised_memory_ref = store.write_artifact(
            "memory/supervised-private.txt",
            "Private supervised-user memory.",
        )
        outsider_memory_ref = store.write_artifact(
            "memory/outsider-private.txt",
            "Private outsider memory.",
        )
        supervised_memory = store.insert(
            "memory_records",
            {
                "memory_type": "note",
                "owner_scope_type": "user",
                "owner_scope_ref": supervised["user_id"],
                "content_ref": supervised_memory_ref,
                "canonicality": "canonical",
            },
        )
        outsider_memory = store.insert(
            "memory_records",
            {
                "memory_type": "note",
                "owner_scope_type": "user",
                "owner_scope_ref": outsider["user_id"],
                "content_ref": outsider_memory_ref,
                "canonicality": "canonical",
            },
        )

        household = store.insert(
            "shared_contexts",
            {
                "name": "V1 Chunk 2 Household",
                "context_type": "household",
                "visibility_model": "shared-members",
                "status": "active",
            },
        )
        authority.add_shared_context_member(
            shared_context_id=household["shared_context_id"],
            member_user_id=primary["user_id"],
            role="administrator",
            actor_user_id=primary["user_id"],
        )
        authority.add_shared_context_member(
            shared_context_id=household["shared_context_id"],
            member_user_id=supervisor["user_id"],
            role="supervisor",
            actor_user_id=primary["user_id"],
        )
        authority.add_shared_context_member(
            shared_context_id=household["shared_context_id"],
            member_user_id=context_member["user_id"],
            role="member",
            actor_user_id=primary["user_id"],
        )
        shared_memory_ref = store.write_artifact(
            "memory/household-shared.txt",
            "Shared household memory visible only to active members.",
        )
        shared_memory = store.insert(
            "memory_records",
            {
                "memory_type": "shared_note",
                "owner_scope_type": "shared_context",
                "owner_scope_ref": household["shared_context_id"],
                "content_ref": shared_memory_ref,
                "canonicality": "canonical",
            },
        )

        grant = authority.create_supervisory_grant(
            grantor_user_id=primary["user_id"],
            grantee_user_id=supervisor["user_id"],
            target_user_id=supervised["user_id"],
            permissions=["read", "monitor"],
            constraints=[{"scope": "bounded_chunk2_validation"}],
        )

        allowed_supervision = authority.evaluate(
            AuthorityRequest(
                actor_user_id=supervisor["user_id"],
                action="read",
                object_type="memory_record",
                object_ref=supervised_memory["memory_id"],
            )
        )
        allowed_channel = authority.evaluate(
            AuthorityRequest(
                actor_user_id=supervisor["user_id"],
                action="read",
                object_type="channel_identity",
                object_ref=supervised_channel["channel_identity_id"],
            )
        )
        denied_overreach = authority.evaluate(
            AuthorityRequest(
                actor_user_id=supervisor["user_id"],
                action="read",
                object_type="memory_record",
                object_ref=outsider_memory["memory_id"],
            )
        )
        denied_channel_overreach = authority.evaluate(
            AuthorityRequest(
                actor_user_id=supervisor["user_id"],
                action="read",
                object_type="channel_identity",
                object_ref=outsider_channel["channel_identity_id"],
            )
        )
        shared_allowed = authority.evaluate(
            AuthorityRequest(
                actor_user_id=context_member["user_id"],
                action="read",
                object_type="memory_record",
                object_ref=shared_memory["memory_id"],
            )
        )
        shared_denied = authority.evaluate(
            AuthorityRequest(
                actor_user_id=outsider["user_id"],
                action="read",
                object_type="memory_record",
                object_ref=shared_memory["memory_id"],
            )
        )

        if not allowed_supervision["allowed"]:
            raise RuntimeError("Explicit supervisory grant did not allow target-user memory read")
        if not allowed_channel["allowed"]:
            raise RuntimeError("Explicit supervisory grant did not allow target-user channel read")
        if denied_overreach["allowed"]:
            raise RuntimeError("Supervisor overreached into unrelated user's private memory")
        if denied_channel_overreach["allowed"]:
            raise RuntimeError("Supervisor overreached into unrelated user's channel identity")
        if not shared_allowed["allowed"]:
            raise RuntimeError("Active shared-context member could not read shared context memory")
        if shared_denied["allowed"]:
            raise RuntimeError("Non-member could read shared context memory")

        audits = store.list_records("audit_events", 1000)
        authority_audits = [audit for audit in audits if audit["event_type"] == "authority_evaluated"]
        if len(authority_audits) < 6:
            raise RuntimeError("Authority decisions were not audit-recorded")

        output = {
            "ok": True,
            "multi_user": {
                "user_count": count(store, "users"),
                "primary_user_id": primary["user_id"],
                "ordinary_user_count": 9,
            },
            "authority_grant": {
                "grant_id": grant["grant_id"],
                "grantor_user_id": grant["grantor_user_id"],
                "grantee_user_id": grant["grantee_user_id"],
                "scope_type": grant["scope_type"],
                "scope_ref": grant["scope_ref"],
                "permissions": grant["permissions_json"],
            },
            "allowed_supervision": {
                "memory_allowed": allowed_supervision["allowed"],
                "channel_allowed": allowed_channel["allowed"],
                "matched_grant_ids": allowed_supervision["matched_grant_ids"],
            },
            "denied_overreach": {
                "memory_allowed": denied_overreach["allowed"],
                "channel_allowed": denied_channel_overreach["allowed"],
                "rationale": denied_overreach["rationale"],
            },
            "shared_context_visibility": {
                "shared_context_id": household["shared_context_id"],
                "active_member_allowed": shared_allowed["allowed"],
                "non_member_allowed": shared_denied["allowed"],
                "member_count": len(store.list_shared_context_members(household["shared_context_id"])),
            },
            "audit": {
                "authority_decision_count": len(authority_audits),
                "audit_event_count": len(audits),
            },
            "policy_decisions": count(store, "policy_decisions"),
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
