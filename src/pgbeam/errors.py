"""What a failed call raises.

The taxonomy is the TypeScript SDK's, deliberately: ``ApiError`` means the
server answered and the answer was an error, ``NetworkError`` means it never
answered at all. Both SDKs draw the line in the same place so a runbook written
against one is true of the other, and so a 429 or a 409 means the same thing in
both.
"""

from __future__ import annotations

from typing import Any

from .models import FieldError

__all__ = ["ApiError", "NetworkError", "PgBeamError", "describe_error", "extract_message"]


class PgBeamError(Exception):
    """Base class for everything this SDK raises."""


class ApiError(PgBeamError):
    """The API answered, and the answer was an error status.

    The API answers every error with an RFC 9457 problem document, so its
    fields are lifted onto the error rather than left in ``body``. They are
    ``None`` (``errors`` empty) when the body is not a problem document.

    Branch on ``code``, not on the message: a 403 is either ``FORBIDDEN`` or
    ``PLAN_LIMIT_REACHED``, and those are resolved in completely different
    ways. The message is prose and may change between releases.
    """

    status: int
    status_text: str
    body: Any
    code: str | None
    type: str | None
    title: str | None
    detail: str | None
    instance: str | None
    request_id: str | None
    errors: list[FieldError]

    def __init__(self, status: int, status_text: str, body: Any) -> None:
        message = extract_message(body) or status_text or f"HTTP {status}"
        super().__init__(message)
        self.status = status
        self.status_text = status_text
        self.body = body
        problem: dict[str, Any] = body if isinstance(body, dict) else {}
        self.code = _str(problem.get("code"))
        self.type = _str(problem.get("type"))
        self.title = _str(problem.get("title"))
        self.detail = _str(problem.get("detail"))
        self.instance = _str(problem.get("instance"))
        self.request_id = _str(problem.get("request_id"))
        self.errors = _field_errors(problem.get("errors"))

    def __repr__(self) -> str:
        return f"ApiError(status={self.status!r}, code={self.code!r}, message={str(self)!r})"


class NetworkError(PgBeamError):
    """The request never got an HTTP answer.

    DNS failure, a refused or reset connection, or a timeout. The message names
    the URL, the number of attempts made and the wall-clock time spent, because
    a bare "connection error" sends the reader looking for which call it was.

    ``timed_out`` is the field worth branching on: a caller that retries on its
    own should not retry a call this SDK already spent its whole budget on.
    """

    url: str
    method: str
    attempts: int
    elapsed_ms: int
    timed_out: bool

    def __init__(
        self,
        *,
        method: str,
        url: str,
        attempts: int,
        elapsed_ms: int,
        timed_out: bool,
        timeout_ms: int,
        cause: BaseException | None,
    ) -> None:
        reason = f"timed out after {timeout_ms}ms" if timed_out else describe_error(cause)
        super().__init__(
            f"{method} {url} failed after {attempts} attempt(s) in {elapsed_ms}ms: {reason}"
        )
        self.url = url
        self.method = method
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms
        self.timed_out = timed_out
        self.__cause__ = cause


def extract_message(body: Any) -> str | None:
    """Pull a human-readable message out of an API error body.

    A problem document's ``detail`` comes first. The legacy shapes are still
    read because the edge MCP endpoint answers ``{"error": {"message": ...}}``
    and Echo's default is ``{"message": ...}``.
    """
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if isinstance(detail, str):
        return detail
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    message = body.get("message")
    if isinstance(message, str):
        return message
    title = body.get("title")
    if isinstance(title, str) and _is_status(body.get("status")):
        return title
    return None


def _is_status(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _field_errors(value: Any) -> list[FieldError]:
    if not isinstance(value, list):
        return []
    return [
        FieldError(field=entry["field"], detail=entry["detail"])
        for entry in value
        if isinstance(entry, dict)
        and isinstance(entry.get("field"), str)
        and isinstance(entry.get("detail"), str)
    ]


def describe_error(err: BaseException | None, depth: int = 0) -> str:
    """Flatten an exception and its ``__cause__`` chain into one line.

    ``ConnectError`` on its own says nothing. The useful detail (which host, and
    whether it was refused, reset or unresolvable) is one or two levels down.
    """
    if err is None:
        return "None"
    if depth > 5:
        return "..."
    head = f"{type(err).__name__}: {err}"
    cause = err.__cause__ or err.__context__
    if cause is not None and cause is not err:
        return f"{head} (caused by {describe_error(cause, depth + 1)})"
    return head
