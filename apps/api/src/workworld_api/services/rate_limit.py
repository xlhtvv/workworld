import hashlib
import socket
from dataclasses import dataclass
from typing import BinaryIO, cast
from urllib.parse import unquote, urlparse

from workworld_api.config import Settings

INCREMENT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
""".strip()


class RateLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitPolicy:
    group: str
    limit: int


def request_policy(method: str, path: str, settings: Settings) -> RateLimitPolicy | None:
    if method in {"GET", "HEAD", "OPTIONS"} or not path.startswith("/v1/"):
        return None
    if path.startswith("/v1/auth/"):
        return RateLimitPolicy("human-auth", settings.rate_limit_auth_requests)
    if path.startswith("/v1/agent-auth/"):
        return RateLimitPolicy("agent-auth", settings.rate_limit_auth_requests)
    if path.startswith("/v1/agent-callbacks/"):
        return RateLimitPolicy("agent-callback", settings.rate_limit_agent_requests)
    return RateLimitPolicy("mutation", settings.rate_limit_mutation_requests)


class RedisRateLimiter:
    def __init__(self, redis_url: str, window_seconds: int) -> None:
        parsed = urlparse(redis_url)
        if parsed.scheme not in {"redis", "rediss"}:
            raise RateLimitError("redis_url_invalid")
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 6379
        self.password = unquote(parsed.password) if parsed.password else None
        self.database = int((parsed.path or "/0").removeprefix("/") or "0")
        self.use_tls = parsed.scheme == "rediss"
        self.window_seconds = window_seconds

    def hit(self, group: str, client: str) -> int:
        identity = hashlib.sha256(client.encode()).hexdigest()[:32]
        key = f"workworld:rate:{group}:{identity}"
        try:
            raw_socket = socket.create_connection((self.host, self.port), timeout=2)
            connection: socket.socket
            if self.use_tls:
                import ssl

                connection = ssl.create_default_context().wrap_socket(
                    raw_socket, server_hostname=self.host
                )
            else:
                connection = raw_socket
            with connection, cast(
                BinaryIO, connection.makefile("rwb", buffering=0)
            ) as stream:
                if self.password:
                    self._command(stream, "AUTH", self.password)
                if self.database:
                    self._command(stream, "SELECT", str(self.database))
                result = self._command(
                    stream,
                    "EVAL",
                    INCREMENT_SCRIPT,
                    "1",
                    key,
                    str(self.window_seconds),
                )
        except (OSError, ValueError) as exc:
            raise RateLimitError("rate_limit_store_unavailable") from exc
        if not isinstance(result, int):
            raise RateLimitError("rate_limit_response_invalid")
        return result

    @classmethod
    def _command(cls, stream: BinaryIO, *parts: str) -> object:
        stream.write(f"*{len(parts)}\r\n".encode())
        for part in parts:
            value = part.encode()
            stream.write(f"${len(value)}\r\n".encode() + value + b"\r\n")
        return cls._response(stream)

    @classmethod
    def _response(cls, stream: BinaryIO) -> object:
        prefix = stream.read(1)
        if not prefix:
            raise RateLimitError("rate_limit_response_missing")
        line = stream.readline()
        if not line.endswith(b"\r\n"):
            raise RateLimitError("rate_limit_response_invalid")
        value = line[:-2]
        if prefix == b"+":
            return value.decode()
        if prefix == b":":
            return int(value)
        if prefix == b"-":
            raise RateLimitError("rate_limit_store_error")
        raise RateLimitError("rate_limit_response_invalid")
