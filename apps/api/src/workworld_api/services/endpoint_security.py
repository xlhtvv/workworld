import hashlib
import hmac
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse


class UnsafeEndpoint(ValueError):
    pass


Resolver = Callable[..., Any]


def configured_endpoint_validator(
    allowed_private_hosts: list[str],
) -> Callable[[str], "ValidatedEndpoint"]:
    allowed = frozenset(allowed_private_hosts)
    return lambda url: validate_https_endpoint(url, allowed_private_hosts=allowed)


@dataclass(frozen=True)
class ValidatedEndpoint:
    url: str
    host: str
    port: int
    addresses: frozenset[str]


def validate_https_endpoint(
    url: str,
    resolver: Resolver = socket.getaddrinfo,
    *,
    allowed_private_hosts: frozenset[str] = frozenset(),
) -> ValidatedEndpoint:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname is None:
        raise UnsafeEndpoint("https_endpoint_required")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise UnsafeEndpoint("endpoint_url_components_forbidden")
    port = parsed.port or 443
    try:
        results = resolver(parsed.hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeEndpoint("endpoint_dns_failed") from exc
    addresses = frozenset(str(item[4][0]) for item in results)
    if not addresses:
        raise UnsafeEndpoint("endpoint_dns_empty")
    private_allowed = parsed.hostname in allowed_private_hosts
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global and not private_allowed:
            raise UnsafeEndpoint("endpoint_address_forbidden")
    normalized = parsed._replace(fragment="").geturl()
    return ValidatedEndpoint(normalized, parsed.hostname, port, addresses)


def canonical_json(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign_webhook(secret: str, timestamp: int, nonce: str, body: bytes) -> str:
    message = f"{timestamp}.{nonce}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_webhook(
    secret: str,
    timestamp: int,
    nonce: str,
    body: bytes,
    signature: str,
    *,
    now: datetime | None = None,
    max_skew_seconds: int = 300,
) -> None:
    current = int((now or datetime.now(UTC)).timestamp())
    if abs(current - timestamp) > max_skew_seconds:
        raise ValueError("webhook_timestamp_out_of_range")
    expected = sign_webhook(secret, timestamp, nonce, body)
    if not hmac.compare_digest(expected, signature):
        raise ValueError("webhook_signature_invalid")


class PinnedHTTPSVerifier:
    def __init__(
        self,
        timeout_seconds: float = 10,
        max_redirects: int = 3,
        ca_file: str | None = None,
        endpoint_validator: Callable[[str], ValidatedEndpoint] = validate_https_endpoint,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.tls = ssl.create_default_context(cafile=ca_file)
        self.endpoint_validator = endpoint_validator

    def verify_challenge(self, endpoint: ValidatedEndpoint, challenge: str) -> None:
        body = canonical_json({"challenge": challenge})
        current = endpoint
        for redirect_count in range(self.max_redirects + 1):
            status, headers, response_body = self._post(current, body)
            if status in {307, 308}:
                if redirect_count == self.max_redirects:
                    raise UnsafeEndpoint("endpoint_redirect_limit")
                location = headers.get("location")
                if not location:
                    raise UnsafeEndpoint("endpoint_redirect_missing_location")
                current = self.endpoint_validator(urljoin(current.url, location))
                continue
            if status != 200:
                raise UnsafeEndpoint("endpoint_challenge_http_error")
            try:
                response = json.loads(response_body)
            except json.JSONDecodeError as exc:
                raise UnsafeEndpoint("endpoint_challenge_invalid_json") from exc
            if not isinstance(response, dict) or not hmac.compare_digest(
                str(response.get("challenge", "")), challenge
            ):
                raise UnsafeEndpoint("endpoint_challenge_mismatch")
            return
        raise UnsafeEndpoint("endpoint_redirect_limit")

    def post_signed_json(
        self, endpoint: ValidatedEndpoint, payload: object, secret: str
    ) -> tuple[int, bytes]:
        body = canonical_json(payload)
        timestamp = int(datetime.now(UTC).timestamp())
        nonce = secrets.token_urlsafe(24)
        signature = sign_webhook(secret, timestamp, nonce, body)
        headers = {
            "X-WorkWorld-Timestamp": str(timestamp),
            "X-WorkWorld-Nonce": nonce,
            "X-WorkWorld-Signature": signature,
        }
        current = endpoint
        for redirect_count in range(self.max_redirects + 1):
            status, response_headers, response_body = self._post(current, body, headers)
            if status in {307, 308}:
                if redirect_count == self.max_redirects:
                    raise UnsafeEndpoint("endpoint_redirect_limit")
                location = response_headers.get("location")
                if not location:
                    raise UnsafeEndpoint("endpoint_redirect_missing_location")
                current = self.endpoint_validator(urljoin(current.url, location))
                continue
            if not 200 <= status < 300:
                raise UnsafeEndpoint("endpoint_delivery_http_error")
            return status, response_body
        raise UnsafeEndpoint("endpoint_redirect_limit")

    def _post(
        self,
        endpoint: ValidatedEndpoint,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(endpoint.url)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        last_error: OSError | None = None
        for address in sorted(endpoint.addresses):
            try:
                with (
                    socket.create_connection(
                        (address, endpoint.port), timeout=self.timeout_seconds
                    ) as connection,
                    self.tls.wrap_socket(connection, server_hostname=endpoint.host) as secured,
                ):
                    extra_headers = "".join(
                        f"{key}: {value}\r\n" for key, value in (headers or {}).items()
                    )
                    request = (
                        f"POST {path} HTTP/1.1\r\n"
                        f"Host: {endpoint.host}\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"{extra_headers}"
                        "Connection: close\r\n\r\n"
                    ).encode() + body
                    secured.sendall(request)
                    response = http.client.HTTPResponse(secured)
                    response.begin()
                    payload = response.read(65_537)
                    if len(payload) > 65_536:
                        raise UnsafeEndpoint("endpoint_response_too_large")
                    return (
                        response.status,
                        {key.lower(): value for key, value in response.getheaders()},
                        payload,
                    )
            except OSError as exc:
                last_error = exc
        raise UnsafeEndpoint("endpoint_connection_failed") from last_error
