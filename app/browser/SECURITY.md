# open_url network boundary

The tool permits HTTP on port 80 and HTTPS on port 443. Credentials in URLs,
malformed authorities, controls, backslashes, local hostnames and nonpublic
addresses are rejected. IPv4 address classification uses Python's `ipaddress`;
multicast, reserved addresses, the 192.0.0.0/24 special-purpose range and Azure's
168.63.129.16 platform address are explicitly excluded. Common metadata ranges
(including link-local and shared/CGN space) are blocked.

DNS is queried for IPv4 TCP destinations only. Every returned A address must pass
validation. The selected address replaces the hostname in the actual HTTPX request
URL, so the transport connects to a numeric, validated destination; it does not
resolve the untrusted hostname again. Host routing and HTTPS SNI/certificate
verification retain the original hostname via HTTPX's documented `sni_hostname`
extension. TLS verification remains enabled. This is connection pinning, not just
a preflight DNS check. A mocked TCP-boundary regression test exercises the real
HTTPX/HTTPCore transport and verifies both the destination and TLS hostname.

Reference: https://www.python-httpx.org/advanced/extensions/#sni_hostname

Each redirect is parsed, validated and resolved again before connecting; relative
locations resolve against the original URL, not its numeric transport URL.
HTTPS-to-HTTP redirects are blocked. A fresh client on each hop prevents pooled
TLS connections or cookies from crossing origins. Environment proxies and CA
overrides are disabled with `trust_env=False`; no explicit proxy is supported.

Limits:

- Three redirects (at most four HTTP requests).
- Five seconds for DNS and connection establishment; ten seconds per read/write;
  thirty seconds overall including DNS and redirects.
- One MiB response body, checked before buffering each raw chunk. Oversized bodies
  are rejected, not partially returned. The existing 20,000-character output
  truncation is retained for accepted bodies.
- Exact text/HTML/CSS/CSV/Markdown/XML/JSON media-type allowlist. HTML/XML are
  returned as text, never executed or parsed for external entities.
- Identity encoding only; compressed bodies are rejected before reading, avoiding
  decompression bombs. Declared lengths are checked but never trusted as the sole
  size bound. HTTP protocol/header parsing is bounded by the installed HTTPCore
  parser separately; the body cap is not a bound on all wire bytes.

Remaining limitations and safe restrictions:

- IPv6 (including mapped IPv4, NAT64 and transition addresses), IPv6-only sites,
  nonstandard ports and compressed-only servers are deliberately unsupported.
  Do not relax these restrictions without equivalent connection-level tests.
- Public classification is not proof that a service is harmless. Custom routing,
  transparent proxies/NAT or organization-specific services on globally numbered
  addresses cannot be identified reliably by this tool. In such environments,
  disable this tool or use an audited egress firewall with a destination allowlist;
  do not claim universal SSRF isolation from application checks alone.
- The first validated IPv4 address is used, with no fallback on connection failure.
  OS DNS work may finish in its executor after cancellation, but no HTTP request
  follows a timed-out lookup. No JavaScript, HTML subresources or meta-refresh URLs
  are fetched.
- HTTP is unencrypted. Public content remains untrusted and may contain prompt
  injection or sensitive data. This change does not harden unrelated agent logging:
  the existing tool-argument logger may record URL query parameters. Avoid secrets
  in URLs; returned browser errors never echo URLs, credentials or exception text.
- Transport behavior was inspected for installed HTTPX 0.28.1/HTTPCore and tested
  without live requests. Keep the connection-pinning regression test when updating
  these dependencies. No network or certificate handshake was performed in tests.
