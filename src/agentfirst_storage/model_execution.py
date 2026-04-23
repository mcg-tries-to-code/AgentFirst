"""Governed live model execution service."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .model_routing import ModelRouteRequest, ModelRoutingService
from .provider_catalog import CATALOG_DISCLOSURE, find_provider, inspect_provider_readiness
from .secret_broker import SecretBroker
from .store import AgentFirstStore, new_id


@dataclass(frozen=True)
class ModelExecutionRequest:
    actor_user_id: str
    sponsoring_user_id: str
    prompt: str
    purpose: str = "general"
    scope_type: str = "user"
    scope_ref: str | None = None
    requesting_agent_id: str | None = None
    content_classification: str = "internal"
    origin_entity_ref: str | None = None
    lane: str | None = None
    max_output_tokens: int = 512
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelTransport(Protocol):
    def execute(self, *, model: str, prompt: str, max_output_tokens: int) -> dict[str, Any]:
        raise NotImplementedError


class OpenAIResponsesApiTransport:
    """Small Responses API text path using stdlib HTTP to avoid a hard SDK dependency."""

    def __init__(self, *, api_key: str, timeout: int = 60):
        self.api_key = api_key
        self.timeout = timeout

    def execute(self, *, model: str, prompt: str, max_output_tokens: int) -> dict[str, Any]:
        payload = json.dumps({"model": model, "input": prompt, "max_output_tokens": max_output_tokens}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"OpenAI Responses API returned HTTP {exc.code}: {detail}") from exc
        data = json.loads(body)
        return {"text": _extract_response_text(data), "raw": data}


class CodexCliTransport:
    """Codex CLI subscription-backed execution lane."""

    def __init__(self, *, cwd: Path | None = None, timeout: int = 180):
        self.cwd = cwd
        self.timeout = timeout

    def execute(self, *, model: str, prompt: str, max_output_tokens: int) -> dict[str, Any]:
        del max_output_tokens
        with tempfile.TemporaryDirectory(prefix="agentfirst-codex-cli-") as tmp:
            output = Path(tmp) / "last-message.txt"
            proc = subprocess.run(
                [
                    "codex",
                    "exec",
                    "--model",
                    model,
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "--output-last-message",
                    str(output),
                    prompt,
                ],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            text = output.read_text(encoding="utf-8") if output.exists() else proc.stdout
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or text).strip()[:1000]
                raise RuntimeError(f"Codex CLI execution failed with exit code {proc.returncode}: {detail}")
            return {
                "text": text.strip(),
                "raw": {
                    "stdout_preview": proc.stdout.strip()[:1000],
                    "stderr_preview": proc.stderr.strip()[:1000],
                    "subscription_backed": True,
                },
            }


class ModelExecutionService:
    """Route, govern, execute, and audit model queries."""

    def __init__(
        self,
        store: AgentFirstStore,
        *,
        secret_broker: SecretBroker,
        routing: ModelRoutingService | None = None,
        transports: dict[tuple[str, str], ModelTransport] | None = None,
    ):
        self.store = store
        self.secret_broker = secret_broker
        self.routing = routing or ModelRoutingService(store)
        self.transports = transports or {}

    def execute(self, request: ModelExecutionRequest) -> dict[str, Any]:
        if not request.prompt.strip():
            raise ValueError("Model execution prompt must not be empty")

        route = self.routing.route(
            ModelRouteRequest(
                actor_user_id=request.actor_user_id,
                sponsoring_user_id=request.sponsoring_user_id,
                purpose=request.purpose,
                scope_type=request.scope_type,
                scope_ref=request.scope_ref,
                requesting_agent_id=request.requesting_agent_id,
                content_classification=request.content_classification,
                origin_entity_ref=request.origin_entity_ref,
                metadata={"execution_requested": True, **request.metadata},
            )
        )
        route_decision = route["route_decision"]
        if not route["selected"]:
            return self._record_unavailable(
                request,
                route_decision,
                provider=route_decision.get("selected_provider"),
                model=route_decision.get("selected_model"),
                lane=request.lane,
                reason=f"Route status is {route_decision['status']}; no live execution attempted.",
                route=route,
            )

        provider = str(route_decision["selected_provider"])
        model = str(route_decision["selected_model"])
        lane_result = self._resolve_lane(provider, request.lane)
        if not lane_result["ok"]:
            return self._record_unavailable(
                request,
                route_decision,
                provider=provider,
                model=model,
                lane=request.lane,
                reason=lane_result["reason"],
                route=route,
                readiness=lane_result.get("readiness"),
            )

        lane = str(lane_result["lane"])
        transport = self._transport(provider, lane)
        try:
            result = transport.execute(
                model=model,
                prompt=request.prompt,
                max_output_tokens=request.max_output_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - execution failures must be persisted honestly.
            return self._record_unavailable(
                request,
                route_decision,
                provider=provider,
                model=model,
                lane=lane,
                reason=str(exc),
                route=route,
                readiness=lane_result.get("readiness"),
                attempted=True,
            )

        text = str(result.get("text") or "")
        execution = self._record_execution(
            request,
            route_decision,
            provider=provider,
            model=model,
            lane=lane,
            status="executed",
            real_execution=True,
            disclosure=self._execution_disclosure(provider, model, lane, route),
            outcome={
                "real_execution": True,
                "output_sha256": _sha256(text),
                "output_preview": _preview(text),
                "transport_metadata": _safe_transport_metadata(result.get("raw")),
            },
        )
        return {
            "ok": True,
            "status": "executed",
            "real_execution": True,
            "text": text,
            "route": route,
            "lane": lane,
            "execution": execution,
            "disclosure": execution["disclosure_summary"],
        }

    def readiness(self, *, provider: str | None = None) -> dict[str, Any]:
        return inspect_provider_readiness(self.store, provider=provider)

    def _resolve_lane(self, provider: str, requested_lane: str | None) -> dict[str, Any]:
        readiness = inspect_provider_readiness(self.store, provider=provider)
        provider_readiness = readiness["providers"][0] if readiness["providers"] else None
        if provider_readiness is None:
            return {"ok": False, "reason": f"Provider is not in the bounded catalog: {provider}", "readiness": readiness}
        candidates = provider_readiness["lanes"]
        if requested_lane:
            candidates = [item for item in candidates if item["lane"] == requested_lane]
            if not candidates:
                return {
                    "ok": False,
                    "reason": f"Requested lane is not registered for provider {provider}: {requested_lane}",
                    "readiness": readiness,
                }
        for lane in candidates:
            if lane["ready_for_live_attempt"]:
                return {"ok": True, "lane": lane["lane"], "readiness": readiness}
        missing = [
            {"lane": item["lane"], "status": item["status"], "missing": item["missing"], "implemented": item["implemented"]}
            for item in candidates
        ]
        lane_scope = f"requested lane {requested_lane}" if requested_lane else f"provider {provider}"
        return {
            "ok": False,
            "reason": f"No live-ready lane is available for {lane_scope}.",
            "readiness": readiness,
            "missing": missing,
        }

    def _transport(self, provider: str, lane: str) -> ModelTransport:
        injected = self.transports.get((provider, lane))
        if injected is not None:
            return injected
        if provider == "openai" and lane == "api":
            secret_ref = self._provider_secret_ref("openai", "api_key", "secret://openai.api_key")
            api_key = self.secret_broker.resolve_secret_text(
                secret_ref,
                actor_type="system",
                actor_ref="model_execution.openai_api",
                purpose="model_execution",
                integration_type="model_provider",
            )
            return OpenAIResponsesApiTransport(api_key=api_key)
        if provider == "openai" and lane == "codex_cli":
            return CodexCliTransport(cwd=Path.cwd())
        raise NotImplementedError(f"Live execution is not implemented for {provider}:{lane}")

    def _provider_secret_ref(self, provider: str, secret_kind: str, default_handle: str) -> str:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT handle_uri FROM secret_records
                WHERE integration_type = 'model_provider'
                  AND secret_kind = ?
                  AND status = 'active'
                  AND json_extract(metadata_json, '$.provider') = ?
                ORDER BY created_at DESC, secret_id DESC
                LIMIT 1
                """,
                (secret_kind, provider),
            ).fetchone()
            if row:
                return str(row["handle_uri"])
            row = conn.execute(
                """
                SELECT handle_uri FROM secret_records
                WHERE handle_uri = ?
                  AND integration_type = 'model_provider'
                  AND status = 'active'
                LIMIT 1
                """,
                (default_handle,),
            ).fetchone()
            if row:
                return str(row["handle_uri"])
        raise ValueError(f"No active {provider} {secret_kind} secret handle is available")

    def _record_unavailable(
        self,
        request: ModelExecutionRequest,
        route_decision: dict[str, Any],
        *,
        provider: str | None,
        model: str | None,
        lane: str | None,
        reason: str,
        route: dict[str, Any],
        readiness: dict[str, Any] | None = None,
        attempted: bool = False,
    ) -> dict[str, Any]:
        disclosure = (
            f"Model execution was not real: {reason} "
            f"Route={provider or 'none'}:{model or 'none'}; lane={lane or 'auto'}."
        )
        execution = self._record_execution(
            request,
            route_decision,
            provider=provider,
            model=model,
            lane=lane,
            status="failed" if attempted else "unavailable",
            real_execution=False,
            disclosure=disclosure,
            outcome={
                "real_execution": False,
                "attempted": attempted,
                "reason": reason,
                "readiness": readiness,
            },
        )
        return {
            "ok": False,
            "status": execution["status"],
            "real_execution": False,
            "text": None,
            "route": route,
            "lane": lane,
            "execution": execution,
            "disclosure": disclosure,
        }

    def _record_execution(
        self,
        request: ModelExecutionRequest,
        route_decision: dict[str, Any],
        *,
        provider: str | None,
        model: str | None,
        lane: str | None,
        status: str,
        real_execution: bool,
        disclosure: str,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        actor_type = "agent" if request.requesting_agent_id else "user"
        actor_ref = request.requesting_agent_id or request.actor_user_id
        with self.store.connect() as conn:
            execution = self.store.insert(
                "model_executions",
                {
                    "model_execution_id": new_id("mexec"),
                    "model_route_decision_id": route_decision["model_route_decision_id"],
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "sponsoring_user_id": request.sponsoring_user_id,
                    "requesting_agent_id": request.requesting_agent_id,
                    "provider": provider,
                    "model": model,
                    "lane": lane,
                    "transport": self._transport_name(provider, lane),
                    "prompt_sha256": _sha256(request.prompt),
                    "prompt_preview": _preview(request.prompt),
                    "disclosure_summary": disclosure,
                    "real_execution": 1 if real_execution else 0,
                    "outcome_json": outcome,
                    "status": status,
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "model_execution_recorded",
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "object_type": "model_execution",
                    "object_ref": execution["model_execution_id"],
                    "action_summary": disclosure,
                    "outcome": status,
                    "policy_decision_id": route_decision.get("policy_decision_id"),
                    "metadata_json": {
                        "model_route_decision_id": route_decision["model_route_decision_id"],
                        "provider": provider,
                        "model": model,
                        "lane": lane,
                        "real_execution": real_execution,
                    },
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "model_execution_recorded",
                "model_execution",
                execution["model_execution_id"],
                actor_type,
                actor_ref,
                {"audit_event_id": audit["audit_event_id"], "status": status, "real_execution": real_execution},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            conn.commit()
            return execution

    def _transport_name(self, provider: str | None, lane: str | None) -> str | None:
        if not provider or not lane:
            return None
        entry = find_provider(provider)
        if entry is None:
            return None
        found = next((item for item in entry.lanes if item.lane == lane), None)
        return found.transport if found else None

    def _execution_disclosure(self, provider: str, model: str, lane: str, route: dict[str, Any]) -> str:
        backing = "subscription-backed Codex CLI" if lane == "codex_cli" else "API-key-backed provider API"
        fallback = " Fallback route was used." if route.get("fallback_used") else ""
        return (
            f"Model execution was real via {provider}:{model} on lane {lane} ({backing})."
            f"{fallback} {CATALOG_DISCLOSURE}"
        )


def _extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _preview(value: str, limit: int = 240) -> str:
    cleaned = " ".join(value.split())
    return cleaned[:limit]


def _safe_transport_metadata(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    allowed = {}
    for key in ("id", "model", "usage", "subscription_backed", "stdout_preview", "stderr_preview"):
        if key in raw:
            allowed[key] = raw[key]
    return allowed
