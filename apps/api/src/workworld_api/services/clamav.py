import socket
import struct
from collections.abc import Iterable
from dataclasses import dataclass


class ClamAVError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanVerdict:
    clean: bool
    signature: str | None
    raw: str


def parse_response(response: bytes) -> ScanVerdict:
    raw = response.rstrip(b"\0\n").decode("utf-8", errors="replace")
    if raw.endswith(" OK"):
        return ScanVerdict(clean=True, signature=None, raw=raw)
    if raw.endswith(" FOUND"):
        _, result = raw.split(": ", maxsplit=1)
        return ScanVerdict(clean=False, signature=result.removesuffix(" FOUND"), raw=raw)
    raise ClamAVError(f"unexpected ClamAV response: {raw}")


class ClamAVClient:
    def __init__(self, host: str, port: int, timeout_seconds: float = 30) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def version(self) -> str:
        try:
            with socket.create_connection(
                (self.host, self.port), self.timeout_seconds
            ) as connection:
                connection.sendall(b"zVERSION\0")
                return connection.recv(4096).rstrip(b"\0\n").decode("utf-8", errors="replace")
        except OSError as exc:
            raise ClamAVError("ClamAV unavailable") from exc

    def scan(self, chunks: Iterable[bytes]) -> ScanVerdict:
        try:
            with socket.create_connection(
                (self.host, self.port), self.timeout_seconds
            ) as connection:
                connection.sendall(b"zINSTREAM\0")
                for chunk in chunks:
                    if chunk:
                        connection.sendall(struct.pack("!I", len(chunk)))
                        connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = bytearray()
                while True:
                    block = connection.recv(4096)
                    if not block:
                        break
                    response.extend(block)
                    if b"\0" in block:
                        break
        except OSError as exc:
            raise ClamAVError("ClamAV unavailable") from exc
        return parse_response(bytes(response))
