"""Security utilities: URL validation to prevent Server-Side Request Forgery (SSRF)."""

import ipaddress
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Only HTTPS is accepted for outbound webhook calls
_ALLOWED_SCHEMES = {"https"}

# Private/reserved IPv4 networks that must never be targeted
_PRIVATE_IPV4 = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),   # shared address space (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),     # loopback
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS IMDS
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),    # IETF protocol assignments
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),   # benchmark
    ipaddress.ip_network("198.51.100.0/24"), # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("240.0.0.0/4"),     # reserved
    ipaddress.ip_network("255.255.255.255/32"),
]

# Private/reserved IPv6 networks
_PRIVATE_IPV6 = [
    ipaddress.ip_network("::1/128"),     # loopback
    ipaddress.ip_network("::/128"),      # unspecified
    ipaddress.ip_network("fc00::/7"),    # unique-local (covers fd00::/8)
    ipaddress.ip_network("fe80::/10"),   # link-local
]

# Well-known localhost aliases that should be blocked even as hostnames
_LOCALHOST_NAMES = frozenset({
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
})


def _is_private_ip(host: str) -> bool:
    """Return True if *host* (IP literal or hostname) is a private/reserved address."""
    try:
        addr = ipaddress.ip_address(host)
        networks = _PRIVATE_IPV4 if addr.version == 4 else _PRIVATE_IPV6
        return any(addr in net for net in networks)
    except ValueError:
        # Not an IP literal — treat as a hostname
        return host.lower() in _LOCALHOST_NAMES


def validate_webhook_url(url: str, *, label: str = "URL") -> str:
    """Validate that *url* is safe to use as an outbound webhook target.

    Checks performed:
    - Must use the ``https`` scheme.
    - Host must be present.
    - Host must not be a private/loopback IP address or a localhost hostname.

    Returns the stripped URL if valid, or raises ``ValueError`` with a
    human-readable message describing the problem.
    """
    if not url or not url.strip():
        raise ValueError(f"{label} must not be empty.")

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError(f"{label} is not a valid URL.")

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"{label} must use HTTPS (got '{parsed.scheme}').")

    host = parsed.hostname
    if not host:
        raise ValueError(f"{label} is missing a hostname.")

    if _is_private_ip(host):
        raise ValueError(f"{label} must not target a private or loopback address.")

    return url
