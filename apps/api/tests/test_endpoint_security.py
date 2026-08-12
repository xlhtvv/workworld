import socket
from datetime import UTC, datetime

import pytest
from workworld_api.services.endpoint_security import (
    UnsafeEndpoint,
    sign_webhook,
    validate_https_endpoint,
    verify_webhook,
)


def resolver_for(*addresses: str):
    def resolve(host: str, port: int, family: int, sock_type: int):
        del host, family
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                sock_type,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolve


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "172.16.0.1", "192.168.1.1", "::1", "fe80::1"],
)
def test_push_endpoint_rejects_non_global_addresses(address: str) -> None:
    with pytest.raises(UnsafeEndpoint, match="endpoint_address_forbidden"):
        validate_https_endpoint("https://provider.example/hook", resolver_for(address))


def test_push_endpoint_requires_https_and_all_addresses_safe() -> None:
    with pytest.raises(UnsafeEndpoint, match="https_endpoint_required"):
        validate_https_endpoint("http://provider.example/hook", resolver_for("8.8.8.8"))
    with pytest.raises(UnsafeEndpoint, match="endpoint_address_forbidden"):
        validate_https_endpoint(
            "https://provider.example/hook", resolver_for("8.8.8.8", "127.0.0.1")
        )
    validated = validate_https_endpoint(
        "https://provider.example/hook", resolver_for("8.8.8.8", "2001:4860:4860::8888")
    )
    assert validated.addresses == frozenset({"8.8.8.8", "2001:4860:4860::8888"})


def test_explicit_local_acceptance_host_can_use_private_address() -> None:
    validated = validate_https_endpoint(
        "https://push-agent:8443/workworld",
        resolver_for("172.20.0.8"),
        allowed_private_hosts=frozenset({"push-agent"}),
    )
    assert validated.addresses == frozenset({"172.20.0.8"})
    with pytest.raises(UnsafeEndpoint, match="endpoint_address_forbidden"):
        validate_https_endpoint(
            "https://other-agent:8443/workworld",
            resolver_for("172.20.0.8"),
            allowed_private_hosts=frozenset({"push-agent"}),
        )


def test_webhook_signature_covers_timestamp_nonce_and_exact_body() -> None:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    timestamp = int(now.timestamp())
    body = b'{"run_id":"run_1"}'
    signature = sign_webhook("secret", timestamp, "nonce-1", body)
    verify_webhook("secret", timestamp, "nonce-1", body, signature, now=now)
    with pytest.raises(ValueError, match="signature_invalid"):
        verify_webhook("secret", timestamp, "nonce-2", body, signature, now=now)
    with pytest.raises(ValueError, match="timestamp_out_of_range"):
        verify_webhook("secret", timestamp - 301, "nonce-1", body, signature, now=now)
