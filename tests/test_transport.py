"""The transport's policy, asserted rather than described.

Every case here is one the TypeScript SDK also has a test for, because the two
agreeing is the whole point of porting the transport rather than writing a new
one.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from pgbeam._transport import (
    MUTATING_METHODS,
    RETRYABLE_STATUS,
    AsyncTransport,
    RetryConfig,
    Transport,
    _build_query,
    _build_url,
    _retry_after_ms,
)
from pgbeam.errors import ApiError, NetworkError

BASE = "https://api.test.pgbeam.com"

FAST = RetryConfig(max_retries=3, initial_delay_ms=1, max_delay_ms=2, total_budget_ms=60_000)


def make_transport(**kwargs: object) -> Transport:
    defaults: dict[str, object] = {
        "base_url": BASE,
        "token": "tok_123",
        "user_agent": "pgbeam-python/test",
        "retry": FAST,
    }
    defaults.update(kwargs)
    return Transport(**defaults)  # type: ignore[arg-type]


def make_async_transport(**kwargs: object) -> AsyncTransport:
    defaults: dict[str, object] = {
        "base_url": BASE,
        "token": "tok_123",
        "user_agent": "pgbeam-python/test",
        "retry": FAST,
    }
    defaults.update(kwargs)
    return AsyncTransport(**defaults)  # type: ignore[arg-type]


class TestUrlBuilding:
    def test_substitutes_and_escapes_path_params(self) -> None:
        url = _build_url("/v1/projects/{project_id}/x", {"project_id": "a/b c"})
        assert url == "/v1/projects/a%2Fb%20c/x"

    def test_drops_none_query_params(self) -> None:
        assert _build_query({"a": None, "b": 2}) == {"b": "2"}

    def test_renders_booleans_the_way_the_api_reads_them(self) -> None:
        # `str(True)` is "True", which the API does not accept as a boolean.
        assert _build_query({"active": True, "archived": False}) == {
            "active": "true",
            "archived": "false",
        }


class TestSuccessDecoding:
    @respx.mock
    def test_json_body(self) -> None:
        respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(200, json={"ok": True}))
        with make_transport() as transport:
            assert transport.request("GET", "/v1/x") == {"ok": True}

    @respx.mock
    def test_204_is_none(self) -> None:
        respx.delete(f"{BASE}/v1/x").mock(return_value=httpx.Response(204))
        with make_transport() as transport:
            assert transport.request("DELETE", "/v1/x") is None

    @respx.mock
    def test_non_json_body_comes_back_as_text(self) -> None:
        # The audit-log export is text/csv. Returning None here would lose the
        # payload the caller asked for.
        respx.get(f"{BASE}/v1/export").mock(
            return_value=httpx.Response(
                200, text="a,b\n1,2\n", headers={"content-type": "text/csv"}
            )
        )
        with make_transport() as transport:
            assert transport.request("GET", "/v1/export") == "a,b\n1,2\n"

    @respx.mock
    def test_sends_bearer_token_and_user_agent(self) -> None:
        route = respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(200, json={}))
        with make_transport() as transport:
            transport.request("GET", "/v1/x")
        request = route.calls[0].request
        assert request.headers["authorization"] == "Bearer tok_123"
        assert request.headers["user-agent"] == "pgbeam-python/test"


class TestErrors:
    @respx.mock
    def test_api_error_carries_the_servers_message(self) -> None:
        respx.get(f"{BASE}/v1/x").mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "conflict", "message": "already exists"}}
            )
        )
        with make_transport() as transport, pytest.raises(ApiError) as caught:
            transport.request("GET", "/v1/x")
        assert caught.value.status == 409
        assert str(caught.value) == "already exists"

    @respx.mock
    def test_a_409_is_not_retried(self) -> None:
        route = respx.post(f"{BASE}/v1/x").mock(return_value=httpx.Response(409, json={}))
        with make_transport() as transport, pytest.raises(ApiError):
            transport.request("POST", "/v1/x", body={})
        assert route.call_count == 1

    @respx.mock
    def test_connection_failure_becomes_a_network_error(self) -> None:
        respx.get(f"{BASE}/v1/x").mock(side_effect=httpx.ConnectError("refused"))
        with make_transport() as transport, pytest.raises(NetworkError) as caught:
            transport.request("GET", "/v1/x")
        error = caught.value
        assert error.attempts == FAST.max_retries + 1
        assert error.timed_out is False
        assert "/v1/x" in error.url

    @respx.mock
    def test_a_timeout_is_flagged_as_one(self) -> None:
        respx.get(f"{BASE}/v1/x").mock(side_effect=httpx.ReadTimeout("slow"))
        with make_transport() as transport, pytest.raises(NetworkError) as caught:
            transport.request("GET", "/v1/x")
        assert caught.value.timed_out is True


class TestRetries:
    @respx.mock
    def test_retries_every_retryable_status_then_succeeds(self) -> None:
        for status in sorted(RETRYABLE_STATUS):
            respx.reset()
            route = respx.get(f"{BASE}/v1/x").mock(
                side_effect=[
                    httpx.Response(status),
                    httpx.Response(200, json={"status": status}),
                ]
            )
            with make_transport() as transport:
                assert transport.request("GET", "/v1/x") == {"status": status}
            assert route.call_count == 2

    @respx.mock
    def test_gives_up_after_max_retries(self) -> None:
        route = respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(503, json={}))
        with make_transport() as transport, pytest.raises(ApiError) as caught:
            transport.request("GET", "/v1/x")
        assert caught.value.status == 503
        assert route.call_count == FAST.max_retries + 1

    @respx.mock
    def test_max_retries_zero_disables_retrying(self) -> None:
        route = respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(503, json={}))
        with make_transport(retry=RetryConfig(max_retries=0)) as transport, pytest.raises(ApiError):
            transport.request("GET", "/v1/x")
        assert route.call_count == 1

    @respx.mock
    def test_a_retry_that_would_outlive_the_budget_is_not_made(self) -> None:
        route = respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(503, json={}))
        budget_spent = RetryConfig(max_retries=5, initial_delay_ms=1000, total_budget_ms=1)
        with make_transport(retry=budget_spent) as transport, pytest.raises(ApiError):
            transport.request("GET", "/v1/x")
        assert route.call_count == 1

    def test_retry_after_seconds(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "2"})
        assert _retry_after_ms(response) == 2000

    def test_retry_after_http_date_in_the_past_is_zero(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        assert _retry_after_ms(response) == 0

    def test_retry_after_absent(self) -> None:
        assert _retry_after_ms(httpx.Response(429)) is None


class TestIdempotencyKeys:
    @respx.mock
    def test_one_key_is_reused_across_attempts(self) -> None:
        route = respx.post(f"{BASE}/v1/x").mock(
            side_effect=[httpx.Response(503), httpx.Response(201, json={"id": "a"})]
        )
        with make_transport() as transport:
            transport.request("POST", "/v1/x", body={"name": "a"})
        keys = {call.request.headers.get("idempotency-key") for call in route.calls}
        assert len(keys) == 1
        assert next(iter(keys)) is not None

    @respx.mock
    def test_no_key_when_retrying_is_off(self) -> None:
        route = respx.post(f"{BASE}/v1/x").mock(return_value=httpx.Response(201, json={}))
        with make_transport(retry=RetryConfig(max_retries=0)) as transport:
            transport.request("POST", "/v1/x", body={})
        assert route.calls[0].request.headers.get("idempotency-key") is None

    @respx.mock
    def test_no_key_on_a_read(self) -> None:
        route = respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(200, json={}))
        with make_transport() as transport:
            transport.request("GET", "/v1/x")
        assert route.calls[0].request.headers.get("idempotency-key") is None

    def test_only_post_and_patch_need_a_key(self) -> None:
        # PUT and DELETE are idempotent by definition and GET changes nothing.
        assert {"POST", "PATCH"} == MUTATING_METHODS


class TestLazyTokens:
    @respx.mock
    def test_a_callable_token_is_resolved(self) -> None:
        route = respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(200, json={}))
        with make_transport(token=lambda: "lazy_tok") as transport:
            transport.request("GET", "/v1/x")
        assert route.calls[0].request.headers["authorization"] == "Bearer lazy_tok"

    @respx.mock
    def test_a_token_that_never_settles_is_a_timed_out_network_error(self) -> None:
        import threading

        never = threading.Event()

        def stalled_token() -> str | None:
            never.wait(30)
            return "too late"

        respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(200, json={}))
        transport = make_transport(token=stalled_token, timeout_ms=50)
        try:
            with pytest.raises(NetworkError) as caught:
                transport.request("GET", "/v1/x")
        finally:
            never.set()
            transport.close()
        assert caught.value.timed_out is True
        assert caught.value.attempts == 0


class TestAsyncParity:
    @respx.mock
    async def test_decodes_and_retries_like_the_sync_client(self) -> None:
        route = respx.get(f"{BASE}/v1/x").mock(
            side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": True})]
        )
        async with make_async_transport() as transport:
            assert await transport.request("GET", "/v1/x") == {"ok": True}
        assert route.call_count == 2

    @respx.mock
    async def test_raises_the_same_api_error(self) -> None:
        respx.get(f"{BASE}/v1/x").mock(
            return_value=httpx.Response(403, json={"error": {"message": "nope"}})
        )
        async with make_async_transport() as transport:
            with pytest.raises(ApiError) as caught:
                await transport.request("GET", "/v1/x")
        assert caught.value.status == 403
        assert str(caught.value) == "nope"

    @respx.mock
    async def test_awaits_an_awaitable_token(self) -> None:
        async def token() -> str | None:
            return "async_tok"

        route = respx.get(f"{BASE}/v1/x").mock(return_value=httpx.Response(200, json={}))
        async with make_async_transport(token=token) as transport:
            await transport.request("GET", "/v1/x")
        assert route.calls[0].request.headers["authorization"] == "Bearer async_tok"
