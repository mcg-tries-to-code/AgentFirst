"""Command line entrypoints for AgentFirst Stage 1 storage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .store import AgentFirstStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentfirst-store")
    parser.add_argument("--db", default="var/agentfirst-v0.sqlite3", help="SQLite database path")
    parser.add_argument("--artifact-root", default=None, help="Filesystem artifact root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize schema and artifact root")

    bootstrap = sub.add_parser("bootstrap-admin", help="Bootstrap or return the administrator user")
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument("--timezone", default="UTC")

    create_user = sub.add_parser("create-user", help="Create a non-primary user through the generic path")
    create_user.add_argument("--display-name", required=True)
    create_user.add_argument("--authority-tier", default="standard")
    create_user.add_argument("--timezone", default="UTC")
    create_user.add_argument("--metadata-json", default="{}")

    get = sub.add_parser("get", help="Retrieve a row by table and id")
    get.add_argument("table")
    get.add_argument("record_id")

    list_records = sub.add_parser("list", help="List rows from a table")
    list_records.add_argument("table")
    list_records.add_argument("--limit", type=int, default=25)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    store = AgentFirstStore(Path(args.db), args.artifact_root)

    if args.command == "init":
        store.initialize()
        print(json.dumps({"ok": True, "db": str(store.db_path), "artifact_root": str(store.artifact_root)}))
    elif args.command == "bootstrap-admin":
        user = store.bootstrap_admin(args.display_name, args.timezone)
        print(json.dumps(user, indent=2, sort_keys=True))
    elif args.command == "create-user":
        metadata = json.loads(args.metadata_json)
        user = store.create_user(
            display_name=args.display_name,
            authority_tier=args.authority_tier,
            default_timezone=args.timezone,
            metadata=metadata,
            actor_type="system",
            actor_ref="cli",
        )
        print(json.dumps(user, indent=2, sort_keys=True))
    elif args.command == "get":
        row = store.get_by_id(args.table, args.record_id)
        print(json.dumps(row, indent=2, sort_keys=True))
    elif args.command == "list":
        rows = store.list_records(args.table, args.limit)
        print(json.dumps(rows, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
