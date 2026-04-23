#!/usr/bin/env python3
"""Validate V1 Chunk 5 Google Workspace per-user connection authority."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import (
    AgentFirstStore,
    AuthorityEngine,
    GoogleWorkspaceRequest,
    GoogleWorkspaceService,
)


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk5-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 5 Primary", "America/New_York")
        alex = store.create_user(
            display_name="Alex Workspace Owner",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        blair = store.create_user(
            display_name="Blair Workspace User",
            authority_tier="standard",
            default_timezone="America/Chicago",
            actor_type="user",
            actor_ref=primary["user_id"],
        )

        authority = AuthorityEngine(store)
        google = GoogleWorkspaceService(store, authority_engine=authority)

        alex_connection = google.create_connection(
            user_id=alex["user_id"],
            google_account_email="alex.workspace@example.com",
            services=["gmail", "calendar", "contacts", "drive"],
            scopes=[
                "gmail.readonly",
                "calendar.events.readonly",
                "contacts.readonly",
                "drive.metadata.readonly",
            ],
            credential_ref="secret://google/alex-primary",
            actor_user_id=alex["user_id"],
            metadata={"validation": "v1-chunk5-primary-connection"},
        )
        alex_second_gmail = google.create_connection(
            user_id=alex["user_id"],
            google_account_email="alex.secondary@example.com",
            services=["gmail"],
            scopes=["gmail.readonly"],
            credential_ref="secret://google/alex-secondary",
            actor_user_id=alex["user_id"],
            metadata={"validation": "v1-chunk5-ambiguity-check"},
        )
        blair_connection = google.create_connection(
            user_id=blair["user_id"],
            google_account_email="blair.workspace@example.com",
            services=["gmail", "calendar", "contacts", "drive"],
            scopes=[
                "gmail.readonly",
                "calendar.events.readonly",
                "contacts.readonly",
                "drive.metadata.readonly",
            ],
            credential_ref="secret://google/blair-primary",
            actor_user_id=blair["user_id"],
            metadata={"validation": "v1-chunk5-separate-user-connection"},
        )

        operations = {
            "gmail": "list_recent_messages",
            "calendar": "list_upcoming_events",
            "contacts": "search_contacts",
            "drive": "list_recent_files",
        }
        own_account_results = {}
        for service, operation in operations.items():
            result = google.perform_action(
                GoogleWorkspaceRequest(
                    actor_user_id=alex["user_id"],
                    target_user_id=alex["user_id"],
                    service=service,
                    operation=operation,
                    google_connection_id=alex_connection["google_connection_id"],
                    input={"validation": f"own-{service}"},
                )
            )
            action = result["action"]
            provenance = action["provenance_json"]
            if action["status"] != "completed":
                raise RuntimeError(f"Own-account Google {service} action did not complete")
            if provenance.get("google_connection_user_id") != alex["user_id"]:
                raise RuntimeError(f"Google {service} action provenance lost connection owner")
            if provenance.get("google_account_email") != "alex.workspace@example.com":
                raise RuntimeError(f"Google {service} action used the wrong account")
            own_account_results[service] = {
                "action_id": action["google_workspace_action_id"],
                "google_connection_user_id": provenance["google_connection_user_id"],
                "google_account_email": provenance["google_account_email"],
                "tool_invocation_id": provenance["tool_invocation_id"],
            }

        try:
            google.perform_action(
                GoogleWorkspaceRequest(
                    actor_user_id=alex["user_id"],
                    target_user_id=alex["user_id"],
                    service="gmail",
                    operation="ambiguous_without_connection_id",
                    input={"validation": "ambiguous-account-denied"},
                )
            )
        except ValueError as exc:
            ambiguity_blocked = "Multiple matching Google connections" in str(exc)
        else:
            ambiguity_blocked = False
        if not ambiguity_blocked:
            raise RuntimeError("Google Gmail account ambiguity was not blocked")

        try:
            google.perform_action(
                GoogleWorkspaceRequest(
                    actor_user_id=blair["user_id"],
                    target_user_id=alex["user_id"],
                    service="gmail",
                    operation="read_other_user_mail_without_grant",
                    google_connection_id=alex_connection["google_connection_id"],
                    input={"validation": "blocked-cross-user"},
                )
            )
        except PermissionError:
            blocked_cross_user = True
        else:
            blocked_cross_user = False
        if not blocked_cross_user:
            raise RuntimeError("Cross-user Google access was allowed without authority grant")

        grant = authority.create_supervisory_grant(
            grantor_user_id=primary["user_id"],
            grantee_user_id=blair["user_id"],
            target_user_id=alex["user_id"],
            permissions=["read"],
            constraints=[{"scope": "v1_chunk5_google_calendar_validation"}],
        )
        granted_cross_user = google.perform_action(
            GoogleWorkspaceRequest(
                actor_user_id=blair["user_id"],
                target_user_id=alex["user_id"],
                service="calendar",
                operation="read_other_user_calendar_with_grant",
                google_connection_id=alex_connection["google_connection_id"],
                input={"validation": "allowed-cross-user-with-grant"},
            )
        )
        granted_action = granted_cross_user["action"]
        granted_provenance = granted_action["provenance_json"]
        if granted_action["status"] != "completed":
            raise RuntimeError("Granted cross-user Google access did not complete")
        if granted_provenance.get("google_connection_user_id") != alex["user_id"]:
            raise RuntimeError("Granted cross-user action did not use the target user's connection")
        if not granted_cross_user["authority_decision"]["matched_grant_ids"]:
            raise RuntimeError("Granted cross-user action did not cite the authority grant")

        blair_own_gmail = google.perform_action(
            GoogleWorkspaceRequest(
                actor_user_id=blair["user_id"],
                target_user_id=blair["user_id"],
                service="gmail",
                operation="list_blair_recent_messages",
                google_connection_id=blair_connection["google_connection_id"],
                input={"validation": "separate-user-correct-account"},
            )
        )
        if blair_own_gmail["action"]["provenance_json"].get("google_account_email") != "blair.workspace@example.com":
            raise RuntimeError("Blair's own Gmail action did not use Blair's connection")

        actions = store.list_records("google_workspace_actions", 1000)
        denied_actions = [action for action in actions if action["status"] == "authority_denied"]
        completed_actions = [action for action in actions if action["status"] == "completed"]
        audits = store.list_records("audit_events", 1000)
        authority_audits = [audit for audit in audits if audit["event_type"] == "authority_evaluated"]
        google_audits = [audit for audit in audits if audit["event_type"] == "google_workspace_action_recorded"]
        if not denied_actions:
            raise RuntimeError("Denied cross-user Google action was not recorded")
        if len(completed_actions) < 6:
            raise RuntimeError("Expected completed Google Workspace actions were not recorded")
        if not authority_audits or not google_audits:
            raise RuntimeError("Google Workspace authority/action audits were not recorded")

        output = {
            "ok": True,
            "connections": {
                "count": count(store, "google_connections"),
                "alex_primary_connection_id": alex_connection["google_connection_id"],
                "alex_secondary_connection_id": alex_second_gmail["google_connection_id"],
                "blair_connection_id": blair_connection["google_connection_id"],
            },
            "own_account_results": own_account_results,
            "blocked_cross_user": {
                "blocked": blocked_cross_user,
                "denied_action_count": len(denied_actions),
                "denied_connection_user_id": denied_actions[-1]["google_connection_user_id"],
            },
            "explicit_authority_grant": {
                "grant_id": grant["grant_id"],
                "allowed_action_id": granted_action["google_workspace_action_id"],
                "matched_grant_ids": granted_cross_user["authority_decision"]["matched_grant_ids"],
                "connection_user_id": granted_provenance["google_connection_user_id"],
            },
            "ambiguity": {
                "gmail_without_connection_id_blocked": ambiguity_blocked,
            },
            "audit": {
                "authority_decision_count": len(authority_audits),
                "google_action_audit_count": len(google_audits),
                "policy_decision_count": count(store, "policy_decisions"),
                "tool_invocation_count": count(store, "tool_invocations"),
                "google_workspace_action_count": count(store, "google_workspace_actions"),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
