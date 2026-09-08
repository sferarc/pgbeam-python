"""The error taxonomy, which both SDKs have to agree about."""

from __future__ import annotations

from pgbeam.errors import ApiError, NetworkError, PgBeamError, describe_error, extract_message


class TestExtractMessage:
    def test_prefers_the_nested_error_object(self) -> None:
        body = {"error": {"code": "conflict", "message": "already exists"}, "message": "outer"}
        assert extract_message(body) == "already exists"

    def test_falls_back_to_a_top_level_message(self) -> None:
        assert extract_message({"message": "plain"}) == "plain"

    def test_returns_none_for_anything_else(self) -> None:
        assert extract_message("not a dict") is None
        assert extract_message({"error": "a string"}) is None
        assert extract_message(None) is None


class TestApiError:
    def test_uses_the_status_text_when_the_body_says_nothing(self) -> None:
        error = ApiError(500, "Internal Server Error", None)
        assert str(error) == "Internal Server Error"

    def test_falls_back_to_the_status_when_there_is_no_text_either(self) -> None:
        assert str(ApiError(500, "", None)) == "HTTP 500"

    def test_keeps_the_body_for_inspection(self) -> None:
        body = {"error": {"code": "quota_exceeded", "message": "over budget"}}
        error = ApiError(429, "Too Many Requests", body)
        assert error.body == body
        assert error.status == 429

    def test_is_a_pgbeam_error(self) -> None:
        assert isinstance(ApiError(400, "Bad Request", None), PgBeamError)


class TestNetworkError:
    def test_names_the_call_and_the_reason(self) -> None:
        error = NetworkError(
            method="GET",
            url="https://api.pgbeam.com/v1/projects",
            attempts=3,
            elapsed_ms=1500,
            timed_out=False,
            timeout_ms=30_000,
            cause=ConnectionRefusedError("refused"),
        )
        assert "GET https://api.pgbeam.com/v1/projects" in str(error)
        assert "3 attempt(s)" in str(error)
        assert "refused" in str(error)

    def test_a_timeout_reports_the_ceiling_it_hit(self) -> None:
        error = NetworkError(
            method="POST",
            url="https://api.pgbeam.com/v1/projects",
            attempts=1,
            elapsed_ms=30_001,
            timed_out=True,
            timeout_ms=30_000,
            cause=None,
        )
        assert "timed out after 30000ms" in str(error)
        assert error.timed_out is True


class TestDescribeError:
    def test_flattens_a_cause_chain(self) -> None:
        inner = ConnectionRefusedError("ECONNREFUSED 10.0.0.1:5432")
        outer = OSError("transport failed")
        outer.__cause__ = inner
        described = describe_error(outer)
        assert "OSError: transport failed" in described
        assert "ECONNREFUSED 10.0.0.1:5432" in described

    def test_stops_before_a_cycle_runs_away(self) -> None:
        a = OSError("a")
        b = OSError("b")
        a.__cause__ = b
        b.__cause__ = a
        described = describe_error(a)
        assert described.endswith("...))))))")
        assert described.count("caused by") == 6

    def test_handles_no_error_at_all(self) -> None:
        assert describe_error(None) == "None"
