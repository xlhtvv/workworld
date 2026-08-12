#!/usr/bin/env python3
"""Exercise a complete Pull Agent marketplace journey against live services."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

API_URL = os.environ.get("WORKWORLD_API_URL", "http://localhost:8000").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "correct horse battery staple"


class JourneyError(RuntimeError):
    pass


def request_json(
    method: str,
    path: str,
    document: object | None = None,
    token: str | None = None,
    *,
    timeout: float = 30,
) -> Any:
    headers = {"accept": "application/json"}
    data = None
    if document is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(document).encode("utf-8")
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{API_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise JourneyError(f"{method} {path} returned {exc.code}: {body}") from exc
    except OSError as exc:
        raise JourneyError(f"{method} {path} failed: {exc}") from exc


def register(email: str) -> tuple[str, str]:
    response = request_json("POST", "/v1/auth/register", {"email": email, "password": PASSWORD})
    return str(response["access_token"]), str(response["user_id"])


def wait_for(
    description: str,
    probe: Any,
    predicate: Any,
    *,
    timeout: float = 180,
    process: subprocess.Popen[str] | None = None,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            stdout, stderr = process.communicate()
            raise JourneyError(
                f"Pull Agent exited with {process.returncode} while waiting for {description}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            last = probe()
            if predicate(last):
                return last
        except JourneyError as exc:
            last = str(exc)
        time.sleep(1)
    raise JourneyError(f"timed out waiting for {description}; last observation: {last!r}")


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main() -> None:
    suffix = uuid.uuid4().hex[:12]
    provider_token, _provider_id = register(f"pull-provider-{suffix}@example.com")
    publisher_token, _publisher_id = register(f"pull-publisher-{suffix}@example.com")
    provider_before = request_json("GET", "/v1/wallet", token=provider_token)["balances"]
    publisher_before = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]

    agent = request_json(
        "POST",
        "/v1/agents",
        {"name": "Real Pull Journey Agent", "slug": f"real-pull-{suffix}"},
        provider_token,
    )
    agent_id = str(agent["id"])
    credential = request_json(
        "POST", f"/v1/agents/{agent_id}/credentials", {}, provider_token
    )["credential"]
    endpoint = request_json(
        "POST",
        f"/v1/agents/{agent_id}/endpoints",
        {"endpoint_type": "pull"},
        provider_token,
    )
    if endpoint["status"] != "pending":
        raise JourneyError(f"Pull endpoint did not enter pending state: {endpoint!r}")

    offering = request_json(
        "POST",
        "/v1/offerings/versions",
        {
            "offering_id": None,
            "slug": f"real-pull-summary-{suffix}",
            "agent_id": agent_id,
            "schema_id": "text.summarize",
            "schema_version": "1.0",
            "name_i18n": {"en": "Real Pull Summary", "zh": "真实 Pull 摘要"},
            "description_i18n": {
                "en": "A real Pull WebSocket acceptance journey.",
                "zh": "真实 Pull WebSocket 验收旅程。",
            },
            "capabilities": ["deterministic-example"],
            "risk_disclosure": "Deterministic example logic; no hosted model is claimed.",
            "output_license": "publisher-use",
            "sla_seconds": 3600,
            "input_limits": {"max_characters": 500000},
            "estimated_tokens_min": 100,
            "estimated_tokens_max": 5000,
            "estimated_seconds_min": 5,
            "estimated_seconds_max": 600,
            "auto_apply_policy": {"enabled": False},
        },
        provider_token,
    )
    version_id = str(offering["version_id"])

    environment = os.environ.copy()
    python_path = str(ROOT / "sdk" / "python" / "src")
    if environment.get("PYTHONPATH"):
        python_path = f"{python_path}{os.pathsep}{environment['PYTHONPATH']}"
    environment.update(
        {
            "WORKWORLD_API_URL": API_URL,
            "WORKWORLD_AGENT_CREDENTIAL": str(credential),
            "PYTHONPATH": python_path,
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "examples" / "python-pull-text-agent" / "agent.py")],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        detail = wait_for(
            "verified Pull endpoint and online Agent capacity",
            lambda: request_json("GET", f"/v1/agents/{agent_id}", token=provider_token),
            lambda value: (
                (value.get("capacity") or {}).get("status") == "online"
                and any(row.get("status") == "verified" for row in value["endpoints"])
            ),
            process=process,
            timeout=60,
        )
        if detail["capacity"]["max_concurrent_runs"] != 1:
            raise JourneyError(f"unexpected capacity snapshot: {detail['capacity']!r}")

        certification = request_json(
            "POST",
            f"/v1/offerings/versions/{version_id}/certify",
            {},
            provider_token,
            timeout=360,
        )
        if certification["status"] != "passed":
            raise JourneyError(f"real certification did not pass: {certification!r}")
        if len(certification["checks"]) != 11:
            raise JourneyError(f"certification did not execute all checks: {certification!r}")
        published = request_json(
            "POST", f"/v1/offerings/versions/{version_id}/publish", {}, provider_token
        )
        if published["status"] != "published":
            raise JourneyError(f"offering did not publish: {published!r}")

        completion_deadline = datetime.now(UTC) + timedelta(hours=1)
        task = request_json(
            "POST",
            "/v1/tasks",
            {
                "schema_id": "text.summarize",
                "schema_version": "1.0",
                "title": "Real Pull end-to-end summary",
                "public_summary": "Verify real marketplace assignment and settlement.",
                "input_json": {
                    "text": (
                        "WorkWorld assigns a provider-hosted Agent over a durable Pull "
                        "WebSocket. The result is evaluated, accepted, and settled "
                        "through the ledger."
                    ),
                    "max_characters": 1000,
                    "difficulty": "simple",
                },
                "field_visibility": {"text": "winner", "difficulty": "public"},
                "difficulty": "simple",
                "acceptance_rules": {"max_characters": 1000},
                "budget_tokens": 10_000,
                "recruitment_deadline": None,
                "completion_deadline": completion_deadline.isoformat(),
                "assignment_mode": "recommended",
                "data_disclosure_acknowledged": True,
            },
            publisher_token,
        )
        task_id = str(task["id"])
        task_detail = request_json("GET", f"/v1/tasks/{task_id}", token=publisher_token)
        recommendation_ids = {
            str(row["offering_version_id"]) for row in task_detail["recommendations"]
        }
        if version_id not in recommendation_ids:
            raise JourneyError(
                f"published certified online offering was not recommended: {task_detail!r}"
            )

        selection = request_json(
            "POST",
            f"/v1/tasks/{task_id}/offerings/{version_id}/select",
            {},
            publisher_token,
        )
        run_id = str(selection["run_id"])
        held_wallet = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
        if held_wallet["user_held"] != 10_000:
            raise JourneyError(f"task budget was not held atomically: {held_wallet!r}")

        evaluated = wait_for(
            "Agent result and worker evaluation",
            lambda: request_json("GET", f"/v1/runs/{run_id}", token=publisher_token),
            lambda value: value.get("state") == "waiting_for_acceptance",
            process=process,
            timeout=90,
        )
        evaluation = evaluated.get("evaluation")
        if not evaluation or evaluation["mode"] != "mock":
            raise JourneyError(f"evaluation mode was not explicitly mock: {evaluated!r}")
        measured_tokens = evaluated.get("measured_tokens")
        if not isinstance(measured_tokens, int) or measured_tokens <= 0:
            raise JourneyError(f"metering result was invalid: {evaluated!r}")

        events = request_json("GET", f"/v1/runs/{run_id}/events", token=publisher_token)
        event_types = [row["type"] for row in events]
        required = [
            "task.offer",
            "task.accept",
            "task.started",
            "task.progress",
            "task.result_submitted",
            "evaluation.started",
            "evaluation.completed",
        ]
        if any(event_type not in event_types for event_type in required):
            raise JourneyError(f"run event history is incomplete: {event_types!r}")

        accepted = request_json("POST", f"/v1/runs/{run_id}/accept", {}, publisher_token)
        if accepted["state"] != "completed" or accepted["settled_tokens"] != measured_tokens:
            raise JourneyError(f"acceptance did not settle the measured amount: {accepted!r}")

        provider_after = request_json("GET", "/v1/wallet", token=provider_token)["balances"]
        publisher_after = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
        if provider_after["provider_available"] != (
            provider_before["provider_available"] + measured_tokens
        ):
            raise JourneyError(f"provider settlement mismatch: {provider_after!r}")
        if publisher_after["user_held"] != 0:
            raise JourneyError(f"publisher hold was not released: {publisher_after!r}")
        if publisher_after["user_available"] != (
            publisher_before["user_available"] - measured_tokens
        ):
            raise JourneyError(f"publisher settlement mismatch: {publisher_after!r}")

        final_run = request_json("GET", f"/v1/runs/{run_id}", token=publisher_token)
        transaction_types = {row["type"] for row in final_run["ledger_transactions"]}
        if not {"task_hold", "task_settlement"}.issubset(transaction_types):
            raise JourneyError(f"ledger audit trail is incomplete: {final_run!r}")

        print(
            json.dumps(
                {
                    "status": "passed",
                    "transport": "pull_websocket",
                    "certification_checks": len(certification["checks"]),
                    "run_id": run_id,
                    "event_types": event_types,
                    "evaluation_mode": evaluation["mode"],
                    "measured_tokens": measured_tokens,
                    "settlement_verified": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        stop_process(process)


if __name__ == "__main__":
    try:
        main()
    except JourneyError as exc:
        print(f"real Pull journey failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
