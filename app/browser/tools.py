import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.tools.base import PermissionLevel, Tool, ToolResult

MAX_RESPONSE_BYTES = 1_048_576
MAX_REDIRECTS = 3
TOTAL_TIMEOUT = 30.0
DNS_TIMEOUT = 5.0
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0, pool=5.0)
TEXT_TYPES = {
    "text/plain",
    "text/html",
    "text/css",
    "text/csv",
    "text/markdown",
    "text/xml",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}


class UnsafeURL(ValueError):
    """Only fixed, credential-free messages may be passed to this exception."""


def _parse_url(value: str) -> httpx.URL:
    if (
        len(value) > 8192
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
        or "\\" in value
        or re.search(r"%(?![0-9a-fA-F]{2})", value)
    ):
        raise UnsafeURL("A valid URL is required.")
    try:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
            raise UnsafeURL("Only HTTP and HTTPS URLs are supported.")
        if not parsed.netloc or not parsed.hostname:
            raise UnsafeURL("A valid URL is required.")
        if "@" in parsed.netloc:
            raise UnsafeURL("URLs with embedded credentials are not allowed.")
        if "%" in parsed.netloc or parsed.netloc.endswith(":"):
            raise UnsafeURL("A valid URL is required.")
        url = httpx.URL(value)
        if url.scheme not in {"http", "https"}:
            raise UnsafeURL("Only HTTP and HTTPS URLs are supported.")
        host = url.raw_host.decode("ascii").lower()
        if ":" in host:
            raise UnsafeURL("Only public IPv4 destinations are supported.")
        if url.port not in (None, 80 if url.scheme == "http" else 443):
            raise UnsafeURL("Only standard HTTP and HTTPS ports are allowed.")
        host = host.removesuffix(".")
        if len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            raise UnsafeURL("A valid URL is required.")
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            raise UnsafeURL("Local hostnames are not allowed.")
        return url.copy_with(host=host, fragment=None)
    except UnsafeURL:
        raise
    except ValueError, httpx.InvalidURL:
        raise UnsafeURL("A valid URL is required.") from None


def _public_ipv4(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise UnsafeURL("The destination has an invalid network address.") from None
    if (
        not isinstance(address, ipaddress.IPv4Address)
        or not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        # Azure's platform virtual IP is globally classified but is not a website.
        or address == ipaddress.IPv4Address("168.63.129.16")
        or address in ipaddress.IPv4Network("192.0.0.0/24")
    ):
        raise UnsafeURL("The destination is not an allowed public IPv4 address.")
    return str(address)


async def _resolve_destination(url: httpx.URL) -> str:
    try:
        ipaddress.ip_address(url.host)
    except ValueError:
        try:
            async with asyncio.timeout(DNS_TIMEOUT):
                records = await asyncio.get_running_loop().getaddrinfo(
                    url.host,
                    url.port or (443 if url.scheme == "https" else 80),
                    family=socket.AF_INET,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                )
        except TimeoutError:
            raise
        except OSError:
            raise UnsafeURL("The hostname could not be resolved.") from None
        if not records:
            raise UnsafeURL("The hostname has no supported IPv4 destination.")
        # Reject mixed public/private answers rather than picking the public one.
        addresses = [_public_ipv4(record[4][0]) for record in records]
        return addresses[0]
    return _public_ipv4(url.host)


class OpenURLTool(Tool):
    name = "open_url"
    description = (
        "Open a public HTTP or HTTPS URL on a standard port and return text "
        "content (HTML remains markup). Supports public IPv4 destinations only. "
        "Use this when the user asks to open or inspect a specific web page."
    )
    permission = PermissionLevel.SAFE

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The HTTP or HTTPS URL to open.",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        value = arguments.get("url", "")
        if value == "":
            return ToolResult(False, "", "URL is required.")
        if not isinstance(value, str):
            return ToolResult(False, "", "A valid URL is required.")
        try:
            async with asyncio.timeout(TOTAL_TIMEOUT):
                return await self._fetch(value)
        except UnsafeURL as exc:
            return ToolResult(False, "", str(exc))
        except TimeoutError, httpx.TimeoutException:
            return ToolResult(False, "", "The URL request timed out.")
        except httpx.HTTPError:
            return ToolResult(False, "", "The HTTP connection or response failed.")
        except Exception:  # noqa: BLE001 - never echo URLs, credentials or response bodies
            return ToolResult(False, "", "The URL could not be retrieved safely.")

    async def _fetch(self, value: str) -> ToolResult:
        for hop in range(MAX_REDIRECTS + 1):
            url = _parse_url(value)
            address = await _resolve_destination(url)
            # Numeric URL pins the actual TCP destination. The original hostname
            # is used ONLY for HTTP routing and TLS SNI/certificate verification.
            destination = url.copy_with(host=address)
            # A fresh client avoids cross-origin cookie and pooled TLS reuse.
            async with (
                httpx.AsyncClient(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=HTTP_TIMEOUT,
                    verify=True,
                    http2=False,
                ) as client,
                client.stream(
                    "GET",
                    destination,
                    headers={
                        "Host": url.host,
                        "User-Agent": "JARVIS/1.0",
                        "Accept-Encoding": "identity",
                    },
                    extensions={"sni_hostname": url.host},
                ) as response,
            ):
                if response.status_code in REDIRECT_CODES:
                    if hop == MAX_REDIRECTS:
                        raise UnsafeURL("The URL exceeded the redirect limit.")
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeURL("The redirect has no destination.")
                    if any(
                        c.isspace() or ord(c) < 32 or ord(c) == 127 for c in location
                    ):
                        raise UnsafeURL("The redirect destination is invalid.")
                    value = urljoin(str(url), location)
                    next_url = _parse_url(value)
                    if url.scheme == "https" and next_url.scheme != "https":
                        raise UnsafeURL("HTTPS to HTTP redirects are not allowed.")
                    continue
                if not 200 <= response.status_code < 300:
                    raise UnsafeURL(
                        f"HTTP request failed with status {response.status_code}."
                    )
                media_type = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if media_type not in TEXT_TYPES:
                    raise UnsafeURL(
                        "The URL does not return a supported text or JSON response."
                    )
                encoding = (
                    response.headers.get("content-encoding", "identity").strip().lower()
                )
                if encoding != "identity":
                    raise UnsafeURL("Compressed responses are not supported.")
                length = response.headers.get("content-length")
                if length is not None:
                    if not re.fullmatch(r"[0-9]+", length):
                        raise UnsafeURL("The response has an invalid content length.")
                    if int(length) > MAX_RESPONSE_BYTES:
                        raise UnsafeURL("The response exceeds the byte limit.")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise UnsafeURL("The response exceeds the byte limit.")
                    body.extend(chunk)
                try:
                    content = body.decode(
                        response.encoding or "utf-8", errors="replace"
                    ).strip()
                except LookupError:
                    content = body.decode("utf-8", errors="replace").strip()
                if not content:
                    return ToolResult(True, "The page returned no text content.")
                if len(content) > 20_000:
                    content = content[:20_000] + "\n\n[Content truncated by JARVIS.]"
                return ToolResult(True, content)
        raise UnsafeURL("The URL exceeded the redirect limit.")
