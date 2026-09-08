# pgbeam

Python SDK for the [PgBeam](https://pgbeam.com) API: a globally distributed PostgreSQL proxy that enforces agent access policy in the wire protocol, with connection pooling and query caching.

Manage projects, databases, agent credentials, and policy profiles from Python, with a blocking client and an asyncio client that expose exactly the same surface.

## Install

```bash
pip install pgbeam
```

Python 3.10 or newer. The only runtime dependency is [httpx](https://www.python-httpx.org/).

## Usage

```python
from pgbeam import PgBeamClient

with PgBeamClient(token="your-api-key") as client:
    # Tag-based access, one attribute per API area
    projects = client.projects.list_projects(org_id="org_123")

    for project in projects["projects"]:
        print(project["id"], project["name"])

    project = client.projects.get_project(project_id="prj_123")
```

Omit `token` and the client reads `PGBEAM_API_KEY` from the environment (`PGBEAM_TOKEN` and `PGBEAM_API_TOKEN` are accepted as aliases, the same order the CLI and the Terraform, Crossplane and Pulumi providers use). `PGBEAM_API_URL` overrides the base URL.

### Async

The async client is the same surface with `await` in front of it. Same method names, same arguments, same return types.

```python
import asyncio
from pgbeam import AsyncPgBeamClient


async def main() -> None:
    async with AsyncPgBeamClient(token="your-api-key") as client:
        projects = await client.projects.list_projects(org_id="org_123")
        print(len(projects["projects"]))


asyncio.run(main())
```

## Types

Every request and response body is a `TypedDict` in `pgbeam.models`, and the package ships a `py.typed` marker, so mypy and pyright check your calls against the API contract.

```python
from pgbeam import PgBeamClient
from pgbeam.models import CreateProjectRequest, Project

body: CreateProjectRequest = {
    "org_id": "org_123",
    "name": "analytics",
    "region": "us-east-1",
}

with PgBeamClient() as client:
    created = client.projects.create_project(body=body)
    project: Project = created["project"]
```

Timestamps are RFC 3339 strings, exactly as the API sends them. They are deliberately not parsed into `datetime`, so what you read is what came over the wire.

## Error handling

`ApiError` means the API answered and the answer was an error. `NetworkError` means it never answered at all: DNS failure, a refused or reset connection, or a timeout.

```python
from pgbeam import ApiError, NetworkError, PgBeamClient

with PgBeamClient() as client:
    try:
        client.projects.get_project(project_id="prj_123")
    except ApiError as err:
        print(err.status, err)  # 404 Project not found
        print(err.body)  # the decoded error body
    except NetworkError as err:
        print(err.url, err.attempts, err.timed_out)
```

## Retries and timeouts

Every call retries 408, 429, 502, 503 and 504 up to five times with jittered exponential backoff, honouring `Retry-After` when the server sends one. A `POST` or `PATCH` that is retried carries one `Idempotency-Key` across all its attempts, so a retry of a request the server already accepted is not a second write.

Three bounds apply, in the order they bite: a 30 second per-attempt timeout, a five-retry ceiling, and a 120 second budget for the whole call measured from the first attempt. A retry that would land past the budget is not made.

```python
from pgbeam import PgBeamClient, RetryConfig

with PgBeamClient(
    timeout_ms=10_000,
    retry=RetryConfig(max_retries=2, total_budget_ms=30_000),
) as client:
    ...

# No retrying at all
with PgBeamClient(retry=RetryConfig(max_retries=0)) as client:
    ...
```

The TypeScript SDK applies the same policy with the same defaults, so a 429 or a 409 means the same thing whichever one you reach for.

### Bring your own HTTP client

Pass an `httpx.Client` (or `httpx.AsyncClient`) to share a connection pool, route through a proxy, or install a custom transport. A client you supply is yours to close.

```python
import httpx
from pgbeam import PgBeamClient

http = httpx.Client(proxy="http://localhost:8080")
client = PgBeamClient(token="...", http_client=http)
```

## Operations map

`pgbeam.OPERATIONS_BY_TAG` and `pgbeam.OPERATIONS_BY_PATH` carry every operation's method and path, for building tooling on top of the SDK.

```python
from pgbeam import OPERATIONS_BY_PATH

print(OPERATIONS_BY_PATH["GET /v1/projects/{project_id}"])
# OperationMeta(method='GET', path='/v1/projects/{project_id}')
```

## Documentation

Full API reference at [pgbeam.com/docs/python-sdk](https://pgbeam.com/docs/python-sdk).

## Contributing

Issues and pull requests are welcome here. An issue is the right place to start for a bug, a wrong doc, or a missing capability; say what you ran, what happened, what you expected, and which version you were on.

`models.py`, `operations.py` and `services.py` are generated from the OpenAPI specification and carry a `DO NOT EDIT` header. A change to any of them belongs in the specification, not in the file. Everything else is ordinary hand-written Python.

To build and test it locally:

```bash
uv sync --all-groups
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

Do not open a public issue for a suspected security vulnerability. Email security@pgbeam.com, or report it privately from this repository's Security tab.

## License

Apache 2.0, see [LICENSE](LICENSE).
