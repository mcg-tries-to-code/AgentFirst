"""Policy and exfiltration enforcement for AgentFirst v0 Stage 2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .store import AgentFirstStore, new_id


DECISIONS = {
    "allow",
    "allow_with_logging",
    "allow_with_redaction",
    "require_primary_user_approval",
    "require_owner_approval",
    "deny",
}

GOVERNED_ACTION_TYPES = {
    "share_external",  # outbound message send
    "query_model",  # external model/provider query
    "export",
    "invoke_tool",  # tool invocation with outbound implication
}

CLASSIFICATION_ORDER = {
    "public": 0,
    "internal": 1,
    "private": 2,
    "sensitive": 3,
    "external_confidential": 4,
    "proprietary": 5,
    "restricted": 6,
}

DECISION_ORDER = {
    "allow": 0,
    "allow_with_logging": 1,
    "allow_with_redaction": 2,
    "require_owner_approval": 3,
    "require_primary_user_approval": 4,
    "deny": 5,
}

POLICY_LAYER_ORDER = {
    "global": 0,
    "system": 0,
    "primary-user": 1,
    "per-user": 2,
}


@dataclass(frozen=True)
class GovernedAction:
    """A consequential action requiring structural policy evaluation."""

    action_type: str
    actor_type: str
    actor_ref: str
    sponsoring_user_id: str
    object_type: str | None = None
    object_ref: str | None = None
    destination_type: str | None = None
    destination_identity: str | None = None
    content_classification: str = "internal"
    origin_entity_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    """Small explicit policy resolver backed by the Stage 1 store."""

    def __init__(self, store: AgentFirstStore):
        self.store = store

    def evaluate_and_record(self, action: GovernedAction) -> dict[str, Any]:
        if action.action_type not in GOVERNED_ACTION_TYPES:
            raise ValueError(f"Unsupported governed action_type: {action.action_type}")
        if action.content_classification not in CLASSIFICATION_ORDER:
            raise ValueError(f"Unsupported content_classification: {action.content_classification}")

        self.store.initialize()
        with self.store.connect() as conn:
            destination = self._resolve_destination(action, conn)
            policies = self._collect_policies(action.sponsoring_user_id, action, conn)
            classification_rules = self._collect_classification_rules(action, conn)

            resolved = self._resolve_decision(action, destination, policies, classification_rules)
            policy_refs = [policy["policy_id"] for policy in policies]
            policy_refs.extend(rule["rule_id"] for rule in classification_rules)

            decision = self.store.insert(
                "policy_decisions",
                {
                    "policy_decision_id": new_id("pdec"),
                    "actor_type": action.actor_type,
                    "actor_ref": action.actor_ref,
                    "sponsoring_user_id": action.sponsoring_user_id,
                    "action_type": action.action_type,
                    "object_type": action.object_type,
                    "object_ref": action.object_ref,
                    "destination_type": action.destination_type,
                    "destination_identity": action.destination_identity,
                    "destination_trust_tier": destination["trust_tier"],
                    "content_classification": action.content_classification,
                    "applicable_policy_refs_json": policy_refs,
                    "decision": resolved["decision"],
                    "rationale_summary": resolved["rationale"],
                },
                conn=conn,
                emit_event=False,
            )

            approval = None
            if decision["decision"] in {"require_primary_user_approval", "require_owner_approval"}:
                approval = self._create_approval_record(action, decision, destination, conn)

            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "policy_evaluated",
                    "actor_type": action.actor_type,
                    "actor_ref": action.actor_ref,
                    "object_type": action.object_type or "governed_action",
                    "object_ref": action.object_ref or decision["policy_decision_id"],
                    "action_summary": self._audit_summary(action, decision),
                    "outcome": decision["decision"],
                    "policy_decision_id": decision["policy_decision_id"],
                    "metadata_json": {
                        "destination": destination,
                        "origin_entity_ref": action.origin_entity_ref,
                        "approval_record_id": approval["approval_record_id"] if approval else None,
                        "matched": resolved["matched"],
                    },
                },
                conn=conn,
                emit_event=False,
            )
            event_id = self.store.append_event(
                "policy_decision_recorded",
                "policy_decision",
                decision["policy_decision_id"],
                action.actor_type,
                action.actor_ref,
                {
                    "decision": decision["decision"],
                    "action_type": action.action_type,
                    "audit_event_id": audit["audit_event_id"],
                    "approval_record_id": approval["approval_record_id"] if approval else None,
                },
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )

            return {
                "decision": decision,
                "audit_event": audit,
                "approval_record": approval,
                "event_id": event_id,
                "destination": destination,
                "matched": resolved["matched"],
            }

    def record_tool_invocation(
        self,
        action: GovernedAction,
        tool_capability_id: str,
        input_ref: str | None = None,
        output_ref: str | None = None,
        *,
        authority_policy_decision_id: str | None = None,
        operation: str | None = None,
        scope: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if action.action_type != "invoke_tool":
            raise ValueError("record_tool_invocation requires action_type='invoke_tool'")

        result = self.evaluate_and_record(action)
        decision = result["decision"]["decision"]
        status = {
            "deny": "policy_denied",
            "require_primary_user_approval": "awaiting_approval",
            "require_owner_approval": "awaiting_approval",
        }.get(decision, "policy_allowed")

        invocation = self.store.insert(
            "tool_invocations",
            {
                "tool_capability_id": tool_capability_id,
                "invoker_agent_id": action.actor_ref if action.actor_type == "agent" else None,
                "sponsoring_user_id": action.sponsoring_user_id,
                "authority_policy_decision_id": authority_policy_decision_id,
                "operation": operation,
                "scope_json": scope
                or {
                    "object_type": action.object_type,
                    "object_ref": action.object_ref,
                    "destination_type": action.destination_type,
                    "destination_identity": action.destination_identity,
                },
                "input_ref": input_ref,
                "output_ref": output_ref,
                "policy_decision_refs_json": [result["decision"]["policy_decision_id"]],
                "provenance_json": {
                    "tool_capability_id": tool_capability_id,
                    "sponsoring_user_id": action.sponsoring_user_id,
                    "actor_type": action.actor_type,
                    "actor_ref": action.actor_ref,
                    "authority_policy_decision_id": authority_policy_decision_id,
                    "policy_decision_id": result["decision"]["policy_decision_id"],
                    "destination_type": action.destination_type,
                    "destination_identity": action.destination_identity,
                    **(provenance or {}),
                },
                "outcome_json": outcome or {"policy_decision": decision, "executed": False},
                "status": status,
            },
            actor_type=action.actor_type,
            actor_ref=action.actor_ref,
        )
        return {**result, "tool_invocation": invocation}

    def _collect_policies(self, sponsoring_user_id: str, action: GovernedAction, conn: Any) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM policies
            WHERE status = 'active'
              AND (
                policy_type IN ('global', 'system')
                OR policy_type = 'primary-user'
                OR (policy_type = 'per-user' AND owner_user_id = ?)
              )
            ORDER BY
              CASE policy_type
                WHEN 'global' THEN 0
                WHEN 'system' THEN 0
                WHEN 'primary-user' THEN 1
                WHEN 'per-user' THEN 2
                ELSE 9
              END,
              priority ASC,
              policy_id ASC
            """,
            (sponsoring_user_id,),
        ).fetchall()
        policies = [self.store._decode_row(row) for row in rows]
        seen = {policy["policy_id"] for policy in policies}
        for policy_id in self._object_policy_refs(action, conn):
            if policy_id in seen:
                continue
            row = conn.execute(
                "SELECT * FROM policies WHERE policy_id = ? AND status = 'active'",
                (policy_id,),
            ).fetchone()
            if row is not None:
                policies.append(self.store._decode_row(row))
                seen.add(policy_id)
        return policies

    def _object_policy_refs(self, action: GovernedAction, conn: Any) -> list[str]:
        if not action.object_type or not action.object_ref:
            return []
        object_table = {
            "project": "projects",
            "commitment": "commitments",
            "artifact": "artifacts",
            "knowledge_corpus": "knowledge_corpora",
        }.get(action.object_type)
        if object_table is None:
            return []
        row = self.store.get_by_id(object_table, action.object_ref, conn=conn)
        if row is None:
            return []
        refs = list(row.get("policy_refs_json", []))
        if action.object_type in {"commitment", "artifact"}:
            project_ids: list[str] = []
            if row.get("project_id"):
                project_ids.append(row["project_id"])
            project_ids.extend(row.get("project_refs_json", []))
            for project_id in dict.fromkeys(project_ids):
                project = self.store.get_by_id("projects", project_id, conn=conn)
                if project:
                    refs.extend(project.get("policy_refs_json", []))
        return list(dict.fromkeys(refs))

    def _collect_classification_rules(self, action: GovernedAction, conn: Any) -> list[dict[str, Any]]:
        if action.content_classification == "external_confidential" and action.origin_entity_ref:
            rows = conn.execute(
                """
                SELECT * FROM data_classification_rules
                WHERE status = 'active'
                  AND classification = ?
                  AND (origin_entity_ref = ? OR origin_entity_ref IS NULL)
                ORDER BY CASE WHEN origin_entity_ref = ? THEN 0 ELSE 1 END, rule_id
                """,
                (action.content_classification, action.origin_entity_ref, action.origin_entity_ref),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM data_classification_rules
                WHERE status = 'active' AND classification = ?
                ORDER BY CASE WHEN origin_entity_ref IS NULL THEN 0 ELSE 1 END, rule_id
                """,
                (action.content_classification,),
            ).fetchall()
        return [self.store._decode_row(row) for row in rows]

    def _resolve_destination(self, action: GovernedAction, conn: Any) -> dict[str, Any]:
        if not action.destination_type or not action.destination_identity:
            return {
                "destination_id": None,
                "destination_type": action.destination_type,
                "destination_identity": action.destination_identity,
                "trust_tier": 3,
                "known": False,
            }

        row = conn.execute(
            """
            SELECT * FROM destination_trust_tiers
            WHERE destination_type = ? AND destination_identity = ? AND status = 'active'
            """,
            (action.destination_type, action.destination_identity),
        ).fetchone()
        if not row:
            return {
                "destination_id": None,
                "destination_type": action.destination_type,
                "destination_identity": action.destination_identity,
                "trust_tier": 3,
                "known": False,
            }
        destination = self.store._decode_row(row)
        destination["known"] = True
        return destination

    def _resolve_decision(
        self,
        action: GovernedAction,
        destination: dict[str, Any],
        policies: list[dict[str, Any]],
        classification_rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []

        default = self._default_decision(action, destination)
        candidates.append({"decision": default[0], "reason": default[1], "source": "default"})

        for policy in policies:
            layer = policy["policy_type"]
            for rule in policy.get("rules_json", []):
                if self._rule_matches(rule, action, destination):
                    candidates.append(
                        {
                            "decision": rule.get("decision") or rule.get("default") or "allow",
                            "reason": rule.get("rationale") or f"{layer} policy matched",
                            "source": policy["policy_id"],
                        }
                    )

        for rule in classification_rules:
            candidates.extend(self._classification_rule_candidates(rule, action, destination))

        deny = next((candidate for candidate in candidates if candidate["decision"] == "deny"), None)
        if deny:
            winner = deny
        else:
            winner = max(candidates, key=lambda item: DECISION_ORDER.get(item["decision"], 5))

        if winner["decision"] not in DECISIONS:
            winner = {
                "decision": "deny",
                "reason": f"Invalid policy outcome resolved: {winner['decision']}",
                "source": winner.get("source", "invalid_policy"),
            }

        matched = [candidate for candidate in candidates if candidate["source"] != "default"]
        return {
            "decision": winner["decision"],
            "rationale": self._rationale(action, destination, winner, candidates),
            "matched": matched,
        }

    def _classification_rule_candidates(
        self,
        rule: dict[str, Any],
        action: GovernedAction,
        destination: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        destination_keys = {
            destination.get("destination_id"),
            f"{action.destination_type}:{action.destination_identity}",
            action.destination_identity,
        }
        destination_keys.discard(None)

        blocked = set(rule.get("blocked_destinations_json", []))
        allowed = set(rule.get("allowed_destinations_json", []))
        if blocked.intersection(destination_keys):
            candidates.append(
                {
                    "decision": "deny",
                    "reason": "classification rule blocks this destination",
                    "source": rule["rule_id"],
                }
            )

        provider_restrictions = rule.get("override_rules_json", [])
        for override in provider_restrictions:
            if not self._rule_matches(override, action, destination):
                continue
            if "decision" in override:
                candidates.append(
                    {
                        "decision": override["decision"],
                        "reason": override.get("rationale", "classification override matched"),
                        "source": rule["rule_id"],
                    }
                )

        approval = rule.get("approval_requirements_json", {})
        approval_required = bool(approval.get("required"))
        if action.content_classification == "external_confidential":
            if action.origin_entity_ref and rule.get("origin_entity_ref") not in {None, action.origin_entity_ref}:
                candidates.append(
                    {
                        "decision": "deny",
                        "reason": "external confidential origin entity mismatch",
                        "source": rule["rule_id"],
                    }
                )
            if allowed and not allowed.intersection(destination_keys):
                candidates.append(
                    {
                        "decision": "deny",
                        "reason": "external confidential destination is outside entity allowlist",
                        "source": rule["rule_id"],
                    }
                )
            elif approval_required:
                candidates.append(
                    {
                        "decision": "require_primary_user_approval",
                        "reason": "external confidential rule requires primary approval",
                        "source": rule["rule_id"],
                    }
                )
        elif approval_required:
            approver = approval.get("approver", "primary_user")
            candidates.append(
                {
                    "decision": "require_owner_approval"
                    if approver == "owner"
                    else "require_primary_user_approval",
                    "reason": "classification rule requires approval",
                    "source": rule["rule_id"],
                }
            )

        return candidates

    def _rule_matches(self, rule: dict[str, Any], action: GovernedAction, destination: dict[str, Any]) -> bool:
        if rule.get("action") and rule["action"] != action.action_type:
            return False
        if rule.get("actions") and action.action_type not in set(rule["actions"]):
            return False
        if rule.get("classification") and rule["classification"] != action.content_classification:
            return False
        if rule.get("classification_floor"):
            floor = CLASSIFICATION_ORDER[rule["classification_floor"]]
            if CLASSIFICATION_ORDER[action.content_classification] < floor:
                return False
        if rule.get("destination_type") and rule["destination_type"] != action.destination_type:
            return False
        if rule.get("destination_identity") and rule["destination_identity"] != action.destination_identity:
            return False
        if "max_trust_tier" in rule and destination["trust_tier"] > int(rule["max_trust_tier"]):
            return False
        if "min_trust_tier" in rule and destination["trust_tier"] < int(rule["min_trust_tier"]):
            return False
        if rule.get("origin_entity_ref") and rule["origin_entity_ref"] != action.origin_entity_ref:
            return False
        return True

    def _default_decision(self, action: GovernedAction, destination: dict[str, Any]) -> tuple[str, str]:
        classification = action.content_classification
        tier = destination["trust_tier"]
        outbound = action.action_type in GOVERNED_ACTION_TYPES
        if not outbound:
            return "allow", "non-outbound default"
        if classification == "public":
            return ("allow", "public outbound default")
        if classification == "internal":
            return ("allow_with_logging" if tier <= 1 else "require_owner_approval", "internal outbound default")
        if classification == "private":
            return ("require_owner_approval" if tier <= 1 else "require_primary_user_approval", "private outbound default")
        if classification in {"sensitive", "proprietary", "restricted"}:
            return ("deny", f"{classification} outbound default restraint")
        if classification == "external_confidential":
            if not action.origin_entity_ref:
                return ("deny", "external confidential data is missing origin entity binding")
            return ("require_primary_user_approval", "external confidential data requires entity-bound approval")
        return ("deny", "unknown classification default")

    def _create_approval_record(
        self,
        action: GovernedAction,
        decision: dict[str, Any],
        destination: dict[str, Any],
        conn: Any,
    ) -> dict[str, Any]:
        approval_type = "primary_user" if decision["decision"] == "require_primary_user_approval" else "owner"
        approver_user_id = self._primary_user_id(conn) if approval_type == "primary_user" else action.sponsoring_user_id
        return self.store.insert(
            "approval_records",
            {
                "approval_record_id": new_id("apr"),
                "policy_decision_id": decision["policy_decision_id"],
                "requested_by_type": action.actor_type,
                "requested_by_ref": action.actor_ref,
                "approver_user_id": approver_user_id,
                "approval_type": approval_type,
                "scope_json": {
                    "action_type": action.action_type,
                    "object_type": action.object_type,
                    "object_ref": action.object_ref,
                    "destination_type": action.destination_type,
                    "destination_identity": action.destination_identity,
                    "destination_trust_tier": destination["trust_tier"],
                    "classification": action.content_classification,
                    "origin_entity_ref": action.origin_entity_ref,
                },
                "justification_summary": decision["rationale_summary"],
                "status": "requested",
            },
            conn=conn,
            emit_event=False,
        )

    def _primary_user_id(self, conn: Any) -> str | None:
        row = conn.execute("SELECT user_id FROM users WHERE primary_user_flag = 1").fetchone()
        return row["user_id"] if row else None

    def _audit_summary(self, action: GovernedAction, decision: dict[str, Any]) -> str:
        return (
            f"Policy evaluated {action.action_type} for {action.content_classification} "
            f"to {action.destination_type}:{action.destination_identity} as {decision['decision']}"
        )

    def _rationale(
        self,
        action: GovernedAction,
        destination: dict[str, Any],
        winner: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> str:
        return (
            f"{winner['decision']} because {winner['reason']}; action={action.action_type}, "
            f"classification={action.content_classification}, origin={action.origin_entity_ref or 'none'}, "
            f"destination={action.destination_type}:{action.destination_identity}, "
            f"trust_tier={destination['trust_tier']}, candidates={len(candidates)}."
        )
