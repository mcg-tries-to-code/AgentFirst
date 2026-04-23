"""Bounded minimal command surface for AgentFirst V1 Feature 3."""

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .doctor import DoctorService
from .memory import MemoryService
from .model_execution import ModelExecutionRequest, ModelExecutionService
from .onboarding import OnboardingRequest, OnboardingSecretFile, OnboardingService
from .operator_surface import OperatorSurface
from .provider_catalog import inspect_provider_readiness, provider_catalog_as_dict
from .secret_broker import SecretBroker
from .store import AgentFirstStore


COMMANDS = {
    "/help": "Show the bounded V1 command set.",
    "/status": "Inspect local onboarding, doctor, and operator state.",
    "/onboard": "Delegate to Feature 1 onboarding bootstrap/status logic.",
    "/doctor": "Delegate to Feature 2 doctor inspection or bounded --fix.",
    "/approve": "List or resolve existing canonical approval records.",
    "/new": "Checkpoint current lane signal, clear short-term context, and start a fresh working set.",
    "/restart": "Checkpoint current lane signal and reinitialize runtime state for the same lane.",
    "/lane": "Inspect bounded lane identity, active short-term context, and recent checkpoints.",
    "/model": "Inspect model catalogs/readiness or run governed execution.",
}


class CommandSurfaceError(Exception):
    """Explicit command-surface failure with a stable error code."""

    def __init__(self, error: str, message: str, *, exit_code: int = 2, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.error = error
        self.message = message
        self.exit_code = exit_code
        self.data = data or {}

    def as_result(self) -> "CommandSurfaceResult":
        return CommandSurfaceResult(
            ok=False,
            command=None,
            exit_code=self.exit_code,
            data={"error": self.error, "message": self.message, **self.data},
        )


class CommandArgumentParser(argparse.ArgumentParser):
    """Argument parser that reports failures through the JSON command envelope."""

    def error(self, message: str) -> None:
        raise CommandSurfaceError(
            "invalid_arguments",
            f"Invalid arguments for {self.prog}: {message}",
            exit_code=2,
        )

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status:
            raise CommandSurfaceError(
                "invalid_arguments",
                message.strip() if message else f"Invalid arguments for {self.prog}.",
                exit_code=status,
            )


@dataclass(frozen=True)
class CommandSurfaceResult:
    ok: bool
    command: str | None
    exit_code: int
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "surface": "agentfirst_v1_minimal_command_surface",
            "exit_code": self.exit_code,
            "data": self.data,
        }
        if self.command:
            payload["command"] = self.command
        return payload


class MinimalCommandSurface:
    """Small slash-command router that delegates to canonical Feature 1/2 services."""

    def __init__(
        self,
        store: AgentFirstStore,
        *,
        secret_root: Path,
        secret_broker_factory: Callable[[], SecretBroker],
    ):
        self.store = store
        self.secret_root = secret_root
        self.secret_broker_factory = secret_broker_factory

    def run(self, tokens: list[str]) -> CommandSurfaceResult:
        parts = self._normalize_tokens(tokens)
        if not parts:
            return self.help_result()
        command = self._canonical_command(parts[0])
        args = parts[1:]
        try:
            if command == "/help":
                return self.help_result(args[0] if args else None)
            if command == "/status":
                self._reject_args(command, args)
                return self.status_result()
            if command == "/onboard":
                return self.onboard_result(args)
            if command == "/doctor":
                return self.doctor_result(args)
            if command == "/approve":
                return self.approve_result(args)
            if command == "/lane":
                self._reject_args(command, args)
                return self.lane_result()
            if command == "/model":
                return self.model_result(args)
            if command == "/new":
                self._reject_args(command, args)
                return self.reset_result("/new")
            if command == "/restart":
                self._reject_args(command, args)
                return self.reset_result("/restart")
        except CommandSurfaceError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert delegated failures into explicit command failures.
            raise CommandSurfaceError(
                "delegated_command_failed",
                str(exc),
                exit_code=1,
                data={"command": command, "delegated_to": self._delegation_target(command)},
            ) from exc
        raise CommandSurfaceError("unsupported_command", f"Unsupported command: {command}", data={"command": command})

    def help_result(self, command: str | None = None) -> CommandSurfaceResult:
        if command:
            canonical = self._canonical_command(command)
            details = self._command_help(canonical)
        else:
            details = {
                "commands": [{"command": name, "summary": summary} for name, summary in sorted(COMMANDS.items())],
                "authority_boundary": (
                    "This surface only routes bounded local commands. It does not infer natural language, "
                    "create a second control plane, or widen enrollment/trust boundaries."
                ),
            }
        return CommandSurfaceResult(ok=True, command="/help", exit_code=0, data=details)

    def status_result(self) -> CommandSurfaceResult:
        onboarding = OnboardingService(self.store, secret_broker=self.secret_broker_factory()).status()
        doctor = DoctorService(self.store, secret_root=self.secret_root).run(fix=False)
        operator = OperatorSurface(self.store).status_overview()
        data = {
            "runnable": bool(onboarding.get("readiness", {}).get("runnable")) and bool(doctor.get("runnable")),
            "onboarding": onboarding,
            "doctor": {
                "runnable": doctor["runnable"],
                "summary": doctor["summary"],
                "counts": doctor["counts"],
            },
            "operator": {
                "counts": operator["counts"],
                "open_approvals": operator["approvals"]["open"],
                "failure_disclosure_count": operator["failure_disclosure_count"],
            },
        }
        return CommandSurfaceResult(ok=True, command="/status", exit_code=0, data=data)

    def onboard_result(self, args: list[str]) -> CommandSurfaceResult:
        if not args:
            raise CommandSurfaceError(
                "missing_subcommand",
                "/onboard requires status or bootstrap.",
                data={"usage": self._command_help("/onboard")},
            )
        subcommand = args[0]
        service = OnboardingService(self.store, secret_broker=self.secret_broker_factory())
        if subcommand == "status":
            self._reject_args("/onboard status", args[1:])
            return CommandSurfaceResult(ok=True, command="/onboard", exit_code=0, data=service.status())
        if subcommand != "bootstrap":
            raise CommandSurfaceError("unsupported_subcommand", f"Unsupported /onboard subcommand: {subcommand}")

        parser = CommandArgumentParser(prog="/onboard bootstrap", add_help=False)
        parser.add_argument("--operator-display-name", required=True)
        parser.add_argument("--timezone", default="UTC")
        parser.add_argument("--custody-mode", choices=["operator-passphrase", "macos-keychain"], required=True)
        parser.add_argument("--provider", required=True)
        parser.add_argument("--model", required=True)
        parser.add_argument("--channel", action="append", default=[])
        parser.add_argument("--secret-file", nargs=4, action="append", default=[])
        parsed = self._parse(parser, args[1:])
        result = service.bootstrap(
            OnboardingRequest(
                operator_display_name=parsed.operator_display_name,
                timezone=parsed.timezone,
                custody_mode=parsed.custody_mode.replace("-", "_"),
                provider=parsed.provider,
                model=parsed.model,
                channels=self._parse_channels(parsed.channel),
                secret_files=self._parse_secret_files(parsed.secret_file),
                actor_type="system",
                actor_ref="command_surface./onboard.bootstrap",
            )
        )
        return CommandSurfaceResult(ok=True, command="/onboard", exit_code=0, data=result)

    def doctor_result(self, args: list[str]) -> CommandSurfaceResult:
        parser = CommandArgumentParser(prog="/doctor", add_help=False)
        parser.add_argument("--fix", action="store_true")
        parsed = self._parse(parser, args)
        result = DoctorService(self.store, secret_root=self.secret_root).run(fix=parsed.fix)
        return CommandSurfaceResult(ok=True, command="/doctor", exit_code=0, data=result)

    def approve_result(self, args: list[str]) -> CommandSurfaceResult:
        surface = OperatorSurface(self.store)
        if not args or args[0] == "list":
            parser = CommandArgumentParser(prog="/approve list", add_help=False)
            parser.add_argument("--limit", type=int, default=25)
            parsed = self._parse(parser, args[1:] if args else [])
            return CommandSurfaceResult(
                ok=True,
                command="/approve",
                exit_code=0,
                data={"approvals": surface.approvals(limit=parsed.limit), "mode": "read_only"},
            )
        if args[0] not in {"approve", "deny"}:
            raise CommandSurfaceError("unsupported_subcommand", f"Unsupported /approve subcommand: {args[0]}")
        parser = CommandArgumentParser(prog=f"/approve {args[0]}", add_help=False)
        parser.add_argument("approval_record_id")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--confirm", required=True)
        parsed = self._parse(parser, args[1:])
        status = "approved" if args[0] == "approve" else "denied"
        return CommandSurfaceResult(
            ok=True,
            command="/approve",
            exit_code=0,
            data=surface.resolve_approval(
                parsed.approval_record_id,
                actor_user_id=parsed.actor,
                status=status,
                confirmation=parsed.confirm,
            ),
        )

    def lane_result(self) -> CommandSurfaceResult:
        snapshot = MemoryService(self.store).lane_snapshot()
        return CommandSurfaceResult(
            ok=True,
            command="/lane",
            exit_code=0,
            data={
                "status": "active",
                "implemented_scope": "bounded_lane_identity_and_lifecycle_scaffold",
                "lane_state": snapshot,
                "authority_boundary": (
                    "Feature 4 represents lane and memory lifecycle metadata locally. "
                    "It does not route remote commands or mutate enrollment trust boundaries."
                ),
            },
        )

    def model_result(self, args: list[str]) -> CommandSurfaceResult:
        if not args:
            raise CommandSurfaceError(
                "missing_subcommand",
                "/model requires catalog, readiness, or execute.",
                data={"usage": self._command_help("/model")},
            )
        subcommand = args[0]
        if subcommand == "catalog":
            self._reject_args("/model catalog", args[1:])
            return CommandSurfaceResult(ok=True, command="/model", exit_code=0, data=provider_catalog_as_dict())
        if subcommand == "readiness":
            parser = CommandArgumentParser(prog="/model readiness", add_help=False)
            parser.add_argument("--provider")
            parsed = self._parse(parser, args[1:])
            return CommandSurfaceResult(
                ok=True,
                command="/model",
                exit_code=0,
                data=inspect_provider_readiness(self.store, provider=parsed.provider),
            )
        if subcommand != "execute":
            raise CommandSurfaceError("unsupported_subcommand", f"Unsupported /model subcommand: {subcommand}")

        parser = CommandArgumentParser(prog="/model execute", add_help=False)
        parser.add_argument("--prompt", required=True)
        parser.add_argument("--purpose", default="general")
        parser.add_argument("--scope-type", choices=["user", "agent", "task"], default="user")
        parser.add_argument("--scope-ref")
        parser.add_argument("--actor-user-id")
        parser.add_argument("--sponsoring-user-id")
        parser.add_argument("--requesting-agent-id")
        parser.add_argument("--classification", default="internal")
        parser.add_argument("--origin-entity-ref")
        parser.add_argument("--lane", choices=["api", "codex_cli", "claude_code_cli", "antigravity_cli"])
        parser.add_argument("--max-output-tokens", type=int, default=512)
        parsed = self._parse(parser, args[1:])
        actor_user_id = parsed.actor_user_id or self._primary_operator_user_id()
        service = ModelExecutionService(self.store, secret_broker=self.secret_broker_factory())
        result = service.execute(
            ModelExecutionRequest(
                actor_user_id=actor_user_id,
                sponsoring_user_id=parsed.sponsoring_user_id or actor_user_id,
                prompt=parsed.prompt,
                purpose=parsed.purpose,
                scope_type=parsed.scope_type,
                scope_ref=parsed.scope_ref,
                requesting_agent_id=parsed.requesting_agent_id,
                content_classification=parsed.classification,
                origin_entity_ref=parsed.origin_entity_ref,
                lane=parsed.lane,
                max_output_tokens=parsed.max_output_tokens,
                metadata={"invoked_by": "command_surface./model.execute"},
            )
        )
        return CommandSurfaceResult(ok=result["ok"], command="/model", exit_code=0 if result["ok"] else 1, data=result)

    def reset_result(self, command: str) -> CommandSurfaceResult:
        result = MemoryService(self.store).reset_lane(command=command, actor_ref=f"command_surface.{command[1:]}")
        return CommandSurfaceResult(ok=True, command=command, exit_code=0, data=result)

    def _canonical_command(self, command: str) -> str:
        canonical = command if command.startswith("/") else f"/{command}"
        if canonical not in COMMANDS:
            raise CommandSurfaceError(
                "unsupported_command",
                f"Unsupported command: {command}",
                data={"supported_commands": sorted(COMMANDS)},
            )
        return canonical

    def _command_help(self, command: str) -> dict[str, Any]:
        if command == "/onboard":
            return {
                "summary": COMMANDS[command],
                "usage": [
                    "/onboard status",
                    "/onboard bootstrap --operator-display-name NAME --custody-mode operator-passphrase --provider openai --model gpt-5.4 --channel local=enabled",
                ],
                "delegates_to": "OnboardingService",
            }
        if command == "/doctor":
            return {"summary": COMMANDS[command], "usage": ["/doctor", "/doctor --fix"], "delegates_to": "DoctorService"}
        if command == "/approve":
            return {
                "summary": COMMANDS[command],
                "usage": [
                    "/approve list [--limit N]",
                    "/approve approve <approval_record_id> --actor <user_id> --confirm APPROVED",
                    "/approve deny <approval_record_id> --actor <user_id> --confirm DENIED",
                ],
                "delegates_to": "OperatorSurface.resolve_approval",
            }
        if command == "/lane":
            return {
                "summary": COMMANDS[command],
                "usage": ["/lane"],
                "delegates_to": "MemoryService.lane_snapshot",
                "scope": "local default operator lane",
            }
        if command == "/model":
            return {
                "summary": COMMANDS[command],
                "usage": [
                    "/model catalog",
                    "/model readiness [--provider openai]",
                    "/model execute --prompt TEXT [--lane api|codex_cli]",
                ],
                "delegates_to": "ModelExecutionService",
                "boundary": "Model queries are governed query_model actions before execution.",
            }
        if command in {"/new", "/restart"}:
            return {
                "summary": COMMANDS[command],
                "usage": [command],
                "delegates_to": "MemoryService.reset_lane",
                "checkpoint_boundary": "selective mid-term checkpoint; no raw transcript dump and no wiki mutation",
            }
        return {"summary": COMMANDS[command], "usage": [command]}

    def _delegation_target(self, command: str) -> str:
        return {
            "/onboard": "OnboardingService",
            "/doctor": "DoctorService",
            "/approve": "OperatorSurface",
            "/status": "OnboardingService, DoctorService, OperatorSurface",
            "/lane": "MemoryService",
            "/model": "ModelExecutionService",
            "/new": "MemoryService",
            "/restart": "MemoryService",
        }.get(command, "command_surface")

    def _normalize_tokens(self, tokens: list[str]) -> list[str]:
        if len(tokens) == 1:
            return shlex.split(tokens[0])
        return tokens

    def _reject_args(self, command: str, args: list[str]) -> None:
        if args:
            raise CommandSurfaceError("unexpected_arguments", f"{command} does not accept arguments: {' '.join(args)}")

    def _parse(self, parser: argparse.ArgumentParser, args: list[str]) -> argparse.Namespace:
        try:
            return parser.parse_args(args)
        except CommandSurfaceError:
            raise
        except SystemExit as exc:
            raise CommandSurfaceError(
                "invalid_arguments",
                f"Invalid arguments for {parser.prog}.",
                exit_code=int(exc.code) if isinstance(exc.code, int) else 2,
            ) from exc

    def _parse_channels(self, values: list[str]) -> dict[str, str]:
        channels: dict[str, str] = {}
        for value in values:
            if "=" not in value:
                raise CommandSurfaceError("invalid_arguments", f"Expected --channel CHANNEL=STATE, got: {value}")
            channel, state = value.split("=", 1)
            channels[channel.strip()] = state.strip()
        return channels

    def _parse_secret_files(self, values: list[list[str]]) -> list[OnboardingSecretFile]:
        return [
            OnboardingSecretFile(handle=handle, kind=kind, integration=integration, path=Path(path))
            for handle, kind, integration, path in values
        ]

    def _primary_operator_user_id(self) -> str:
        with self.store.connect() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE primary_user_flag = 1 AND status = 'active'").fetchone()
            if row is None:
                raise CommandSurfaceError(
                    "missing_primary_operator",
                    "No active primary operator found; pass --actor-user-id or run onboarding bootstrap.",
                    exit_code=1,
                )
            return str(row["user_id"])
