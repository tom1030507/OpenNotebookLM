"""Network-boundary validation for user-supplied destinations."""
import ipaddress
import socket
from typing import Callable, List, Tuple
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UnsafeURLError(ValueError):
    """Raised when a URL is not safe for a server-side fetch."""


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
            address = str(ipaddress.ip_address(answer[4][0]))
        except (IndexError, TypeError, ValueError) as exc:
            raise UnsafeURLError("URL hostname returned an invalid address") from exc
        if not ipaddress.ip_address(address).is_global:
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
