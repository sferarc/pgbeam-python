"""HTTP transport: one request, retried and bounded.

This is the half of the SDK that is not generated, and it is a deliberate port
of the TypeScript SDK's ``utils/fetcher.ts`` rather than an independent design.
The two clients agree on which statuses are worth retrying, how long to wait
between attempts, when to stop waiting, when an idempotency key is attached, and
what a failure is called. A team running both should not have to learn the
difference twice.

The bounds, in the order they bite:

* ``timeout_ms`` caps one attempt. It defaults to 30 seconds, which is long
  enough for the slowest legitimate call (an audit-log CSV export) and short
  enough that a black-holed connection fails in a sane time.
* ``RetryConfig.max_retries`` caps how many attempts there are.
* ``RetryConfig.total_budget_ms`` caps the whole call, measured from the first
  attempt and including time spent in requests. A retry that would land past the
  budget is not made, so a long backoff ladder against a service that is down
  cannot outlive it.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import random
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from .errors import ApiError, NetworkError

__all__ = ["AsyncTransport", "RetryConfig", "Transport"]

#: Statuses worth trying again. Everything else is the server's considered
#: answer, and repeating the request will get the same one.
RETRYABLE_STATUS = frozenset({408, 429, 502, 503, 504})

DEFAULT_TIMEOUT_MS = 30_000

#: Methods where a retry could otherwise duplicate work. PUT and DELETE are
#: idempotent by definition and need no key; GET changes nothing.
MUTATING_METHODS = frozenset({"POST", "PATCH"})


@dataclass(frozen=True)
class RetryConfig:
    """How hard to try again, and when to stop.

    The defaults are the TypeScript SDK's. ``max_retries=0`` disables retrying
    without disabling anything else.
    """

    max_retries: int = 5
    initial_delay_ms: int = 500
    max_delay_ms: int = 30_000
    #: Attach an ``Idempotency-Key`` to retried POST and PATCH requests, so a
    #: retry of a request the server already accepted is not a second write.
    idempotency_keys: bool = True
    #: Ceiling for the whole call, measured from the first attempt.
    total_budget_ms: int = 120_000


NO_RETRY = RetryConfig(max_retries=0)


def _backoff_ms(attempt: int, config: RetryConfig) -> float:
    """Exponential backoff with jitter, capped at ``max_delay_ms``."""
    delay: float = min(config.initial_delay_ms * (2**attempt), config.max_delay_ms)
    return delay * (0.5 + random.random())


def _out_of_budget(started_at: float, delay_ms: float, config: RetryConfig) -> bool:
    """Whether waiting ``delay_ms`` and trying again would land past the budget."""
    if config.total_budget_ms <= 0:
        return False
    elapsed_ms = (time.monotonic() - started_at) * 1000
    return elapsed_ms + delay_ms >= config.total_budget_ms


def _retry_after_ms(response: httpx.Response) -> float | None:
    """``Retry-After`` in milliseconds, honouring both forms the RFC allows."""
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        seconds = float(header)
    except ValueError:
        pass
    else:
        return seconds * 1000 if seconds >= 0 else None
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    now = dt.datetime.now(tz=when.tzinfo or dt.timezone.utc)
    delta_ms = (when - now).total_seconds() * 1000
    return max(delta_ms, 0.0)


def _query_value(value: object) -> str:
    """Render a query parameter the way the API reads it.

    Booleans go over the wire as ``true``/``false``, not Python's ``True``.
    Getting this wrong is the kind of bug that only shows up as a filter that
    quietly matches nothing.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_url(path: str, path_params: Mapping[str, str] | None) -> str:
    if not path_params:
        return path
    url = path
    for key, value in path_params.items():
        url = url.replace("{" + key + "}", quote(str(value), safe=""))
    return url


def _build_query(query: Mapping[str, object] | None) -> dict[str, str]:
    if not query:
        return {}
    return {key: _query_value(value) for key, value in query.items() if value is not None}


def _parse_body(response: httpx.Response) -> Any:
    """Decode a successful response.

    A 204 is ``None``. JSON is decoded. Anything else comes back as text, after
    one opportunistic JSON attempt in case the server mislabelled it, because
    the audit-log export is genuinely ``text/csv`` and a caller wants the bytes
    rather than ``None``.
    """
    if response.status_code == 204:
        return None
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    text = response.text
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _error_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text or None


def _headers(
    token: str | None,
    has_body: bool,
    extra: Mapping[str, str] | None,
    user_agent: str,
) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": user_agent}
    if extra:
        headers.update(extra)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if has_body:
        headers["Content-Type"] = "application/json"
    return headers


class _Attempt:
    """Bookkeeping shared by the sync and async loops."""

    def __init__(self, method: str, url: str, timeout_ms: int) -> None:
        self.method = method
        self.url = url
        self.timeout_ms = timeout_ms
        self.started_at = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)

    def network_error(
        self, attempts: int, timed_out: bool, cause: BaseException | None
    ) -> NetworkError:
        return NetworkError(
            method=self.method,
            url=self.url,
            attempts=attempts,
            elapsed_ms=self.elapsed_ms(),
            timed_out=timed_out,
            timeout_ms=self.timeout_ms,
            cause=cause,
        )


def _timed_out(err: BaseException) -> bool:
    return isinstance(err, httpx.TimeoutException)


class Transport:
    """Blocking transport over ``httpx.Client``."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | Callable[[], str | None] | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry: RetryConfig | None = None,
        headers: Mapping[str, str] | None = None,
        user_agent: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._token = token
        self._timeout_ms = timeout_ms
        self._retry = retry if retry is not None else RetryConfig()
        self._headers = dict(headers) if headers else {}
        self._user_agent = user_agent
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(base_url=base_url, follow_redirects=False)
        self._base_url = base_url
        self._token_pool: ThreadPoolExecutor | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
        if self._token_pool is not None:
            self._token_pool.shutdown(wait=False)
            self._token_pool = None

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _resolve_token(self, attempt: _Attempt) -> str | None:
        """Resolve a lazy token, or give up once ``timeout_ms`` has passed.

        A token callable is usually a network call in disguise, so it gets the
        same per-attempt ceiling as the request it authenticates. Without one it
        would sit outside every bound this module applies, which is the case the
        TypeScript SDK found the hard way: a request with no ceiling of any kind.
        A ``timeout_ms`` of 0 disables the request timeout by documented
        contract, so it disables this one too rather than inventing a ceiling
        the caller turned off.
        """
        token = self._token
        if not callable(token):
            return token
        if self._timeout_ms <= 0:
            return token()

        if self._token_pool is None:
            self._token_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pgbeam-token")
        future = self._token_pool.submit(token)
        try:
            return future.result(timeout=self._timeout_ms / 1000)
        except FutureTimeoutError as err:
            # The thread is abandoned rather than killed: Python cannot
            # interrupt it, and the caller is owed an answer now. It is reported
            # as a timed-out NetworkError because that is what it is to a
            # caller, and because a second try tests the same thing again.
            raise attempt.network_error(attempts=0, timed_out=True, cause=err) from err

    def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, str] | None = None,
        query: Mapping[str, object] | None = None,
        body: object | None = None,
    ) -> Any:
        url = _build_url(path, path_params)
        params = _build_query(query)
        attempt_ctx = _Attempt(method, f"{self._base_url.rstrip('/')}{url}", self._timeout_ms)
        retry = self._retry

        token = self._resolve_token(attempt_ctx)
        headers = _headers(token, body is not None, self._headers, self._user_agent)

        # Generated once and reused, so every attempt at the same call carries
        # the same key and the server can collapse the duplicates.
        if retry.max_retries > 0 and retry.idempotency_keys and method.upper() in MUTATING_METHODS:
            headers.setdefault("Idempotency-Key", str(uuid.uuid4()))

        timeout = self._timeout_ms / 1000 if self._timeout_ms > 0 else None
        content = json.dumps(body).encode() if body is not None else None

        for attempt in range(retry.max_retries + 1):
            answered = False
            try:
                response = self._client.request(
                    method,
                    url,
                    params=params or None,
                    headers=headers,
                    content=content,
                    timeout=timeout,
                )
                answered = True

                if response.is_success:
                    return _parse_body(response)

                retryable = response.status_code in RETRYABLE_STATUS and attempt < retry.max_retries
                delay = (
                    (_retry_after_ms(response) or _backoff_ms(attempt, retry)) if retryable else 0.0
                )
                if not retryable or _out_of_budget(attempt_ctx.started_at, delay, retry):
                    raise ApiError(
                        response.status_code,
                        response.reason_phrase,
                        _error_body(response),
                    )
                time.sleep(delay / 1000)
            except ApiError:
                raise
            except httpx.HTTPError as err:
                delay = _backoff_ms(attempt, retry)
                if attempt == retry.max_retries or _out_of_budget(
                    attempt_ctx.started_at, delay, retry
                ):
                    if answered:
                        raise
                    raise attempt_ctx.network_error(
                        attempts=attempt + 1, timed_out=_timed_out(err), cause=err
                    ) from err
                time.sleep(delay / 1000)

        raise RuntimeError("pgbeam transport: exhausted all retry attempts")  # pragma: no cover


class AsyncTransport:
    """Awaitable transport over ``httpx.AsyncClient``.

    Same policy as :class:`Transport`, same defaults, same errors.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | Callable[[], str | Awaitable[str | None] | None] | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry: RetryConfig | None = None,
        headers: Mapping[str, str] | None = None,
        user_agent: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._timeout_ms = timeout_ms
        self._retry = retry if retry is not None else RetryConfig()
        self._headers = dict(headers) if headers else {}
        self._user_agent = user_agent
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(base_url=base_url, follow_redirects=False)
        self._base_url = base_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _resolve_token(self, attempt: _Attempt) -> str | None:
        token = self._token
        if not callable(token):
            return token
        result = token()
        if not isinstance(result, str) and result is not None:
            if self._timeout_ms <= 0:
                return await result
            try:
                return await asyncio.wait_for(result, timeout=self._timeout_ms / 1000)
            except asyncio.TimeoutError as err:
                raise attempt.network_error(attempts=0, timed_out=True, cause=err) from err
        return result

    async def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, str] | None = None,
        query: Mapping[str, object] | None = None,
        body: object | None = None,
    ) -> Any:
        url = _build_url(path, path_params)
        params = _build_query(query)
        attempt_ctx = _Attempt(method, f"{self._base_url.rstrip('/')}{url}", self._timeout_ms)
        retry = self._retry

        token = await self._resolve_token(attempt_ctx)
        headers = _headers(token, body is not None, self._headers, self._user_agent)

        if retry.max_retries > 0 and retry.idempotency_keys and method.upper() in MUTATING_METHODS:
            headers.setdefault("Idempotency-Key", str(uuid.uuid4()))

        timeout = self._timeout_ms / 1000 if self._timeout_ms > 0 else None
        content = json.dumps(body).encode() if body is not None else None

        for attempt in range(retry.max_retries + 1):
            answered = False
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params or None,
                    headers=headers,
                    content=content,
                    timeout=timeout,
                )
                answered = True

                if response.is_success:
                    return _parse_body(response)

                retryable = response.status_code in RETRYABLE_STATUS and attempt < retry.max_retries
                delay = (
                    (_retry_after_ms(response) or _backoff_ms(attempt, retry)) if retryable else 0.0
                )
                if not retryable or _out_of_budget(attempt_ctx.started_at, delay, retry):
                    raise ApiError(
                        response.status_code,
                        response.reason_phrase,
                        _error_body(response),
                    )
                await asyncio.sleep(delay / 1000)
            except ApiError:
                raise
            except httpx.HTTPError as err:
                delay = _backoff_ms(attempt, retry)
                if attempt == retry.max_retries or _out_of_budget(
                    attempt_ctx.started_at, delay, retry
                ):
                    if answered:
                        raise
                    raise attempt_ctx.network_error(
                        attempts=attempt + 1, timed_out=_timed_out(err), cause=err
                    ) from err
                await asyncio.sleep(delay / 1000)

        raise RuntimeError("pgbeam transport: exhausted all retry attempts")  # pragma: no cover
