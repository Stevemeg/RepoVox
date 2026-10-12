import io
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trustme
from repovox.analysis.common import AnalysisError
from repovox.analysis.transport import GitHubHTTP, PinnedHTTPS, addresses


@pytest.fixture
def tls_server(monkeypatch: pytest.MonkeyPatch):
    """Real HTTPS server; local endpoint is allowed only by this explicit test patch."""
    ca = trustme.CA()
    certificate = ca.issue_cert("api.github.com", "codeload.github.com")
    settings = {
        "status": 200,
        "body": b"{}",
        "type": "application/json",
        "length": True,
        "redirect": "",
        "extra_headers": {},
        "delay": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            time.sleep(settings["delay"])
            self.send_response(settings["status"])
            self.send_header("Content-Type", settings["type"])
            if settings["length"]:
                self.send_header("Content-Length", str(len(settings["body"])))
            if settings["redirect"]:
                self.send_header("Location", settings["redirect"])
            for name, value in settings["extra_headers"].items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(settings["body"])
            except OSError:
                pass

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    certificate.configure_cert(context)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client_context = ssl.create_default_context()
    ca.configure_trust(client_context)
    import repovox.analysis.transport as transport

    monkeypatch.setattr(
        transport,
        "addresses",
        lambda host, *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", server.server_address)],
    )
    monkeypatch.setattr(transport, "public_ip", lambda ip: True)
    monkeypatch.setattr(transport.ssl, "create_default_context", lambda: client_context)
    yield settings
    server.shutdown()
    server.server_close()


def test_real_tls_numeric_connect_and_stream_limit(tls_server: dict) -> None:
    client = GitHubHTTP()
    assert client.get("api.github.com", "/repos/example/demo", 20) == b"{}"
    tls_server.update(body=b"x" * 1024, length=False)
    with pytest.raises(AnalysisError, match="archive_download_limit"):
        client.get("api.github.com", "/repos/example/demo", 100)
    tls_server.update(length=True)
    with pytest.raises(AnalysisError, match="archive_download_limit"):
        client.get("api.github.com", "/repos/example/demo", 100)


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/x",
        "https://10.0.0.1/x",
        "https://169.254.169.254/x",
        "https://[::1]/x",
        "https://codeload.github.com/x",
    ],
)
def test_redirect_never_followed(tls_server: dict, target: str) -> None:
    tls_server.update(status=302, redirect=target)
    with pytest.raises(AnalysisError, match="github_redirect_rejected"):
        GitHubHTTP().get("api.github.com", "/repos/example/demo", 100)


@pytest.mark.parametrize(
    "status,code",
    [
        (404, "repository_not_found"),
        (410, "repository_removed"),
        (429, "github_rate_limited"),
        (503, "github_unavailable"),
        (403, "github_access_denied"),
    ],
)
def test_sanitized_status_codes(tls_server: dict, status: int, code: str) -> None:
    tls_server.update(status=status, body=b"sensitive provider payload")
    with pytest.raises(AnalysisError, match=code) as exc:
        GitHubHTTP().get("api.github.com", "/repos/example/demo", 100)
    assert "sensitive" not in str(exc.value)


def test_unexpected_type_and_archive_stream(tls_server: dict) -> None:
    tls_server.update(type="text/html")
    with pytest.raises(AnalysisError, match="github_response_type"):
        GitHubHTTP().get("api.github.com", "/repos/example/demo", 100)
    tls_server.update(type="application/x-gzip", body=b"bounded-archive-fixture")
    target = io.BytesIO()
    GitHubHTTP().download("/example/demo/tar.gz/" + "a" * 40, target, 100, lambda: None)
    assert target.getvalue() == b"bounded-archive-fixture"


@pytest.mark.parametrize(
    "header,value,code",
    [
        ("Content-Type", "text/html", "github_response_type"),
        ("Content-Encoding", "gzip", "github_response_encoding"),
        ("Content-Length", "1000", "github_response_type"),
        ("Transfer-Encoding", "gzip", "github_response_encoding"),
    ],
)
def test_ambiguous_or_malicious_headers(
    tls_server: dict, header: str, value: str, code: str
) -> None:
    tls_server["extra_headers"] = {header: value}
    with pytest.raises(AnalysisError, match=code):
        GitHubHTTP().get("api.github.com", "/repos/example/demo", 100)


def test_aggregate_timeout(tls_server: dict) -> None:
    tls_server["delay"] = 0.3
    started = time.monotonic()
    with pytest.raises(AnalysisError, match="github_timeout"):
        GitHubHTTP().get("api.github.com", "/repos/example/demo", 100, seconds=0.05)
    assert time.monotonic() - started < 2


def test_production_dns_rebinding_pins_numeric_address(monkeypatch: pytest.MonkeyPatch) -> None:
    queries: list[str] = []
    connected: list[object] = []

    class Wire:
        def settimeout(self, seconds: float) -> None:
            pass

        def connect(self, address: object) -> None:
            connected.append(address)

        def getpeername(self) -> tuple[str, int]:
            return ("140.82.112.6", 443)

        def close(self) -> None:
            pass

    class TLS:
        def wrap_socket(self, raw: object, server_hostname: str) -> object:
            assert server_hostname == "api.github.com"
            return raw

    def lookup(host: str, *args: object, **kw: object) -> list:
        queries.append(host)
        ip = "140.82.112.6" if len(queries) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket, "socket", lambda *a: Wire())
    connection = PinnedHTTPS("api.github.com", timeout=1, context=TLS())
    connection.connect()
    assert queries == ["api.github.com"] and connected == [("140.82.112.6", 443)]
    with pytest.raises(AnalysisError, match="github_address_blocked"):
        addresses("api.github.com")
