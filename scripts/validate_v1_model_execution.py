#!/usr/bin/env python3
"""Validate governed model execution scaffolding and OpenAI API-lane execution path."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from agentfirst_storage import (
    AgentFirstStore,
    LocalEncryptedSecretVault,
    ModelExecutionRequest,
    ModelExecutionService,
    ModelPreferenceRequest,
    ModelRoutingService,
    OperatorPassphraseRootKeyProvider,
    SecretBroker,
)
from agentfirst_storage.provider_catalog import find_provider, inspect_provider_readiness, provider_catalog_as_dict


class FakeTextTransport:
    def execute(self, *, model: str, prompt: str, max_output_tokens: int) -> dict[str, Any]:
        return {
            "text": f"fake-live-response model={model} tokens={max_output_tokens} prompt={prompt[:12]}",
            "raw": {"id": "fake-response", "model": model, "usage": {"output_tokens": 7}},
        }


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-model-exec-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()
        primary = store.bootstrap_admin("Model Execution Primary", "America/New_York")
        routing = ModelRoutingService(store)
        routing.create_preference(
            ModelPreferenceRequest(
                scope_type="user",
                scope_ref=primary["user_id"],
                provider="openai",
                model="gpt-5.4",
                rationale_summary="Validation uses OpenAI API lane with an injected transport.",
                purpose="general",
                created_by_type="user",
                created_by_ref=primary["user_id"],
            )
        )
        routing.create_preference(
            ModelPreferenceRequest(
                scope_type="user",
                scope_ref=primary["user_id"],
                provider="google",
                model="gemini-3-pro",
                rationale_summary="Validation proves structural readiness without pretending Google live execution.",
                purpose="google_structural",
                created_by_type="user",
                created_by_ref=primary["user_id"],
            )
        )

        broker = SecretBroker(
            store,
            LocalEncryptedSecretVault(
                root / "secure-secrets",
                OperatorPassphraseRootKeyProvider(passphrase="validation-passphrase"),
            ),
        )
        broker.ingest_secret(
            plaintext="sk-validation-placeholder",
            handle_name="openai.api_key",
            secret_kind="api_key",
            integration_type="model_provider",
            owner_type="system",
            owner_ref="validation",
            scope_type="user",
            scope_ref=primary["user_id"],
            metadata={"provider": "openai"},
            actor_type="system",
            actor_ref="validate_v1_model_execution",
        )

        service = ModelExecutionService(
            store,
            secret_broker=broker,
            transports={("openai", "api"): FakeTextTransport()},
        )
        executed = service.execute(
            ModelExecutionRequest(
                actor_user_id=primary["user_id"],
                sponsoring_user_id=primary["user_id"],
                prompt="Return a tiny validation response.",
                lane="api",
                max_output_tokens=32,
            )
        )
        if not executed["ok"] or not executed["real_execution"]:
            raise RuntimeError(f"Injected OpenAI API execution did not execute: {executed}")
        execution = executed["execution"]
        if execution["status"] != "executed" or execution["real_execution"] != 1:
            raise RuntimeError("Execution evidence did not record real execution")
        if "validation response" in json.dumps(execution["outcome_json"]):
            raise RuntimeError("Execution outcome stored more prompt text than expected")

        unavailable = service.execute(
            ModelExecutionRequest(
                actor_user_id=primary["user_id"],
                sponsoring_user_id=primary["user_id"],
                prompt="Try Google structurally.",
                purpose="google_structural",
                lane="api",
                metadata={"validation_case": "google_structural_no_secret"},
            )
        )
        if unavailable["ok"]:
            raise RuntimeError("Unexpected execution succeeded without an Anthropic route")

        catalog = provider_catalog_as_dict()
        for provider in ("openai", "anthropic", "google"):
            if find_provider(provider) is None:
                raise RuntimeError(f"Provider missing from catalog: {provider}")

        readiness = inspect_provider_readiness(store, provider="openai")
        openai_readiness = readiness["providers"][0]
        if not any(lane["lane"] == "api" and lane["ready_for_live_attempt"] for lane in openai_readiness["lanes"]):
            raise RuntimeError("OpenAI API lane did not report ready after secret ingestion")

        audits = store.list_records("audit_events", 1000)
        execution_audits = [item for item in audits if item["event_type"] == "model_execution_recorded"]
        if len(execution_audits) < 2:
            raise RuntimeError("Model execution audit events were not recorded")

        print(
            json.dumps(
                {
                    "ok": True,
                    "catalog_snapshot_version": catalog["snapshot_version"],
                    "providers": [item["provider"] for item in catalog["providers"]],
                    "openai_api_execution": {
                        "model_execution_id": execution["model_execution_id"],
                        "status": execution["status"],
                        "lane": execution["lane"],
                        "real_execution": bool(execution["real_execution"]),
                        "prompt_sha256_recorded": bool(execution["prompt_sha256"]),
                    },
                    "unavailable_execution": {
                        "status": unavailable["status"],
                        "real_execution": unavailable["real_execution"],
                        "disclosure": unavailable["disclosure"],
                    },
                    "audit": {
                        "model_executions": count(store, "model_executions"),
                        "model_execution_audits": len(execution_audits),
                        "model_route_decisions": count(store, "model_route_decisions"),
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
