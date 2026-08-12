import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from workworld_api.config import get_settings
from workworld_api.dependencies import Database
from workworld_api.routers.admin import router as admin_router
from workworld_api.routers.agent_auth import router as agent_auth_router
from workworld_api.routers.agent_callbacks import router as agent_callbacks_router
from workworld_api.routers.agent_socket import router as agent_socket_router
from workworld_api.routers.agents import router as agents_router
from workworld_api.routers.artifacts import router as artifacts_router
from workworld_api.routers.auth import router as auth_router
from workworld_api.routers.reviews import router as reviews_router
from workworld_api.routers.runs import router as runs_router
from workworld_api.routers.tasks import router as tasks_router
from workworld_api.routers.wallet import router as wallet_router
from workworld_api.schema_catalog import get_schema, load_catalog
from workworld_api.services.clamav import ClamAVClient
from workworld_api.services.rate_limit import RateLimitError, RedisRateLimiter, request_policy
from workworld_api.services.s3_store import S3ArtifactStore


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    protocol_version: str


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="WorkWorld API",
        version="0.1.0",
        description="Coordination API for provider-hosted Agents.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )
    limiter = RedisRateLimiter(settings.redis_url, settings.rate_limit_window_seconds)

    @application.middleware("http")
    async def enforce_rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if settings.rate_limit_enabled:
            policy = request_policy(request.method, request.url.path, settings)
            if policy is not None:
                client = request.client.host if request.client is not None else "unknown"
                try:
                    count = await asyncio.to_thread(limiter.hit, policy.group, client)
                except RateLimitError:
                    return JSONResponse(
                        status_code=503,
                        content={"detail": "rate_limit_store_unavailable"},
                    )
                if count > policy.limit:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "rate_limit_exceeded"},
                        headers={"Retry-After": str(settings.rate_limit_window_seconds)},
                    )
        return await call_next(request)
    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(artifacts_router)
    application.include_router(agents_router)
    application.include_router(agent_auth_router)
    application.include_router(agent_callbacks_router)
    application.include_router(agent_socket_router)
    application.include_router(tasks_router)
    application.include_router(runs_router)
    application.include_router(wallet_router)
    application.include_router(reviews_router)

    @application.get("/health", tags=["system"], response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.service_name,
            protocol_version=settings.protocol_version,
        )

    @application.get("/health/ready", tags=["system"])
    def readiness(db: Database) -> dict[str, object]:
        checks: dict[str, str] = {}
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
            S3ArtifactStore(
                settings.s3_endpoint_url,
                settings.s3_access_key,
                settings.s3_secret_key,
                settings.s3_bucket,
            ).check()
            checks["object_store"] = "ok"
            checks["clamav"] = ClamAVClient(
                settings.clamav_host, settings.clamav_port
            ).version()
            parsed = urlparse(settings.redis_url)
            with socket.create_connection(
                (parsed.hostname or "localhost", parsed.port or 6379), timeout=2
            ) as connection:
                connection.sendall(b"*1\r\n$4\r\nPING\r\n")
                if not connection.recv(32).startswith(b"+PONG"):
                    raise OSError("redis_ping_failed")
            checks["redis"] = "ok"
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "checks": checks, "error": type(exc).__name__},
            ) from exc
        return {"status": "ready", "checks": checks}

    @application.get("/v1/schemas", tags=["schemas"])
    async def schemas() -> dict[str, object]:
        return load_catalog()

    @application.get("/v1/schemas/{schema_id}/{version}", tags=["schemas"])
    async def schema_detail(schema_id: str, version: str) -> dict[str, object]:
        definition = get_schema(schema_id, version)
        if definition is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="schema_version_not_found")
        return definition

    return application


app = create_app()
