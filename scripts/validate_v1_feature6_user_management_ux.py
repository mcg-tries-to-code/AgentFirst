#!/usr/bin/env python3
"""Validate V1 Feature 6 bounded user-management UX."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentfirst_storage import AgentFirstStore, OperatorSurface, TrustedOperatorTUI
from agentfirst_storage.store import new_id


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def create_binding(
    store: AgentFirstStore,
    *,
    user_id: str,
    channel_type: str,
    address: str,
    state: str,
    status: str = "active",
    owner_approval_status: str = "approved",
) -> dict:
    enrollment = store.insert(
        "channel_enrollments",
        {
            "enrollment_id": new_id("enr"),
            "channel_type": channel_type,
            "address": address,
            "user_id": user_id,
            "state": state,
            "challenge_status": "verified" if state in {"challenge_verified", "enrolled"} else "issued",
            "owner_approval_status": owner_approval_status,
            "metadata_json": {"feature": "v1_feature6_user_management_ux"},
            "status": status,
        },
        actor_type="system",
        actor_ref="feature6_validation",
    )
    identity = store.insert(
        "channel_identities",
        {
            "channel_identity_id": new_id("chan"),
            "user_id": user_id,
            "channel_type": channel_type,
            "address": address,
            "enrollment_id": enrollment["enrollment_id"],
            "enrollment_state": state if state in {"enrolled", "suspended", "rebinding_required", "revoked"} else "rebinding_required",
            "binding_generation": 1,
            "metadata_json": {"feature": "v1_feature6_user_management_ux"},
            "routing_policy_refs_json": [],
            "status": status,
        },
        actor_type="system",
        actor_ref="feature6_validation",
    )
    return {"enrollment": enrollment, "identity": identity}


def audit_event_types(store: AgentFirstStore) -> set[str]:
    return {audit["event_type"] for audit in store.list_records("audit_events", 1000)}


def validate_feature6() -> dict:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature6-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()
        primary = store.bootstrap_admin("Feature 6 Primary", "America/New_York")
        tui = TrustedOperatorTUI(store)
        surface = OperatorSurface(store)

        audit_before_read = count(store, "audit_events")
        event_before_read = count(store, "event_log")
        empty_users = tui.handle_command("users")
        if empty_users.mode != "READ-ONLY" or "ADMIN SEPARATE" not in empty_users.text:
            raise RuntimeError("User list did not render as explicit read-only inspection")
        if count(store, "audit_events") != audit_before_read or count(store, "event_log") != event_before_read:
            raise RuntimeError("Read-only user list mutated audit or event state")

        create_result = tui.handle_command(
            f'admin user create --actor {primary["user_id"]} --display-name "Feature 6 Managed User" '
            "--authority-tier standard --timezone America/New_York --confirm CREATE_USER"
        )
        if create_result.mode != "ADMIN" or create_result.data.get("error"):
            raise RuntimeError(f"User creation was rejected unexpectedly: {create_result.data}")
        created_user = create_result.data["user"]
        if created_user["primary_user_flag"] or created_user["authority_tier"] != "standard":
            raise RuntimeError("Created user received elevated authority unexpectedly")
        if store.get_by_id("users", created_user["user_id"]) is None:
            raise RuntimeError("Created user was not persisted canonically")

        enrolled = create_binding(
            store,
            user_id=created_user["user_id"],
            channel_type="telegram",
            address="telegram:feature6-active",
            state="enrolled",
        )
        pending = create_binding(
            store,
            user_id=created_user["user_id"],
            channel_type="bluebubbles",
            address="imessage:feature6-pending",
            state="awaiting_owner_approval",
            owner_approval_status="requested",
        )
        store.insert(
            "authority_grants",
            {
                "grant_id": new_id("grant"),
                "grantor_user_id": primary["user_id"],
                "grantee_user_id": created_user["user_id"],
                "scope_type": "user",
                "scope_ref": primary["user_id"],
                "permissions_json": ["monitor"],
                "constraints_json": [{"feature": "v1_feature6_user_management_ux"}],
                "effective_at": "2026-04-23T00:00:00.000Z",
                "status": "active",
            },
            actor_type="user",
            actor_ref=primary["user_id"],
        )

        read_audit_before = count(store, "audit_events")
        read_event_before = count(store, "event_log")
        list_result = tui.handle_command("users")
        detail_result = tui.handle_command(f"user {created_user['user_id']}")
        if count(store, "audit_events") != read_audit_before or count(store, "event_log") != read_event_before:
            raise RuntimeError("Read-only user detail mutated audit or event state")
        user_list_row = next(user for user in list_result.data["users"] if user["user_id"] == created_user["user_id"])
        if user_list_row["identity_count"] != 2 or user_list_row["enrollment_count"] != 2:
            raise RuntimeError("User list did not show linked identity and enrollment counts")
        if "APPROVAL-NEEDED" not in user_list_row["badges"] or "DEGRADED-BINDINGS" not in user_list_row["badges"]:
            raise RuntimeError("User list did not disclose approval-needed/degraded badges")
        if detail_result.mode != "READ-ONLY":
            raise RuntimeError("User detail was not marked read-only")
        if len(detail_result.data["channel_identities"]) != 2 or len(detail_result.data["channel_enrollments"]) != 2:
            raise RuntimeError("User detail did not expose identities and enrollments")
        if not detail_result.data["authority"]["active_grants_received"]:
            raise RuntimeError("User detail did not expose authority grant summary")
        if not detail_result.data["degraded_bindings"]:
            raise RuntimeError("User detail hid degraded or approval-needed binding state")
        if pending["identity"]["channel_identity_id"] not in detail_result.text:
            raise RuntimeError("Degraded pending identity was not visible in rendered detail")

        suspend_result = tui.handle_command(
            f"admin user suspend {created_user['user_id']} --actor {primary['user_id']} --confirm SUSPEND_USER"
        )
        if suspend_result.data.get("error") or suspend_result.data["user"]["status"] != "suspended":
            raise RuntimeError(f"User suspension failed: {suspend_result.data}")
        suspended_detail = surface.user_detail(created_user["user_id"])
        if "USER-SUSPENDED" not in suspended_detail["user"]["badges"]:
            raise RuntimeError("Suspended user badge was not visible")
        if not any("user_status:suspended" in binding["reasons"] for binding in suspended_detail["degraded_bindings"]):
            raise RuntimeError("Suspended user state was not reflected in degraded binding visibility")

        reactivate_result = tui.handle_command(
            f"admin user reactivate {created_user['user_id']} --actor {primary['user_id']} --confirm REACTIVATE_USER"
        )
        if reactivate_result.data.get("error") or reactivate_result.data["user"]["status"] != "active":
            raise RuntimeError(f"User reactivation failed: {reactivate_result.data}")
        reactivated_detail = surface.user_detail(created_user["user_id"])
        if reactivated_detail["user"]["status"] != "active":
            raise RuntimeError("Reactivated user did not return to active status")

        rejected_actions = []
        missing_confirm_before = store.get_by_id("users", created_user["user_id"])["status"]
        missing_confirm = tui.handle_command(f"admin user suspend {created_user['user_id']} --actor {primary['user_id']}")
        if missing_confirm.data.get("error") != "missing_confirmation":
            raise RuntimeError("Missing confirmation was not rejected explicitly")
        if store.get_by_id("users", created_user["user_id"])["status"] != missing_confirm_before:
            raise RuntimeError("Missing-confirmation rejection mutated user state")
        rejected_actions.append("missing_confirmation")

        unauthorized_actor = store.create_user(
            display_name="Feature 6 Non Primary",
            authority_tier="standard",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        unauthorized = tui.handle_command(
            f'admin user create --actor {unauthorized_actor["user_id"]} --display-name "Unauthorized Create" '
            "--confirm CREATE_USER"
        )
        if unauthorized.data.get("error") != "admin_rejected":
            raise RuntimeError("Unauthorized actor was not rejected explicitly")
        rejected_actions.append("unauthorized_actor")

        nonexistent = tui.handle_command(
            f"admin user suspend usr_missing_feature6 --actor {primary['user_id']} --confirm SUSPEND_USER"
        )
        if nonexistent.data.get("error") != "admin_rejected":
            raise RuntimeError("Nonexistent target user was not rejected explicitly")
        rejected_actions.append("nonexistent_target")

        events = audit_event_types(store)
        required_events = {"operator_user_created", "operator_user_suspended", "operator_user_reactivated"}
        if not required_events.issubset(events):
            raise RuntimeError(f"Missing user-management audit events: {sorted(required_events - events)}")
        audit_events_written = [
            audit
            for audit in store.list_records("audit_events", 1000)
            if audit["event_type"] in required_events and audit["object_ref"] == created_user["user_id"]
        ]
        event_log_written = [
            event
            for event in store.list_records("event_log", 1000)
            if event["event_type"] in required_events and event["aggregate_id"] == created_user["user_id"]
        ]
        if len(audit_events_written) != 3 or len(event_log_written) != 3:
            raise RuntimeError("Consequential user-management actions did not write matching audit/event evidence")

        enrolled_after = store.get_by_id("channel_enrollments", enrolled["enrollment"]["enrollment_id"])
        pending_after = store.get_by_id("channel_enrollments", pending["enrollment"]["enrollment_id"])
        if enrolled_after["state"] != "enrolled" or pending_after["state"] != "awaiting_owner_approval":
            raise RuntimeError("User management actions unexpectedly changed enrollment states")

        return {
            "ok": True,
            "created_user_id": created_user["user_id"],
            "suspended_user_id": suspend_result.data["user"]["user_id"],
            "reactivated_user_id": reactivate_result.data["user"]["user_id"],
            "audit_events_written": len(audit_events_written),
            "event_log_entries_written": len(event_log_written),
            "rejected_actions": rejected_actions,
            "identity_count": user_list_row["identity_count"],
            "enrollment_count": user_list_row["enrollment_count"],
            "badges_seen": sorted(set(user_list_row["badges"] + suspended_detail["user"]["badges"])),
            "read_only_audit_preserved": True,
            "enrollment_policy_bypassed": False,
        }


def main() -> None:
    print(json.dumps(validate_feature6(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
