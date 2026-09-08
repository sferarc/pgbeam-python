"""Client construction, and the surface the generator produced.

The surface tests read the generated files rather than a list written here, so
adding an operation to the OpenAPI contract cannot leave one flavour of the
client behind without this going red.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
import respx

import pgbeam
from pgbeam import (
    OPERATIONS_BY_PATH,
    OPERATIONS_BY_TAG,
    AsyncPgBeamClient,
    PgBeamClient,
    RetryConfig,
)
from pgbeam._client import DEFAULT_BASE_URL, TOKEN_ENV_VARS

BASE = "https://api.test.pgbeam.com"


class TestConstruction:
    def test_defaults_to_the_hosted_api(self) -> None:
        with PgBeamClient(token="t") as client:
            assert client._transport._base_url == DEFAULT_BASE_URL

    def test_reads_the_token_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in TOKEN_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("PGBEAM_API_KEY", "from_env")
        with PgBeamClient() as client:
            assert client._transport._token == "from_env"

    def test_canonical_env_var_wins_over_the_aliases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PGBEAM_API_KEY", "canonical")
        monkeypatch.setenv("PGBEAM_TOKEN", "alias")
        with PgBeamClient() as client:
            assert client._transport._token == "canonical"

    def test_reads_the_base_url_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PGBEAM_API_URL", BASE)
        with PgBeamClient(token="t") as client:
            assert client._transport._base_url == BASE

    def test_an_explicit_base_url_wins_over_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PGBEAM_API_URL", "https://wrong.example")
        with PgBeamClient(token="t", base_url=BASE) as client:
            assert client._transport._base_url == BASE

    def test_a_supplied_http_client_is_not_closed(self) -> None:
        http_client = httpx.Client(base_url=BASE)
        client = PgBeamClient(token="t", base_url=BASE, http_client=http_client)
        client.close()
        assert http_client.is_closed is False
        http_client.close()

    def test_retry_config_reaches_the_transport(self) -> None:
        retry = RetryConfig(max_retries=0)
        with PgBeamClient(token="t", retry=retry) as client:
            assert client._transport._retry is retry


class TestCalls:
    @respx.mock
    def test_a_list_call_sends_the_query_and_returns_the_body(self) -> None:
        route = respx.get(f"{BASE}/v1/projects").mock(
            return_value=httpx.Response(200, json={"projects": [], "total": 0})
        )
        with PgBeamClient(token="t", base_url=BASE) as client:
            result = client.projects.list_projects(org_id="org_1", page_size=5)
        assert result == {"projects": [], "total": 0}
        assert dict(route.calls[0].request.url.params) == {"org_id": "org_1", "page_size": "5"}

    @respx.mock
    def test_a_path_param_lands_in_the_url(self) -> None:
        route = respx.get(f"{BASE}/v1/projects/prj_1").mock(
            return_value=httpx.Response(200, json={"id": "prj_1"})
        )
        with PgBeamClient(token="t", base_url=BASE) as client:
            client.projects.get_project(project_id="prj_1")
        assert route.calls[0].request.url.path == "/v1/projects/prj_1"

    @respx.mock
    def test_a_204_delete_returns_nothing(self) -> None:
        # Typed as `-> None`, so there is no value to assert on: what is being
        # checked is that a 204 does not raise on an empty body.
        route = respx.delete(f"{BASE}/v1/projects/prj_1").mock(return_value=httpx.Response(204))
        with PgBeamClient(token="t", base_url=BASE) as client:
            client.projects.delete_project(project_id="prj_1")
        assert route.call_count == 1

    @respx.mock
    async def test_the_async_client_makes_the_same_call(self) -> None:
        route = respx.get(f"{BASE}/v1/projects").mock(
            return_value=httpx.Response(200, json={"projects": [], "total": 0})
        )
        async with AsyncPgBeamClient(token="t", base_url=BASE) as client:
            result = await client.projects.list_projects(org_id="org_1")
        assert result == {"projects": [], "total": 0}
        assert route.call_count == 1


def service_attributes(client_class: type) -> dict[str, str]:
    """Tag attribute to service class name, from the generated annotations."""
    return {
        name: annotation
        for name, annotation in client_class.__annotations__.items()
        if not name.startswith("_")
    }


class TestGeneratedSurface:
    def test_the_two_clients_carry_the_same_tags(self) -> None:
        sync = set(service_attributes(PgBeamClient))
        async_ = set(service_attributes(AsyncPgBeamClient))
        assert sync == async_
        assert sync == set(OPERATIONS_BY_TAG)

    def test_every_operation_is_a_method_on_both_clients(self) -> None:
        with PgBeamClient(token="t") as sync_client:
            async_client = AsyncPgBeamClient(token="t")
            for tag, operations in OPERATIONS_BY_TAG.items():
                sync_service = getattr(sync_client, tag)
                async_service = getattr(async_client, tag)
                for name in operations:
                    assert callable(getattr(sync_service, name)), f"{tag}.{name} missing (sync)"
                    method = getattr(async_service, name)
                    assert inspect.iscoroutinefunction(method), f"{tag}.{name} is not awaitable"

    def test_the_two_flavours_agree_on_every_signature(self) -> None:
        # A parameter added to one and not the other is a difference a caller
        # discovers at runtime, in whichever flavour they happen to use second.
        with PgBeamClient(token="t") as sync_client:
            async_client = AsyncPgBeamClient(token="t")
            for tag, operations in OPERATIONS_BY_TAG.items():
                for name in operations:
                    sync_signature = inspect.signature(getattr(getattr(sync_client, tag), name))
                    async_signature = inspect.signature(getattr(getattr(async_client, tag), name))
                    assert sync_signature == async_signature, f"{tag}.{name}"

    def test_operations_are_registered_by_route_too(self) -> None:
        total = sum(len(operations) for operations in OPERATIONS_BY_TAG.values())
        assert len(OPERATIONS_BY_PATH) == total
        for route, meta in OPERATIONS_BY_PATH.items():
            assert route == f"{meta.method} {meta.path}"

    def test_there_is_a_real_surface_to_check(self) -> None:
        # Guards against the assertions above passing over an empty registry.
        assert len(OPERATIONS_BY_PATH) > 50

    def test_the_package_ships_a_typing_marker(self) -> None:
        # Without py.typed in the wheel, a type checker ignores every annotation
        # in this package and the whole point of the generated types is lost.
        package_dir = __import__("pathlib").Path(pgbeam.__file__).parent
        assert (package_dir / "py.typed").is_file()
