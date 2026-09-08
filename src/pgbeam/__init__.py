"""Python SDK for the PgBeam API.

    from pgbeam import PgBeamClient

    with PgBeamClient(token="pgb_...") as client:
        projects = client.projects.list_projects(org_id="org_123")
        for project in projects["projects"]:
            print(project["id"], project["name"])

Every request and response body is a ``TypedDict`` in :mod:`pgbeam.models`, so a
type checker knows the shape of what comes back without anything having to be
unwrapped first. The async client is the same surface with ``await`` in front of
it:

    from pgbeam import AsyncPgBeamClient

    async with AsyncPgBeamClient(token="pgb_...") as client:
        projects = await client.projects.list_projects(org_id="org_123")
"""

from __future__ import annotations

from . import models as models
from ._client import BASE_URL_ENV_VAR, DEFAULT_BASE_URL, TOKEN_ENV_VARS
from ._transport import RETRYABLE_STATUS, RetryConfig
from .errors import ApiError, NetworkError, PgBeamError, describe_error, extract_message
from .operations import OPERATIONS_BY_PATH, OPERATIONS_BY_TAG, OperationMeta
from .services import AsyncPgBeamClient, PgBeamClient

__all__ = [
    "BASE_URL_ENV_VAR",
    "DEFAULT_BASE_URL",
    "OPERATIONS_BY_PATH",
    "OPERATIONS_BY_TAG",
    "RETRYABLE_STATUS",
    "TOKEN_ENV_VARS",
    "ApiError",
    "AsyncPgBeamClient",
    "NetworkError",
    "OperationMeta",
    "PgBeamClient",
    "PgBeamError",
    "RetryConfig",
    "describe_error",
    "extract_message",
    "models",
]
