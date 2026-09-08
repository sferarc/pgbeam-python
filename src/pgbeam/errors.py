"""What a failed call raises.

The taxonomy is the TypeScript SDK's, deliberately: ``ApiError`` means the
server answered and the answer was an error, ``NetworkError`` means it never
answered at all. Both SDKs draw the line in the same place so a runbook written
against one is true of the other, and so a 429 or a 409 means the same thing in
both.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ApiError", "NetworkError", "PgBeamError", "describe_error", "extract_message"]


class PgBeamError(Exception):
    """Base class for everything this SDK raises."""


class ApiError(PgBeamError):
    """The API answered, and the answer was an error status.

    ``status`` is the HTTP status code, ``body`` the decoded response body when
    there was one. The message is pulled out of the body where the API supplied
    one, because ``{"error": {"code": ..., "message": ...}}`` is what PgBeam
    sends and a bare "Conflict" tells a reader nothing.
    """

    status: int
    status_text: str
    body: Any

    def __init__(self, status: int, status_text: str, body: Any) -> None:
        message = extract_message(body) or status_text or f"HTTP {status}"
        super().__init__(message)
        self.status = status
        self.status_text = status_text
        self.body = body

    def __repr__(self) -> str:
        return f"ApiError(status={self.status!r}, message={str(self)!r})"


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
    """Pull a human-readable message out of an API error body."""
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    message = body.get("message")
    if isinstance(message, str):
        return message
    return None


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
