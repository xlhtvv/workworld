#!/usr/bin/env python3
"""Exercise sealed multi-provider recruitment against the live Compose stack."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from real_pull_journey import (
    API_URL,
    ROOT,
    JourneyError,
    register,
    request_json,
    stop_process,
    wait_for,
)


@dataclass(frozen=True)
class Candidate:
    token: str
    version_id: str
    process: subprocess.Popen[str]
    provider_balance_before: int


def provision_candidate(label: str, suffix: str) -> Candidate:
    token, _user_id = register(f"open-{label}-{suffix}@example.com")
    balance = request_json("GET", "/v1/wallet", token=token)["balances"]
    agent = request_json(
        "POST",
        "/v1/agents",
        {"name": f"Open Call {label} Agent", "slug": f"open-{label}-{suffix}"},
        token,
    )
    agent_id = str(agent["id"])
    credential = request_json(
        "POST", f"/v1/agents/{agent_id}/credentials", {}, token
    )["credential"]
    endpoint = request_json(
        "POST",
        f"/v1/agents/{agent_id}/endpoints",
        {"endpoint_type": "pull"},
        token,
    )
    if endpoint["status"] != "pending":
        raise JourneyError(f"candidate {label} endpoint was not pending: {endpoint!r}")
    offering = request_json(
        "POST",
        "/v1/offerings/versions",
        {
            "offering_id": None,
            "slug": f"open-summary-{label}-{suffix}",
            "agent_id": agent_id,
            "schema_id": "text.summarize",
            "schema_version": "1.0",
            "name_i18n": {"en": f"Open Summary {label}", "zh": f"公开招募摘要 {label}"},
            "description_i18n": {
                "en": "A certified provider-hosted Pull candidate.",
                "zh": "经过认证的提供方托管 Pull 候选服务。",
            },
            "capabilities": ["sealed-application"],
            "risk_disclosure": "Deterministic example; no hosted model is claimed.",
            "output_license": "publisher-use",
            "sla_seconds": 1800,
            "input_limits": {"max_characters": 500000},
            "estimated_tokens_min": 100,
            "estimated_tokens_max": 4000,
            "estimated_seconds_min": 5,
            "estimated_seconds_max": 600,
            "auto_apply_policy": {"enabled": False},
        },
        token,
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
    wait_for(
        f"candidate {label} endpoint and capacity",
        lambda: request_json("GET", f"/v1/agents/{agent_id}", token=token),
        lambda value: (
            (value.get("capacity") or {}).get("status") == "online"
            and any(row.get("status") == "verified" for row in value["endpoints"])
        ),
        process=process,
        timeout=60,
    )
    certification = request_json(
        "POST",
        f"/v1/offerings/versions/{version_id}/certify",
        {},
        token,
        timeout=360,
    )
    if certification["status"] != "passed" or len(certification["checks"]) != 11:
        raise JourneyError(f"candidate {label} certification failed: {certification!r}")
    published = request_json(
        "POST", f"/v1/offerings/versions/{version_id}/publish", {}, token
    )
    if published["status"] != "published":
        raise JourneyError(f"candidate {label} did not publish: {published!r}")
    return Candidate(token, version_id, process, int(balance["provider_available"]))


def application_document(version_id: str, valid_until: datetime, label: str) -> dict[str, Any]:
    return {
        "offering_version_id": version_id,
        "estimated_tokens_min": 100,
        "estimated_tokens_max": 4000,
        "estimated_completion_seconds": 600,
        "message": f"Sealed candidate {label}",
        "valid_until": valid_until.isoformat(),
    }


def main() -> None:
    suffix = uuid.uuid4().hex[:12]
    publisher_token, _publisher_id = register(f"open-publisher-{suffix}@example.com")
    publisher_before = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
    candidates: list[Candidate] = []
    try:
        candidates.append(provision_candidate("alpha", suffix))
        candidates.append(provision_candidate("beta", suffix))
        now = datetime.now(UTC)
        recruitment_deadline = now + timedelta(hours=1)
        task = request_json(
            "POST",
            "/v1/tasks",
            {
                "schema_id": "text.summarize",
                "schema_version": "1.0",
                "title": "Sealed multi-provider recruitment",
                "public_summary": "Choose one provider without exposing competing bids.",
                "input_json": {
                    "text": (
                        "Two providers apply independently. Only one receives the task "
                        "and settlement."
                    ),
                    "max_characters": 1000,
                    "difficulty": "simple",
                },
                "field_visibility": {"text": "applicants", "difficulty": "public"},
                "difficulty": "simple",
                "acceptance_rules": {"max_characters": 1000},
                "budget_tokens": 10_000,
                "recruitment_deadline": recruitment_deadline.isoformat(),
                "completion_deadline": (now + timedelta(hours=2)).isoformat(),
                "assignment_mode": "open_call",
                "data_disclosure_acknowledged": True,
            },
            publisher_token,
        )
        task_id = str(task["id"])
        valid_until = now + timedelta(minutes=30)
        applications = [
            request_json(
                "POST",
                f"/v1/tasks/{task_id}/applications",
                application_document(candidate.version_id, valid_until, label),
                candidate.token,
            )
            for candidate, label in zip(candidates, ("alpha", "beta"), strict=True)
        ]
        application_ids = {str(row["id"]) for row in applications}
        for candidate, own in zip(candidates, applications, strict=True):
            own_rows = request_json("GET", "/v1/applications", token=candidate.token)
            if [row["id"] for row in own_rows] != [own["id"]]:
                raise JourneyError(f"candidate observed another sealed application: {own_rows!r}")
            public_detail = request_json(
                "GET", f"/v1/tasks/{task_id}", token=candidate.token
            )
            if "applications" in public_detail:
                raise JourneyError(f"sealed applications leaked in task detail: {public_detail!r}")
        publisher_detail = request_json(
            "GET", f"/v1/tasks/{task_id}", token=publisher_token
        )
        if {row["id"] for row in publisher_detail["applications"]} != application_ids:
            raise JourneyError(f"publisher did not receive both applications: {publisher_detail!r}")

        selected = request_json(
            "POST",
            f"/v1/tasks/{task_id}/applications/{applications[0]['id']}/select",
            {},
            publisher_token,
        )
        run_id = str(selected["run_id"])
        evaluated = wait_for(
            "selected sealed candidate execution",
            lambda: request_json("GET", f"/v1/runs/{run_id}", token=publisher_token),
            lambda value: value.get("state") == "waiting_for_acceptance",
            process=candidates[0].process,
            timeout=90,
        )
        measured = evaluated["measured_tokens"]
        if evaluated["evaluation"]["mode"] != "mock" or not isinstance(measured, int):
            raise JourneyError(f"open-call evaluation was invalid: {evaluated!r}")
        request_json("POST", f"/v1/runs/{run_id}/accept", {}, publisher_token)
        after_selection = request_json(
            "GET", f"/v1/tasks/{task_id}", token=publisher_token
        )["applications"]
        statuses = {row["id"]: row["status"] for row in after_selection}
        expected_statuses = {
            applications[0]["id"]: "selected",
            applications[1]["id"]: "not_selected",
        }
        if statuses != expected_statuses:
            raise JourneyError(f"application winner states were not sealed/final: {statuses!r}")
        winner_balance = request_json("GET", "/v1/wallet", token=candidates[0].token)[
            "balances"
        ]["provider_available"]
        loser_balance = request_json("GET", "/v1/wallet", token=candidates[1].token)[
            "balances"
        ]["provider_available"]
        publisher_after = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
        if winner_balance != candidates[0].provider_balance_before + measured:
            raise JourneyError("selected provider did not receive settlement")
        if loser_balance != candidates[1].provider_balance_before:
            raise JourneyError("losing provider received settlement")
        if publisher_after["user_available"] != publisher_before["user_available"] - measured:
            raise JourneyError("publisher open-call settlement mismatch")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "journey": "sealed_open_call",
                    "applications": 2,
                    "selected": 1,
                    "not_selected": 1,
                    "evaluation_mode": "mock",
                    "measured_tokens": measured,
                    "settlement_verified": True,
                },
                sort_keys=True,
            )
        )
    finally:
        for candidate in candidates:
            stop_process(candidate.process)


if __name__ == "__main__":
    try:
        main()
    except JourneyError as exc:
        print(f"real open-call journey failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
