"""Human-friendly command line entrypoints for AgentFirst."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from .command_surface import CommandSurfaceError, MinimalCommandSurface
from .doctor import DoctorService
from .model_execution import ModelExecutionRequest, ModelExecutionService
from .onboarding import OnboardingRequest, OnboardingSecretFile, OnboardingService
from .operator_surface import TrustedOperatorTUI
from .provider_catalog import find_provider, provider_catalog_as_dict, inspect_provider_readiness
from .secret_broker import (
    LocalEncryptedSecretVault,
    MacOSKeychainRootKeyProvider,
    OperatorPassphraseRootKeyProvider,
    SecretBroker,
)
from .store import AgentFirstStore


def _default_runtime_config() -> dict[str, str]:
    app_home = Path(os.environ.get("AGENTFIRST_HOME", "~/.agentfirst")).expanduser()
    db_path = Path(os.environ.get("AF_DB") or os.environ.get("AGENTFIRST_DB") or app_home / "agentfirst.sqlite3")
    artifact_root = Path(
        os.environ.get("AF_ARTIFACTS") or os.environ.get("AGENTFIRST_ARTIFACT_ROOT") or app_home / "artifacts"
    )
    secret_root = Path(
        os.environ.get("AF_SECRETS") or os.environ.get("AGENTFIRST_SECRET_ROOT") or app_home / "secure-secrets"
    )
    return {
        "app_home": str(app_home),
        "db": str(db_path),
        "artifact_root": str(artifact_root),
        "secret_root": str(secret_root),
    }


def build_parser() -> argparse.ArgumentParser:
    defaults = _default_runtime_config()
    parser = argparse.ArgumentParser(
        prog="agentfirst",
        description="AgentFirst, a simpler human-first local operator CLI.",
    )
    parser.add_argument("--db", default=defaults["db"], help=f"SQLite database path (default: {defaults['db']})")
    parser.add_argument(
        "--artifact-root",
        default=defaults["artifact_root"],
        help=f"Filesystem artifact root (default: {defaults['artifact_root']})",
    )
    parser.add_argument(
        "--secret-root",
        default=defaults["secret_root"],
        help=f"Encrypted secret vault root (default: {defaults['secret_root']})",
    )
    parser.add_argument(
        "--root-provider",
        choices=["operator-passphrase", "macos-keychain"],
        default="operator-passphrase",
        help="Root key provider for secret vault operations",
    )
    parser.add_argument(
        "--passphrase-env",
        default="AGENTFIRST_SECRET_PASSPHRASE",
        help="Environment variable used by operator-passphrase provider",
    )
    parser.add_argument(
        "--keychain-service",
        default="agentfirst.v1.secret-root",
        help="macOS keychain service name for root key custody",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize schema and local storage")

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

    tui = sub.add_parser("tui", help="Open the local multimode TUI")
    tui.add_argument(
        "--mode",
        choices=["operator", "chat"],
        default="operator",
        help="Initial TUI mode (default: operator)",
    )
    tui.add_argument(
        "--command",
        action="append",
        default=[],
        dest="tui_commands",
        help="Run one TUI command non-interactively; repeat for scripted validation",
    )

    onboarding = sub.add_parser("onboarding", help="Guided onboarding and bootstrap")
    onboarding_sub = onboarding.add_subparsers(dest="onboarding_command", required=False)
    onboarding_bootstrap = onboarding_sub.add_parser("bootstrap", help="Bootstrap primary operator and first-run state")
    onboarding_bootstrap.add_argument("--operator-display-name", required=True)
    onboarding_bootstrap.add_argument("--timezone", default="UTC")
    onboarding_bootstrap.add_argument(
        "--custody-mode",
        choices=["operator-passphrase", "macos-keychain"],
        default=None,
        help="Root-key custody mode to initialize and record",
    )
    onboarding_bootstrap.add_argument("--provider", required=True)
    onboarding_bootstrap.add_argument("--model", required=True)
    onboarding_bootstrap.add_argument(
        "--channel",
        action="append",
        default=[],
        metavar="CHANNEL=STATE",
        help="Record channel enablement: local, telegram, bluebubbles, google_workspace = enabled, disabled, or deferred",
    )
    onboarding_bootstrap.add_argument(
        "--secret-file",
        nargs=4,
        action="append",
        default=[],
        metavar=("HANDLE", "KIND", "INTEGRATION", "PATH"),
        help="Ingest a minimum startup secret from a trusted local file; plaintext is never printed",
    )
    onboarding_sub.add_parser("status", help="Show latest onboarding readiness without reading secret plaintext")

    doctor = sub.add_parser("doctor", help="Inspect local onboarding/bootstrap health")
    doctor.add_argument(
        "--fix",
        action="store_true",
        help="Apply only bounded mechanical fixes such as missing directories and stale metadata refresh",
    )

    command = sub.add_parser("command", help="Run the bounded V1 minimal slash-command surface")
    command.add_argument(
        "command_tokens",
        nargs=argparse.REMAINDER,
        help="Slash command and arguments, for example: /help, /status, /doctor --fix",
    )

    model = sub.add_parser("model", help="Inspect catalogs/readiness or execute a governed model query")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("catalog", help="Show the bounded point-in-time provider catalog")
    model_readiness = model_sub.add_parser("readiness", help="Show provider execution lane readiness")
    model_readiness.add_argument("--provider")
    model_execute = model_sub.add_parser("execute", help="Run a governed model execution attempt")
    model_execute.add_argument("--prompt", required=True)
    model_execute.add_argument("--purpose", default="general")
    model_execute.add_argument("--scope-type", choices=["user", "agent", "task"], default="user")
    model_execute.add_argument("--scope-ref")
    model_execute.add_argument("--actor-user-id")
    model_execute.add_argument("--sponsoring-user-id")
    model_execute.add_argument("--requesting-agent-id")
    model_execute.add_argument("--classification", default="internal")
    model_execute.add_argument("--origin-entity-ref")
    model_execute.add_argument("--lane", choices=["api", "codex_cli", "claude_code_cli", "antigravity_cli"])
    model_execute.add_argument("--max-output-tokens", type=int, default=512)

    secret = sub.add_parser("secret", help="Trusted local secret broker operations")
    secret_sub = secret.add_subparsers(dest="secret_command", required=True)

    secret_put = secret_sub.add_parser("put", help="Ingest a secret via prompt, stdin, or local file")
    secret_put.add_argument("--handle", required=True)
    secret_put.add_argument("--kind", required=True)
    secret_put.add_argument("--integration", required=True)
    secret_put.add_argument("--owner-type", default="system")
    secret_put.add_argument("--owner-ref", default="cli")
    secret_put.add_argument("--scope-type")
    secret_put.add_argument("--scope-ref")
    secret_put.add_argument("--display-hint")
    secret_put.add_argument("--stdin", action="store_true")
    secret_put.add_argument("--file")

    secret_rotate = secret_sub.add_parser("rotate", help="Rotate an existing secret from prompt, stdin, or local file")
    secret_rotate.add_argument("secret_ref")
    secret_rotate.add_argument("--stdin", action="store_true")
    secret_rotate.add_argument("--file")
    secret_rotate.add_argument("--reason", default="rotation")

    secret_list = secret_sub.add_parser("list", help="List secret metadata without revealing payloads")
    secret_list.add_argument("--all", action="store_true", dest="include_inactive")

    secret_revoke = secret_sub.add_parser("revoke", help="Revoke a secret handle")
    secret_revoke.add_argument("secret_ref")
    secret_revoke.add_argument("--reason", default="revoked")

    return parser


def build_secret_broker(args: argparse.Namespace, store: AgentFirstStore) -> SecretBroker:
    secret_root = Path(args.secret_root) if args.secret_root else store.db_path.parent / "secure-secrets"
    if args.root_provider == "macos-keychain":
        provider = MacOSKeychainRootKeyProvider(service_name=args.keychain_service)
    else:
        provider = OperatorPassphraseRootKeyProvider(passphrase_env=args.passphrase_env)
    return SecretBroker(store, LocalEncryptedSecretVault(secret_root, provider))


def parse_onboarding_channels(values: list[str]) -> dict[str, str]:
    channels: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Expected --channel CHANNEL=STATE, got: {value}")
        channel, state = value.split("=", 1)
        channels[channel.strip()] = state.strip()
    return channels


def parse_onboarding_secret_files(values: list[list[str]]) -> list[OnboardingSecretFile]:
    return [
        OnboardingSecretFile(handle=handle, kind=kind, integration=integration, path=Path(path))
        for handle, kind, integration, path in values
    ]


def read_secret_input(args: argparse.Namespace) -> str:
    if getattr(args, "stdin", False):
        data = sys.stdin.read()
        if not data:
            raise ValueError("Expected secret payload on stdin")
        return data.rstrip("\n")
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8").rstrip("\n")
    prompted = getpass.getpass("Secret value: ")
    if not prompted:
        raise ValueError("Secret value must not be empty")
    return prompted


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
    elif args.command == "tui":
        tui = TrustedOperatorTUI(store, mode=args.mode)
        if args.tui_commands:
            for result in tui.run_script(args.tui_commands):
                print(result.text)
        else:
            tui.run_interactive()
    elif args.command == "onboarding":
        if args.onboarding_command is None:
            _run_guided_onboarding(args, store)
        elif args.onboarding_command == "bootstrap":
            if args.custody_mode is not None:
                args.root_provider = args.custody_mode
            broker = build_secret_broker(args, store)
            service = OnboardingService(store, secret_broker=broker)
            result = service.bootstrap(
                OnboardingRequest(
                    operator_display_name=args.operator_display_name,
                    timezone=args.timezone,
                    custody_mode=args.root_provider.replace("-", "_"),
                    provider=args.provider,
                    model=args.model,
                    channels=parse_onboarding_channels(args.channel),
                    secret_files=parse_onboarding_secret_files(args.secret_file),
                    actor_type="system",
                    actor_ref="cli.onboarding.bootstrap",
                )
            )
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.onboarding_command == "status":
            broker = build_secret_broker(args, store)
            service = OnboardingService(store, secret_broker=broker)
            print(json.dumps(service.status(), indent=2, sort_keys=True))
    elif args.command == "doctor":
        secret_root = Path(args.secret_root) if args.secret_root else store.db_path.parent / "secure-secrets"
        service = DoctorService(store, secret_root=secret_root)
        print(json.dumps(service.run(fix=args.fix), indent=2, sort_keys=True))
    elif args.command == "command":
        secret_root = Path(args.secret_root) if args.secret_root else store.db_path.parent / "secure-secrets"
        surface = MinimalCommandSurface(
            store,
            secret_root=secret_root,
            secret_broker_factory=lambda: build_secret_broker(args, store),
        )
        try:
            result = surface.run(args.command_tokens)
        except CommandSurfaceError as exc:
            result = exc.as_result()
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        if result.exit_code:
            raise SystemExit(result.exit_code)
    elif args.command == "model":
        if args.model_command == "catalog":
            print(json.dumps(provider_catalog_as_dict(), indent=2, sort_keys=True))
        elif args.model_command == "readiness":
            print(json.dumps(inspect_provider_readiness(store, provider=args.provider), indent=2, sort_keys=True))
        elif args.model_command == "execute":
            broker = build_secret_broker(args, store)
            actor_user_id = args.actor_user_id or _primary_operator_user_id(store)
            sponsoring_user_id = args.sponsoring_user_id or actor_user_id
            service = ModelExecutionService(store, secret_broker=broker)
            result = service.execute(
                ModelExecutionRequest(
                    actor_user_id=actor_user_id,
                    sponsoring_user_id=sponsoring_user_id,
                    prompt=args.prompt,
                    purpose=args.purpose,
                    scope_type=args.scope_type,
                    scope_ref=args.scope_ref,
                    requesting_agent_id=args.requesting_agent_id,
                    content_classification=args.classification,
                    origin_entity_ref=args.origin_entity_ref,
                    lane=args.lane,
                    max_output_tokens=args.max_output_tokens,
                    metadata={"invoked_by": "cli.model.execute"},
                )
            )
            print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "secret":
        broker = build_secret_broker(args, store)
        if args.secret_command == "put":
            record = broker.ingest_secret(
                plaintext=read_secret_input(args),
                handle_name=args.handle,
                secret_kind=args.kind,
                integration_type=args.integration,
                owner_type=args.owner_type,
                owner_ref=args.owner_ref,
                scope_type=args.scope_type,
                scope_ref=args.scope_ref,
                display_hint=args.display_hint,
                actor_type="system",
                actor_ref="cli.secret.put",
            )
            print(json.dumps(record, indent=2, sort_keys=True))
        elif args.secret_command == "rotate":
            record = broker.rotate_secret(
                args.secret_ref,
                plaintext=read_secret_input(args),
                actor_type="system",
                actor_ref="cli.secret.rotate",
                reason=args.reason,
            )
            print(json.dumps(record, indent=2, sort_keys=True))
        elif args.secret_command == "list":
            rows = broker.list_secrets(include_inactive=args.include_inactive)
            print(json.dumps(rows, indent=2, sort_keys=True))
        elif args.secret_command == "revoke":
            record = broker.revoke_secret(
                args.secret_ref,
                actor_type="system",
                actor_ref="cli.secret.revoke",
                reason=args.reason,
            )
            print(json.dumps(record, indent=2, sort_keys=True))


def _primary_operator_user_id(store: AgentFirstStore) -> str:
    with store.connect() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE primary_user_flag = 1 AND status = 'active'").fetchone()
        if row is None:
            raise ValueError("No active primary operator found; pass --actor-user-id or run onboarding bootstrap.")
        return str(row["user_id"])


def _run_guided_onboarding(args: argparse.Namespace, store: AgentFirstStore) -> None:
    broker = build_secret_broker(args, store)
    service = OnboardingService(store, secret_broker=broker)
    status = service.status()

    print("AgentFirst onboarding")
    print(f"Using local state at: {store.db_path.parent}")

    if status.get("bootstrapped"):
        latest = status.get("latest_bootstrap", {})
        print("\nAgentFirst is already onboarded.")
        print(f"Primary provider/model: {latest.get('provider') or 'unknown'}:{latest.get('model') or 'unknown'}")
        _print_next_steps(provider=latest.get("provider") or "openai")
        return

    print("\nI will walk you through a few simple choices.")
    operator_display_name = _prompt_text("Operator display name", default="Primary Operator")
    timezone = _prompt_text("Timezone", default="America/New_York")
    custody_mode = _prompt_choice(
        "How should AgentFirst protect local secrets?",
        [
            ("operator-passphrase", "Use a local passphrase"),
            ("macos-keychain", "Use macOS Keychain"),
        ],
        default_index=0,
    )
    provider = _prompt_choice(
        "Which AI provider should be your default?",
        [
            ("openai", "OpenAI"),
            ("anthropic", "Anthropic"),
            ("google", "Google"),
            ("local", "Local placeholder/fallback"),
        ],
        default_index=0,
    )
    provider_entry = find_provider(provider)
    models = [
        (item.model, f"{item.model} ({item.family})")
        for item in provider_entry.models
    ] if provider_entry else []
    model = _prompt_choice("Which model should be your default?", models, default_index=0)
    enable_local = _prompt_confirm("Enable local shell and TUI access?", default=True)
    channels = {"local": "enabled" if enable_local else "disabled"}

    if custody_mode == "operator-passphrase" and not os.environ.get(args.passphrase_env):
        print(f"\nAgentFirst will ask for a passphrase when it initializes the local secret vault ({args.passphrase_env}).")

    result = service.bootstrap(
        OnboardingRequest(
            operator_display_name=operator_display_name,
            timezone=timezone,
            custody_mode=custody_mode.replace("-", "_"),
            provider=provider,
            model=model,
            channels=channels,
            secret_files=[],
            actor_type="system",
            actor_ref="cli.onboarding.guided",
        )
    )

    print("\nOnboarding complete.")
    print(f"Primary operator: {result['primary_operator']['display_name']}")
    print(f"Default model: {result['model_preference']['provider']}:{result['model_preference']['model']}")
    print(f"Readiness: {result['readiness']['summary']}")
    print()
    print(json.dumps(result, indent=2, sort_keys=True))
    _print_next_steps(provider=provider)


def _print_next_steps(*, provider: str) -> None:
    print("\nNext useful commands:")
    print("  agentfirst tui")
    print("  agentfirst doctor")
    print(f"  agentfirst model readiness --provider {provider}")
    if provider == "openai":
        print("  agentfirst model execute --lane codex_cli --prompt 'Return exactly: codex lane live ok'")


def _prompt_text(label: str, *, default: str) -> str:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        value = raw or default
        if value:
            return value


def _prompt_choice(label: str, options: list[tuple[str, str]], *, default_index: int = 0) -> str:
    while True:
        print(f"\n{label}")
        for index, (_, description) in enumerate(options, start=1):
            default_marker = " (default)" if index - 1 == default_index else ""
            print(f"  {index}. {description}{default_marker}")
        raw = input("Choose a number: ").strip()
        if not raw:
            return options[default_index][0]
        try:
            selected = int(raw) - 1
        except ValueError:
            print("Please enter a number from the list.")
            continue
        if 0 <= selected < len(options):
            return options[selected][0]
        print("That choice is not in the list.")


def _prompt_confirm(label: str, *, default: bool) -> bool:
    while True:
        hint = "Y/n" if default else "y/N"
        raw = input(f"{label} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer y or n.")


if __name__ == "__main__":
    main()
