"""Numeric socket connection + original-host TLS; no proxy or automatic redirects."""

import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO

from repovox.analysis.common import AnalysisError

ORIGINS = frozenset({"api.github.com", "codeload.github.com"})
DNS_SLOTS = threading.BoundedSemaphore(4)
SPECIAL = tuple(
    ipaddress.ip_network(value)
    for value in [
        "192.0.0.0/24",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "::/96",
    ]
)


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if any(address.version == network.version and address in network for network in SPECIAL):
        return False
    # Mapped/tunnel encodings have no reason to occur for these approved origins.
    if isinstance(address, ipaddress.IPv6Address) and (
        address.ipv4_mapped or address.sixtofour or address.teredo
    ):
        return False
    return address.is_global and not address.is_multicast


def addresses(host: str, timeout: float = 3) -> list[tuple[Any, ...]]:
    if not DNS_SLOTS.acquire(blocking=False):
        raise AnalysisError("github_unavailable", True)
    result: queue.Queue[Any] = queue.Queue(maxsize=1)

    def lookup() -> None:
        try:
            result.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            result.put(None)
        finally:
            DNS_SLOTS.release()

    threading.Thread(target=lookup, daemon=True).start()
    try:
        answers: list[tuple[Any, ...]] | None = result.get(timeout=max(0.001, timeout))
    except queue.Empty:
        raise AnalysisError("github_timeout", True) from None
    if not answers:
        raise AnalysisError("github_unavailable", True)
    if any(not public_ip(str(answer[4][0])) for answer in answers):
        raise AnalysisError("github_address_blocked")
    return answers[:8]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(
        self, host: str, timeout: float, context: ssl.SSLContext, deadline: float | None = None
    ) -> None:
        super().__init__(host, timeout=timeout, context=context)
        self.tls_context = context
        self.connect_deadline = min(
            deadline or time.monotonic() + timeout, time.monotonic() + timeout
        )

    def connect(self) -> None:
        # DNS is resolved once here, immediately before connect. connect never re-resolves.
        connect_deadline = self.connect_deadline
        answers = addresses(self.host, min(3, connect_deadline - time.monotonic()))
        for family, kind, proto, _, address in answers:
            raw = socket.socket(family, kind, proto)
            if time.monotonic() >= connect_deadline:
                raw.close()
                raise AnalysisError("github_timeout", True)
            raw.settimeout(max(0.001, connect_deadline - time.monotonic()))
            try:
                raw.connect(address)
                if not public_ip(raw.getpeername()[0]):
                    raise AnalysisError("github_address_blocked")
                raw.settimeout(max(0.001, connect_deadline - time.monotonic()))
                self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
                return
            except (OSError, AnalysisError):
                raw.close()
                if not public_ip(str(address[0])):
                    raise AnalysisError("github_address_blocked") from None
        raise AnalysisError("github_unavailable", True)


def response_error(status: int, headers: http.client.HTTPMessage) -> None:
    if 300 <= status < 400:
        raise AnalysisError("github_redirect_rejected")
    if status == 404:
        raise AnalysisError("repository_not_found")
    if status == 410:
        raise AnalysisError("repository_removed")
    if status == 429 or (status == 403 and headers.get("x-ratelimit-remaining") == "0"):
        raise AnalysisError("github_rate_limited", True)
    if status in {401, 403}:
        raise AnalysisError("github_access_denied")
    if status != 200:
        raise AnalysisError("github_unavailable", status >= 500)


class GitHubHTTP:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    @contextmanager
    def stream(
        self,
        host: str,
        path: str,
        limit: int,
        seconds: float = 10,
        checkpoint: Callable[[], None] = lambda: None,
    ) -> Iterator[Iterator[bytes]]:
        if host not in ORIGINS or not path.startswith("/") or any(ord(c) < 33 for c in path):
            raise AnalysisError("github_origin_blocked")
        deadline = time.monotonic() + seconds
        connection = PinnedHTTPS(
            host, timeout=min(3, seconds), context=ssl.create_default_context(), deadline=deadline
        )
        expired = threading.Event()

        def abort() -> None:
            expired.set()
            if connection.sock:
                try:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = threading.Timer(seconds, abort)
        timer.daemon = True
        timer.start()
        headers = {"User-Agent": "RepoVox-static/1", "Accept-Encoding": "identity"}
        if host == "api.github.com":
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
        try:
            checkpoint()
            connection.request("GET", path, headers=headers)
            if expired.is_set():
                raise AnalysisError("github_timeout", True)
            response = connection.getresponse()
            response_error(response.status, response.headers)
            expected = (
                {"application/json"}
                if host == "api.github.com"
                else {
                    "application/x-gzip",
                    "application/gzip",
                    "application/octet-stream",
                }
            )
            if response.headers.get_content_type() not in expected:
                raise AnalysisError("github_response_type")
            if len(response.headers.get_all("Content-Type", [])) != 1:
                raise AnalysisError("github_response_type")
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise AnalysisError("github_response_encoding")
            transfer = response.headers.get("Transfer-Encoding")
            if transfer is not None and transfer.lower() != "chunked":
                raise AnalysisError("github_response_encoding")
            length = response.headers.get("Content-Length")
            if len(response.headers.get_all("Content-Length", [])) > 1 or (
                length and response.headers.get("Transfer-Encoding")
            ):
                raise AnalysisError("github_response_type")
            if length and (not length.isdecimal() or int(length) > limit):
                raise AnalysisError("archive_download_limit")

            def chunks() -> Iterator[bytes]:
                total = 0
                while True:
                    checkpoint()
                    if time.monotonic() >= deadline:
                        raise AnalysisError("github_timeout", True)
                    chunk = response.read1(64 * 1024)
                    if expired.is_set():
                        raise AnalysisError("github_timeout", True)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise AnalysisError("archive_download_limit")
                    yield chunk
                if length is not None and total != int(length):
                    raise AnalysisError("github_truncated_response", True)

            yield chunks()
        except TimeoutError:
            raise AnalysisError("github_timeout", True) from None
        except (OSError, http.client.HTTPException):
            raise AnalysisError(
                "github_timeout" if expired.is_set() else "github_unavailable", True
            ) from None
        finally:
            timer.cancel()
            connection.close()

    def get(self, host: str, path: str, limit: int, seconds: float = 10) -> bytes:
        with self.stream(host, path, limit, seconds) as chunks:
            return b"".join(chunks)

    def download(
        self,
        path: str,
        target: BinaryIO,
        limit: int,
        checkpoint: Callable[[], None],
    ) -> None:
        with self.stream("codeload.github.com", path, limit, 110, checkpoint) as chunks:
            for chunk in chunks:
                target.write(chunk)
