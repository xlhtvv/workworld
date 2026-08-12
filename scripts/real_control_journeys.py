#!/usr/bin/env python3
"""Exercise clarification defaults and one-rework settlement on live services."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from real_open_call_journey import Candidate, provision_candidate
from real_pull_journey import JourneyError, register, request_json, stop_process, wait_for


def create_recommended_run(
    publisher_token: str, candidate: Candidate, suffix: str, focus: str
) -> tuple[str, str]:
    task = request_json(
        "POST",
        "/v1/tasks",
        {
            "schema_id": "text.summarize",
            "schema_version": "1.0",
            "title": f"Control journey {focus}",
            "public_summary": "Exercise a durable Run control transition.",
            "input_json": {
                "text": f"Control journey source {suffix} for {focus}.",
                "max_characters": 1000,
                "focus": focus,
                "difficulty": "simple",
            },
            "field_visibility": {"focus": "winner", "difficulty": "public"},
            "difficulty": "simple",
            "acceptance_rules": {"max_characters": 1000},
            "budget_tokens": 10_000,
            "recruitment_deadline": None,
            "completion_deadline": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "assignment_mode": "recommended",
            "data_disclosure_acknowledged": True,
        },
        publisher_token,
    )
    task_id = str(task["id"])
    detail = request_json("GET", f"/v1/tasks/{task_id}", token=publisher_token)
    if candidate.version_id not in {
        row["offering_version_id"] for row in detail["recommendations"]
    }:
        raise JourneyError(f"control candidate was not recommended: {detail!r}")
    selected = request_json(
        "POST",
        f"/v1/tasks/{task_id}/offerings/{candidate.version_id}/select",
        {},
        publisher_token,
    )
    return task_id, str(selected["run_id"])


def event_types(run_id: str, publisher_token: str) -> list[str]:
    events = request_json("GET", f"/v1/runs/{run_id}/events", token=publisher_token)
    return [str(row["type"]) for row in events]


def require_count(values: list[str], value: str, count: int) -> None:
    if values.count(value) != count:
        raise JourneyError(f"expected {count} {value} events, observed {values!r}")


def upload_verified_output(provider_token: str, task_id: str) -> dict[str, Any]:
    payload = b"Verified partial result produced before cancellation.\n"
    artifact = request_json(
        "POST",
        "/v1/artifacts/uploads",
        {
            "original_name": "partial-result.txt",
            "kind": "text",
            "direction": "output",
            "mime_type": "text/plain",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "task_id": task_id,
        },
        provider_token,
    )
    artifact_id = str(artifact["id"])
    signed = request_json(
        "POST", f"/v1/artifacts/{artifact_id}/parts/1", token=provider_token
    )
    upload = urllib.request.Request(str(signed["url"]), data=payload, method="PUT")
    with urllib.request.urlopen(upload, timeout=120) as response:
        if response.status != 200:
            raise JourneyError(f"partial artifact upload returned {response.status}")
    completed = request_json(
        "POST",
        f"/v1/artifacts/{artifact_id}/complete",
        {"parts": []},
        provider_token,
        timeout=180,
    )
    if completed["scan_status"] != "clean":
        raise JourneyError(f"partial artifact was not verified: {completed!r}")
    return dict(completed)


def main() -> None:
    suffix = uuid.uuid4().hex[:12]
    publisher_token, _publisher_id = register(f"controls-publisher-{suffix}@example.com")
    candidate = provision_candidate("controls", suffix)
    try:
        _task_id, clarification_run = create_recommended_run(
            publisher_token, candidate, suffix, "clarification-default-e2e"
        )
        clarification = wait_for(
            "blocking clarification request",
            lambda: request_json(
                "GET", f"/v1/runs/{clarification_run}", token=publisher_token
            ),
            lambda value: value.get("state") == "waiting_for_clarification",
            process=candidate.process,
            timeout=45,
        )
        if len(clarification["clarifications"]) != 1:
            raise JourneyError(f"clarification record missing: {clarification!r}")
        clarification_done = wait_for(
            "expired clarification default and continued evaluation",
            lambda: request_json(
                "GET", f"/v1/runs/{clarification_run}", token=publisher_token
            ),
            lambda value: value.get("state") == "waiting_for_acceptance",
            process=candidate.process,
            timeout=90,
        )
        if clarification_done["clarifications"][0]["status"] != "defaulted":
            raise JourneyError(f"clarification did not use its default: {clarification_done!r}")
        clarification_events = event_types(clarification_run, publisher_token)
        for required in ("clarification.requested", "clarification.timed_out"):
            require_count(clarification_events, required, 1)
        request_json("POST", f"/v1/runs/{clarification_run}/accept", {}, publisher_token)

        _task_id, rework_run = create_recommended_run(
            publisher_token, candidate, suffix, "rework-e2e"
        )
        wait_for(
            "first evaluation round",
            lambda: request_json("GET", f"/v1/runs/{rework_run}", token=publisher_token),
            lambda value: value.get("state") == "waiting_for_acceptance",
            process=candidate.process,
            timeout=90,
        )
        rework = request_json(
            "POST",
            f"/v1/runs/{rework_run}/rework",
            {
                "reason": "Repeat the summary against the max-character acceptance rule.",
                "acceptance_rule_refs": ["max_characters"],
            },
            publisher_token,
        )
        if rework["run_id"] != rework_run:
            raise JourneyError(f"rework was not attached to its Run: {rework!r}")
        second_round = wait_for(
            "second evaluation round after rework",
            lambda: request_json("GET", f"/v1/runs/{rework_run}", token=publisher_token),
            lambda value: (
                value.get("state") == "waiting_for_acceptance"
                and value.get("rework_count") == 1
            ),
            process=candidate.process,
            timeout=90,
        )
        rework_events = event_types(rework_run, publisher_token)
        require_count(rework_events, "task.result_submitted", 2)
        require_count(rework_events, "evaluation.completed", 2)
        require_count(rework_events, "task.rework_requested", 1)
        accepted = request_json("POST", f"/v1/runs/{rework_run}/accept", {}, publisher_token)
        if accepted["settled_tokens"] != second_round["measured_tokens"]:
            raise JourneyError(f"reworked Run settlement mismatch: {accepted!r}")
        review = request_json(
            "POST",
            f"/v1/runs/{rework_run}/review",
            {"rating": 5, "body": "Verified one-rework delivery."},
            publisher_token,
        )
        reply = request_json(
            "POST",
            f"/v1/reviews/{review['id']}/reply",
            {"body": "Acknowledged by the provider."},
            candidate.token,
        )
        reputation: dict[str, Any] = request_json(
            "GET", f"/v1/providers/{review['provider_id']}/reputation"
        )
        if reply["review_id"] != review["id"] or reputation["average_rating"] != 5:
            raise JourneyError(f"review or reputation did not persist: {reputation!r}")

        provider_before_cancel = request_json(
            "GET", "/v1/wallet", token=candidate.token
        )["balances"]["provider_available"]
        publisher_before_cancel = request_json(
            "GET", "/v1/wallet", token=publisher_token
        )["balances"]["user_available"]
        cancel_task, cancel_run = create_recommended_run(
            publisher_token, candidate, suffix, "cancel-partial-e2e"
        )
        wait_for(
            "cancellable running Run",
            lambda: request_json("GET", f"/v1/runs/{cancel_run}", token=publisher_token),
            lambda value: value.get("state") == "running",
            process=candidate.process,
            timeout=45,
        )
        partial_artifact = upload_verified_output(candidate.token, cancel_task)
        request_json("POST", f"/v1/runs/{cancel_run}/cancel", {}, publisher_token)
        cancelled = wait_for(
            "partial cancellation settlement",
            lambda: request_json("GET", f"/v1/runs/{cancel_run}", token=publisher_token),
            lambda value: (
                value.get("state") == "cancelled"
                and any(
                    row.get("type") == "task_partial_settlement"
                    for row in value.get("ledger_transactions", [])
                )
            ),
            process=candidate.process,
            timeout=60,
        )
        provider_after_cancel = request_json(
            "GET", "/v1/wallet", token=candidate.token
        )["balances"]["provider_available"]
        publisher_after_cancel = request_json(
            "GET", "/v1/wallet", token=publisher_token
        )["balances"]["user_available"]
        partial_amount = provider_after_cancel - provider_before_cancel
        if not 0 < partial_amount < 10_000:
            raise JourneyError(f"invalid partial settlement amount: {partial_amount}")
        if publisher_before_cancel - publisher_after_cancel != partial_amount:
            raise JourneyError("publisher refund did not match partial settlement")
        cancel_events = event_types(cancel_run, publisher_token)
        for required in ("task.cancel_requested", "task.cancelled"):
            require_count(cancel_events, required, 1)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "journeys": [
                        "clarification_default",
                        "one_rework_review",
                        "partial_cancellation",
                    ],
                    "clarification_defaulted": True,
                    "rework_count": 1,
                    "evaluation_rounds": 2,
                    "review_rating": 5,
                    "provider_reply": True,
                    "partial_artifact_id": partial_artifact["id"],
                    "partial_settled_tokens": partial_amount,
                    "refund_verified": True,
                    "cancelled_state": cancelled["state"],
                },
                sort_keys=True,
            )
        )
    finally:
        stop_process(candidate.process)


if __name__ == "__main__":
    try:
        main()
    except JourneyError as exc:
        print(f"real control journeys failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
