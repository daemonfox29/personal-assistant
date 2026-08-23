"""HTTP utilities that can connect only to an explicit loopback address."""

from ipaddress import ip_address
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)
from urllib.parse import urlsplit
from typing import BinaryIO


class LocalConnectionError(ValueError):
    """Raised when a URL is not an explicit local-only HTTP address."""


class NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects instead of following them to another destination."""

    def redirect_request(self, request, file_pointer, code, message, headers, url):
        return None


def validate_loopback_http_url(url: str, *, base_url: bool = False) -> str:
    """Return an approved URL or reject anything outside numeric loopback HTTP."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise LocalConnectionError(
            "The Ollama URL must be a valid loopback HTTP address."
        ) from error

    if parsed.scheme != "http":
        raise LocalConnectionError("The Ollama URL must use plain HTTP.")
    if parsed.username is not None or parsed.password is not None:
        raise LocalConnectionError("The Ollama URL must not contain credentials.")
    if parsed.hostname is None or port is None:
        raise LocalConnectionError(
            "The Ollama URL must contain an explicit IP address and port."
        )
    if port == 0:
        raise LocalConnectionError("The Ollama URL port must be between 1 and 65535.")

    try:
        address = ip_address(parsed.hostname)
    except ValueError as error:
        raise LocalConnectionError(
            "The Ollama URL must use a numeric loopback IP address."
        ) from error

    if not address.is_loopback:
        raise LocalConnectionError(
            "The Ollama URL must use a loopback IP address."
        )
    if parsed.query or parsed.fragment:
        raise LocalConnectionError(
            "The Ollama URL must not contain a query string or fragment."
        )
    if base_url and parsed.path not in {"", "/"}:
        raise LocalConnectionError("The Ollama base URL must not contain a path.")

    return url.rstrip("/") if base_url else url


def build_local_only_opener() -> OpenerDirector:
    """Build an opener that ignores proxies and refuses HTTP redirects."""

    return build_opener(ProxyHandler({}), NoRedirectHandler())


_LOCAL_ONLY_OPENER = build_local_only_opener()


def open_local(request: Request, timeout_seconds: float) -> BinaryIO:
    """Open one validated local request through the restricted HTTP client."""

    validate_loopback_http_url(request.full_url)
    return _LOCAL_ONLY_OPENER.open(request, timeout=timeout_seconds)
