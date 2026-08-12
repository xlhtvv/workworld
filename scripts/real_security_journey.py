#!/usr/bin/env python3
"""Verify Task Artifact foreign keys and API throttling on real PostgreSQL/Redis."""

import json
import urllib.error
import urllib.request

from sqlalchemy import func, select
from workworld_api.database import session_factory
from workworld_api.models import Artifact
from workworld_api.task_models import Task, TaskArtifact

API_URL = "http://localhost:8000"


def verify_task_artifacts() -> int:
    with session_factory()() as db:
        count = db.scalar(select(func.count(TaskArtifact.id))) or 0
        if count < 1:
            raise RuntimeError("real_task_artifact_relation_missing")
        rows = list(db.scalars(select(TaskArtifact).limit(100)))
        for row in rows:
            task = db.get(Task, row.task_id)
            artifact = db.get(Artifact, row.artifact_id)
            if task is None or artifact is None or artifact.direction != row.direction:
                raise RuntimeError("task_artifact_foreign_key_or_direction_invalid")
        return count


def verify_rate_limit() -> int:
    payload = json.dumps(
        {"email": "rate-limit-probe@example.com", "password": "not-a-real-password"}
    ).encode()
    limited_at: int | None = None
    for attempt in range(1, 122):
        request = urllib.request.Request(
            f"{API_URL}/v1/auth/login",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except urllib.error.HTTPError as exc:
            document = json.loads(exc.read())
            if exc.code == 429:
                if document != {"detail": "rate_limit_exceeded"}:
                    raise RuntimeError("rate_limit_reason_invalid") from exc
                if exc.headers.get("Retry-After") != "60":
                    raise RuntimeError("rate_limit_retry_header_missing") from exc
                limited_at = attempt
                break
            if exc.code != 401:
                raise RuntimeError(f"unexpected_auth_status:{exc.code}") from exc
    if limited_at is None:
        raise RuntimeError("real_redis_rate_limit_not_enforced")
    with urllib.request.urlopen(f"{API_URL}/health", timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("rate_limit_affected_health_endpoint")
    return limited_at


def main() -> None:
    relation_count = verify_task_artifacts()
    limited_at = verify_rate_limit()
    print(
        json.dumps(
            {
                "task_artifact_relations": relation_count,
                "rate_limit_backend": "redis",
                "limited_at_request": limited_at,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
