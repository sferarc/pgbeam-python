"""Client construction: credentials, base URL, retries, shutdown.

The service attributes and the methods on them are generated from the OpenAPI
contract and live in ``services.py``. What is here is everything that is a
decision rather than a derivation.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from importlib.metadata import PackageNotFoundError, version

import httpx

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: no cover
    from typing_extensions import Self

from ._transport import DEFAULT_TIMEOUT_MS, AsyncTransport, RetryConfig, Transport

__all__ = ["DEFAULT_BASE_URL", "BaseAsyncClient", "BaseClient"]

DEFAULT_BASE_URL = "https://api.pgbeam.com"

#: Read in order, first non-empty wins. ``PGBEAM_API_KEY`` is canonical and is
#: what the CLI and the Terraform, Crossplane and Pulumi providers read; the
#: other two are accepted so one credential in the environment works everywhere.
TOKEN_ENV_VARS = ("PGBEAM_API_KEY", "PGBEAM_TOKEN", "PGBEAM_API_TOKEN")

BASE_URL_ENV_VAR = "PGBEAM_API_URL"


def _package_version() -> str:
    try:
        return version("pgbeam")
    except PackageNotFoundError:  # pragma: no cover - only when run from a source tree
        return "0.0.0+unknown"


def _env_token() -> str | None:
    for name in TOKEN_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _resolve_base_url(base_url: str | None) -> str:
    return base_url or os.environ.get(BASE_URL_ENV_VAR) or DEFAULT_BASE_URL


def _user_agent() -> str:
    return f"pgbeam-python/{_package_version()}"


class BaseClient:
    """Shared construction for the blocking client.

    Args:
        token: An API key, or a callable returning one. A callable is resolved
            once per request, under the same timeout as the request itself, so a
            credential service that stops answering cannot stall a call
            indefinitely. Omit it to read ``PGBEAM_API_KEY``, ``PGBEAM_TOKEN`` or
            ``PGBEAM_API_TOKEN`` from the environment.
        base_url: Where the API lives. Defaults to ``PGBEAM_API_URL`` if set,
            otherwise ``https://api.pgbeam.com``.
        timeout_ms: Per-attempt timeout. 0 disables it, which leaves the request
            at the mercy of the platform's own socket timeouts.
        retry: Retry policy. Defaults to five retries with jittered exponential
            backoff on 408, 429, 502, 503 and 504. Pass
            ``RetryConfig(max_retries=0)`` to disable retrying.
        headers: Extra headers sent on every request.
        http_client: An ``httpx.Client`` to use instead of one of this client's
            own. Supply one to share a connection pool, a proxy or a custom
            transport. A supplied client is not closed by ``close()``.
    """

    def __init__(
        self,
        *,
        token: str | Callable[[], str | None] | None = None,
        base_url: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry: RetryConfig | None = None,
        headers: Mapping[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._transport = Transport(
            base_url=_resolve_base_url(base_url),
            token=token if token is not None else _env_token(),
            timeout_ms=timeout_ms,
            retry=retry,
            headers=headers,
            user_agent=_user_agent(),
            http_client=http_client,
        )
        self._bind_services()

    def _bind_services(self) -> None:
        """Attach the generated service objects. Overridden in ``services.py``."""

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._transport.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class BaseAsyncClient:
    """Shared construction for the asyncio client.

    Takes the same arguments as :class:`BaseClient`, with two differences: the
    token callable may return an awaitable, and the HTTP client is an
    ``httpx.AsyncClient``. Close it with ``await client.aclose()``, or use it as
    an async context manager.
    """

    def __init__(
        self,
        *,
        token: str | Callable[[], str | Awaitable[str | None] | None] | None = None,
        base_url: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry: RetryConfig | None = None,
        headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._transport = AsyncTransport(
            base_url=_resolve_base_url(base_url),
            token=token if token is not None else _env_token(),
            timeout_ms=timeout_ms,
            retry=retry,
            headers=headers,
            user_agent=_user_agent(),
            http_client=http_client,
        )
        self._bind_services()

    def _bind_services(self) -> None:
        """Attach the generated service objects. Overridden in ``services.py``."""

    async def aclose(self) -> None:
        """Release the underlying connection pool."""
        await self._transport.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
