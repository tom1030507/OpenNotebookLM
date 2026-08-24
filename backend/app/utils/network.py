"""Network-boundary validation for user-supplied destinations."""
import ipaddress
import socket
from typing import Callable, List, Tuple
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UnsafeURLError(ValueError):
    """Raised when a URL is not safe for a server-side fetch."""


def _is_public_address(address) -> bool:
    """Return whether an IP and any embedded transition address are public."""
    explicitly_denied = (
        address.is_multicast,
        address.is_reserved,
        address.is_unspecified,
        address.is_loopback,
        address.is_link_local,
        address.is_private,
    )
    if not address.is_global or any(explicitly_denied):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.is_site_local:
            return False
        embedded = []
        if address.ipv4_mapped is not None:
            embedded.append(address.ipv4_mapped)
        if address.sixtofour is not None:
            embedded.append(address.sixtofour)
        if address.teredo is not None:
            embedded.extend(address.teredo)
        if any(not _is_public_address(item) for item in embedded):
            return False
    return True


def validate_public_http_url(
    url: str,
    resolver: Callable = socket.getaddrinfo,
) -> str:
    """Validate and normalize a URL before an outbound request.

    Args:
        url: User-supplied URL.
        resolver: DNS resolver compatible with ``socket.getaddrinfo``.

    Returns:
        The normalized URL.
    """
    normalized, _ = resolve_public_http_url(url, resolver=resolver)
    return normalized


def resolve_public_http_url(
    url: str,
    resolver: Callable = socket.getaddrinfo,
) -> Tuple[str, List[str]]:
    """Validate a URL and return the public addresses resolved for this fetch.

    The caller must connect to one of the returned addresses rather than resolve
    the hostname a second time. Otherwise a rebinding DNS server can answer with
    a public address for validation and a private address for the actual socket.

    Args:
        url: User-supplied URL.
        resolver: DNS resolver compatible with ``socket.getaddrinfo``.

    Returns:
        A pair containing the normalized URL and its unique public IP strings.

    Raises:
        UnsafeURLError: If URL syntax, scheme, credentials, DNS, or any resolved
            address violates the public-network policy.
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise UnsafeURLError("URL is malformed") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError("Only HTTP(S) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URL credentials are not allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL must include a hostname")

    try:
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UnsafeURLError("URL hostname is invalid") from exc
    if not hostname or any(character.isspace() for character in hostname):
        raise UnsafeURLError("URL hostname is invalid")

    lookup_port = port if port is not None else (443 if scheme == "https" else 80)
    try:
        answers = resolver(hostname, lookup_port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise UnsafeURLError("URL hostname could not be resolved") from exc
    if not answers:
        raise UnsafeURLError("URL hostname could not be resolved")

    addresses: List[str] = []
    for answer in answers:
        try:
            parsed_address = ipaddress.ip_address(answer[4][0])
            address = str(parsed_address)
        except (IndexError, TypeError, ValueError) as exc:
            raise UnsafeURLError("URL hostname returned an invalid address") from exc
        if not _is_public_address(parsed_address):
            raise UnsafeURLError("URL destination must be globally routable")
        if address not in addresses:
            addresses.append(address)

    normalized_host = "[%s]" % hostname if ":" in hostname else hostname
    normalized_netloc = normalized_host
    if port is not None:
        normalized_netloc += ":%s" % port
    normalized = SplitResult(
        scheme=scheme,
        netloc=normalized_netloc,
        path=parsed.path,
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized), addresses
