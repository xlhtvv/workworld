#!/usr/bin/env python3
"""Exercise a complete TypeScript Push Agent journey against live Compose services."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from real_pull_journey import JourneyError, register, request_json, wait_for


def main() -> None:
    runtime_dir = Path(os.environ.get("WORKWORLD_PUSH_RUNTIME_DIR", ""))
    if not runtime_dir.is_dir():
        raise JourneyError("WORKWORLD_PUSH_RUNTIME_DIR must name the mounted runtime directory")
    suffix = uuid.uuid4().hex[:12]
    provider_token, _provider_id = register(f"push-provider-{suffix}@example.com")
    publisher_token, _publisher_id = register(f"push-publisher-{suffix}@example.com")
    provider_before = request_json("GET", "/v1/wallet", token=provider_token)["balances"]
    publisher_before = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
    agent = request_json(
        "POST",
        "/v1/agents",
        {"name": "Real TypeScript Push Agent", "slug": f"real-push-{suffix}"},
        provider_token,
    )
    agent_id = str(agent["id"])
    credential = str(
        request_json(
            "POST", f"/v1/agents/{agent_id}/credentials", {}, provider_token
        )["credential"]
    )
    credential_file = runtime_dir / "credential"
    credential_file.write_text(credential, encoding="utf-8")
    credential_file.chmod(0o600)
    endpoint = request_json(
        "POST",
        f"/v1/agents/{agent_id}/endpoints",
        {"endpoint_type": "push", "url": "https://minio:8443/workworld"},
        provider_token,
        timeout=60,
    )
    if endpoint["status"] != "verified":
        raise JourneyError(f"Push endpoint was not verified: {endpoint!r}")
    offering = request_json(
        "POST",
        "/v1/offerings/versions",
        {
            "offering_id": None,
            "slug": f"real-push-json-{suffix}",
            "agent_id": agent_id,
            "schema_id": "json.transform",
            "schema_version": "1.0",
            "name_i18n": {"en": "Push JSON Transform", "zh": "Push JSON 转换"},
            "description_i18n": {
                "en": "A real signed HTTPS TypeScript Push Agent.",
                "zh": "真实签名 HTTPS TypeScript Push Agent。",
            },
            "capabilities": ["set", "remove"],
            "risk_disclosure": "Deterministic JSON operations; no model is claimed.",
            "output_license": "publisher-use",
            "sla_seconds": 600,
            "input_limits": {"max_operations": 100},
            "estimated_tokens_min": 100,
            "estimated_tokens_max": 2000,
            "estimated_seconds_min": 1,
            "estimated_seconds_max": 120,
            "auto_apply_policy": {"enabled": False},
        },
        provider_token,
    )
    version_id = str(offering["version_id"])
    certification = request_json(
        "POST",
        f"/v1/offerings/versions/{version_id}/certify",
        {},
        provider_token,
        timeout=360,
    )
    if certification["status"] != "passed" or len(certification["checks"]) != 11:
        raise JourneyError(f"Push certification failed: {certification!r}")
    request_json(
        "POST", f"/v1/offerings/versions/{version_id}/publish", {}, provider_token
    )
    agent_detail = request_json("GET", f"/v1/agents/{agent_id}", token=provider_token)
    if (agent_detail.get("capacity") or {}).get("status") != "online":
        raise JourneyError(f"Push Agent capacity was not published: {agent_detail!r}")
    task = request_json(
        "POST",
        "/v1/tasks",
        {
            "schema_id": "json.transform",
            "schema_version": "1.0",
            "title": "Real Push JSON transformation",
            "public_summary": "Exercise signed HTTPS delivery and real callbacks.",
            "input_json": {
                "document": {"keep": True, "nested": {"old": "remove"}},
                "operations": [
                    {"op": "set", "path": "nested.value", "value": 42},
                    {"op": "remove", "path": "nested.old"},
                ],
                "strict": True,
                "difficulty": "simple",
            },
            "field_visibility": {"document": "winner", "operations": "winner"},
            "difficulty": "simple",
            "acceptance_rules": {"operation_postconditions": True},
            "budget_tokens": 10_000,
            "recruitment_deadline": None,
            "completion_deadline": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "assignment_mode": "recommended",
            "data_disclosure_acknowledged": True,
        },
        publisher_token,
    )
    task_id = str(task["id"])
    detail = request_json("GET", f"/v1/tasks/{task_id}", token=publisher_token)
    if version_id not in {row["offering_version_id"] for row in detail["recommendations"]}:
        raise JourneyError(f"Push Offering was not recommended: {detail!r}")
    selected = request_json(
        "POST",
        f"/v1/tasks/{task_id}/offerings/{version_id}/select",
        {},
        publisher_token,
    )
    run_id = str(selected["run_id"])
    evaluated = wait_for(
        "Push result evaluation",
        lambda: request_json("GET", f"/v1/runs/{run_id}", token=publisher_token),
        lambda value: value.get("state") == "waiting_for_acceptance",
        timeout=90,
    )
    events = request_json("GET", f"/v1/runs/{run_id}/events", token=publisher_token)
    submitted = [row for row in events if row["type"] == "task.result_submitted"]
    expected = {"keep": True, "nested": {"value": 42}}
    if len(submitted) != 1 or submitted[0]["payload"]["output"]["document"] != expected:
        raise JourneyError(f"Push transform result mismatch: {submitted!r}")
    accepted = request_json("POST", f"/v1/runs/{run_id}/accept", {}, publisher_token)
    provider_after = request_json("GET", "/v1/wallet", token=provider_token)["balances"]
    publisher_after = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
    measured = int(evaluated["measured_tokens"])
    if accepted["settled_tokens"] != measured:
        raise JourneyError(f"Push settlement mismatch: {accepted!r}")
    if provider_after["provider_available"] - provider_before["provider_available"] != measured:
        raise JourneyError("Push provider did not receive measured settlement")
    if publisher_before["user_available"] - publisher_after["user_available"] != measured:
        raise JourneyError("Push publisher balance did not reflect settlement and refund")
    print(
        json.dumps(
            {
                "status": "passed",
                "agent_runtime": "typescript-push",
                "endpoint": "verified_tls_hmac_nonce",
                "certification_checks": len(certification["checks"]),
                "result": expected,
                "evaluation_mode": evaluated["evaluation"]["mode"],
                "settled_tokens": measured,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except JourneyError as exc:
        print(f"real Push journey failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
