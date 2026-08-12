import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.market_models import AgentEndpoint
from workworld_api.services.endpoint_security import (
    PinnedHTTPSVerifier,
    UnsafeEndpoint,
    ValidatedEndpoint,
    configured_endpoint_validator,
)
from workworld_api.services.protocol import ProtocolService

Sender = Callable[[ValidatedEndpoint, object, str], tuple[int, bytes]]
HealthVerifier = Callable[[ValidatedEndpoint, str], None]
EndpointValidator = Callable[[str], ValidatedEndpoint]


class PushDeliveryService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        sender: Sender | None = None,
        health_verifier: HealthVerifier | None = None,
        endpoint_validator: EndpointValidator | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.endpoint_validator = endpoint_validator or configured_endpoint_validator(
            settings.push_allowed_private_hosts
        )
        verifier = PinnedHTTPSVerifier(
            ca_file=settings.push_ca_file or None,
            endpoint_validator=self.endpoint_validator,
        )
        self.sender = sender or verifier.post_signed_json
        self.health_verifier = health_verifier or verifier.verify_challenge

    def check_health(self, now: datetime | None = None) -> tuple[int, int]:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(seconds=self.settings.push_health_interval_seconds)
        endpoints = list(
            self.db.scalars(
                select(AgentEndpoint).where(
                    AgentEndpoint.endpoint_type == "push",
                    AgentEndpoint.status == "verified",
                )
            )
        )
        healthy = 0
        failed = 0
        for endpoint in endpoints:
            if endpoint.url is None:
                continue
            last_health = endpoint.last_health_at
            if last_health is not None:
                comparable_cutoff = (
                    cutoff if last_health.tzinfo is not None else cutoff.replace(tzinfo=None)
                )
                if last_health > comparable_cutoff:
                    continue
            endpoint.last_health_at = current
            try:
                validated = self.endpoint_validator(endpoint.url)
                self.health_verifier(validated, secrets.token_urlsafe(32))
            except (OSError, UnsafeEndpoint, ValueError):
                failed += 1
                continue
            endpoint.resolved_addresses = sorted(validated.addresses)
            healthy += 1
        self.db.commit()
        return healthy, failed

    def dispatch_due(self) -> tuple[int, int]:
        delivered = 0
        failed = 0
        endpoints = list(
            self.db.scalars(
                select(AgentEndpoint).where(
                    AgentEndpoint.endpoint_type == "push",
                    AgentEndpoint.status == "verified",
                )
            )
        )
        protocol = ProtocolService(self.db)
        for endpoint in endpoints:
            if endpoint.url is None:
                continue
            for _outbox, event in protocol.pending_outbox(endpoint.agent_id):
                try:
                    # Resolve every delivery so a DNS change cannot bypass the original SSRF check.
                    validated = self.endpoint_validator(endpoint.url)
                    self.sender(
                        validated,
                        protocol.event_envelope(event, endpoint.agent_id),
                        self.settings.push_signing_secret,
                    )
                except (OSError, UnsafeEndpoint):
                    failed += 1
                    continue
                protocol.acknowledge_outbox(endpoint.agent_id, [event.id])
                delivered += 1
        return delivered, failed
