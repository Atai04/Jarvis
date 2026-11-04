import asyncio
import socket
import ssl
from unittest.mock import AsyncMock

import httpx
import pytest

from app.browser import tools as browser
from app.browser.tools import OpenURLTool
from app.tools.base import PermissionLevel


@pytest.mark.asyncio
async def test_open_url_requires_url():
    tool = OpenURLTool()

    result = await tool.execute({})

    assert result.success is False
    assert result.error == "URL is required."


@pytest.mark.asyncio
async def test_open_url_rejects_invalid_scheme():
    tool = OpenURLTool()

    result = await tool.execute(
        {
            "url": "ftp://example.com",
        }
    )

    assert result.success is False
    assert result.error == "Only HTTP and HTTPS URLs are supported."


@pytest.mark.asyncio
async def test_open_url_rejects_invalid_url():
    tool = OpenURLTool()

    result = await tool.execute(
        {
            "url": "not-a-url",
        }
    )

    assert result.success is False
    assert result.error == "A valid URL is required."


def test_open_url_is_safe():
    tool = OpenURLTool()

    assert tool.permission == PermissionLevel.SAFE


def test_open_url_schema():
    tool = OpenURLTool()

    schema = tool.schema()

    assert schema["type"] == "object"
    assert "url" in schema["properties"]
    assert schema["required"] == ["url"]
    assert schema["additionalProperties"] is False


# Every test below replaces DNS and the HTTP transport; none contacts a server.

PUBLIC_IP = "93.184.216.34"


def answers(*addresses):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))
        for ip in addresses
    ]


@pytest.fixture
async def dns(monkeypatch):
    resolver = AsyncMock(return_value=answers(PUBLIC_IP))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    return resolver


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.reads = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def reply(body=b"Public page", status=200, headers=None):
    return httpx.Response(
        status, headers=headers or {"content-type": "text/plain"}, stream=Chunks([body])
    )


@pytest.fixture
def transport(monkeypatch):
    original_client = httpx.AsyncClient
    requests = []
    options = []
    responses = []

    def handler(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def client(**kwargs):
        options.append(kwargs)
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(browser.httpx, "AsyncClient", client)
    return requests, options, responses


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://x.localhost",
        "http://host.local",
        "http://127.0.0.1",
        "http://0.0.0.0",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254",
        "http://169.254.170.2",
        "http://100.100.100.200",
        "http://168.63.129.16",
        "http://224.0.0.1",
        "http://240.0.0.1",
        "http://255.255.255.255",
        "http://192.0.2.1",
        "http://192.0.0.9",
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",
        "http://[fe80::1%25en0]",
        "http://[2606:4700:4700::1111]",
        "http://user:password@example.com",
        "http://@example.com",
        "file:///etc/passwd",
        "ftp://example.com",
        "https://example.com:8443",
        "http://example.com:0",
        "http://example.com:99999",
        "http://example.com:",
        "http://example.com/%zz",
        "http://%31%32%37.0.0.1",
        "https://example.com\\@127.0.0.1",
        "http://[broken",
        "//example.com",
        "https://example.com\r\nHost: localhost",
        " https://example.com",
        "http://example..com",
        "http://-example.com",
        "http://2130706433",
    ],
)
async def test_rejects_unsafe_urls_without_connecting(url, dns, transport):
    result = await OpenURLTool().execute({"url": url})
    assert not result.success
    assert result.output == ""
    assert "password" not in result.error
    assert transport[0] == []


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        (PUBLIC_IP, "10.0.0.1"),
        ("169.254.169.254",),
        ("100.64.0.1",),
        ("224.0.0.1",),
        ("168.63.129.16",),
    ],
)
async def test_dns_answers_must_all_be_public(addresses, dns, transport):
    dns.return_value = answers(*addresses)
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert not result.success
    assert transport[0] == []


@pytest.mark.parametrize(
    "url", ["http://127.1", "http://0177.0.0.1", "http://0x7f.0.0.1"]
)
async def test_alternative_ip_spellings_are_validated_after_resolution(
    url, dns, transport
):
    dns.return_value = answers("127.0.0.1")
    assert not (await OpenURLTool().execute({"url": url})).success
    assert transport[0] == []


async def test_public_url_is_pinned_and_proxy_environment_ignored(
    dns, transport, monkeypatch
):
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@localhost:8888")
    requests, options, responses = transport
    responses.append(reply())
    result = await OpenURLTool().execute(
        {"url": "https://example.com/path?q=value#fragment"}
    )
    assert result.success and result.output == "Public page"
    assert str(requests[0].url) == f"https://{PUBLIC_IP}/path?q=value"
    assert requests[0].headers["host"] == "example.com"
    assert requests[0].headers["accept-encoding"] == "identity"
    assert requests[0].extensions["sni_hostname"] == "example.com"
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["verify"] is True
    assert requests[0].extensions["timeout"]["connect"] == 5.0
    dns.assert_awaited_once()


async def test_literal_public_ip_needs_no_dns(dns, transport):
    transport[2].append(reply())
    assert (await OpenURLTool().execute({"url": f"http://{PUBLIC_IP}"})).success
    dns.assert_not_awaited()


@pytest.mark.parametrize(
    "destination",
    [
        "https://127.0.0.1",
        "https://169.254.169.254/latest/meta-data",
        "https://user:secret@example.com",
        "file:///etc/passwd",
        "http://example.com",
        "https://example.com:8443",
        "\thttps://example.com",
    ],
)
async def test_unsafe_redirect_is_not_followed(destination, dns, transport):
    transport[2].append(reply(status=302, headers={"location": destination}))
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert not result.success
    assert len(transport[0]) == 1
    assert "secret" not in result.error


async def test_relative_redirect_resolves_original_host_and_drops_cookies(
    dns, transport
):
    requests, options, responses = transport
    responses.extend(
        [
            reply(
                status=302, headers={"location": "/next", "set-cookie": "secret=value"}
            ),
            reply(body=b"Done"),
        ]
    )
    result = await OpenURLTool().execute({"url": "https://example.com/start"})
    assert result.success and result.output == "Done"
    assert [call.args[0] for call in dns.call_args_list] == [
        "example.com",
        "example.com",
    ]
    assert str(requests[1].url) == f"https://{PUBLIC_IP}/next"
    assert "cookie" not in requests[1].headers
    assert len(options) == 2


async def test_redirect_dns_rebinding_blocked(dns, transport):
    dns.side_effect = [answers(PUBLIC_IP), answers("127.0.0.1")]
    transport[2].append(reply(status=302, headers={"location": "/next"}))
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert not result.success
    assert len(transport[0]) == 1


async def test_redirect_limit(dns, transport):
    transport[2].extend(
        reply(status=302, headers={"location": "/again"}) for _ in range(4)
    )
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert "redirect limit" in result.error
    assert len(transport[0]) == 4


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "image/png"},
        {"content-type": "application/octet-stream"},
        {"content-type": "application/not-json"},
        {"content-type": "text/event-stream"},
        {"content-type": "text/plain", "content-encoding": "gzip"},
        {"content-type": "text/plain", "content-length": "1048577"},
        {"content-type": "text/plain", "content-length": "-1"},
        {"content-type": "text/plain", "content-length": "1, 2"},
    ],
)
async def test_rejects_unsafe_response_headers_before_reading(headers, dns, transport):
    response = reply(headers=headers)
    stream = response.stream
    transport[2].append(response)
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert not result.success
    assert stream.reads == 0
    assert stream.closed


async def test_streaming_limit_even_if_length_is_absent_or_false(
    dns, transport, monkeypatch
):
    monkeypatch.setattr(browser, "MAX_RESPONSE_BYTES", 8)
    stream = Chunks([b"1234", b"5678", b"9", b"never-read"])
    transport[2].append(
        httpx.Response(
            200,
            headers={"content-type": "text/plain", "content-length": "1"},
            stream=stream,
        )
    )
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert not result.success and "byte limit" in result.error
    assert stream.reads == 3 and stream.closed


async def test_exact_byte_limit_and_output_truncation(dns, transport, monkeypatch):
    monkeypatch.setattr(browser, "MAX_RESPONSE_BYTES", 20_001)
    transport[2].append(reply(body=b"x" * 20_001))
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert result.success and result.output.startswith("x" * 20_000)
    assert result.output.endswith("[Content truncated by JARVIS.]")


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("secret URL"),
        httpx.ReadTimeout("secret URL"),
        RuntimeError("secret URL"),
    ],
)
async def test_errors_do_not_echo_sensitive_content(failure, dns, transport):
    transport[2].append(failure)
    result = await OpenURLTool().execute({"url": "https://example.com/?token=secret"})
    assert not result.success and "secret" not in result.error


async def test_dns_timeout(dns, transport):
    dns.side_effect = TimeoutError
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert "timed out" in result.error
    assert not transport[0]


async def test_total_timeout_bounds_slow_stream(dns, transport, monkeypatch):
    class SlowStream(Chunks):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b"never"

    monkeypatch.setattr(browser, "TOTAL_TIMEOUT", 0.02)
    stream = SlowStream([])
    transport[2].append(
        httpx.Response(200, headers={"content-type": "text/plain"}, stream=stream)
    )
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert "timed out" in result.error
    assert stream.closed


async def test_real_httpx_transport_connects_only_to_pinned_ip(dns, monkeypatch):
    # Exercise HTTPX + HTTPCore through the TCP boundary, without opening sockets.
    from httpcore._backends.anyio import AnyIOBackend

    tcp_calls = []
    tls_calls = []
    writes = []

    class Wire:
        async def read(self, max_bytes, timeout=None):
            return b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"

        async def write(self, buffer, timeout=None):
            writes.append(buffer)

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert ssl_context.check_hostname
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            tls_calls.append(server_hostname)
            return self

        async def aclose(self):
            pass

        def get_extra_info(self, name):
            return None

    async def connect(self, host, port, **kwargs):
        tcp_calls.append((host, port))
        return Wire()

    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    # A second DNS lookup would return loopback: it must never happen.
    dns.side_effect = [answers(PUBLIC_IP), answers("127.0.0.1")]
    result = await OpenURLTool().execute({"url": "https://example.com"})
    assert result.success and result.output == "OK"
    assert tcp_calls == [(PUBLIC_IP, 443)]
    assert tls_calls == ["example.com"]
    assert b"Host: example.com" in b"".join(writes)
    dns.assert_awaited_once()
