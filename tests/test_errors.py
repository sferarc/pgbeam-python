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


PROBLEM = {
    "type": "https://pgbeam.com/docs/api/errors/plan-limit-reached",
    "title": "Plan limit reached",
    "status": 403,
    "detail": "the Starter plan allows 3 projects",
    "instance": "/v1/projects",
    "code": "PLAN_LIMIT_REACHED",
    "request_id": "req_abc123",
    "errors": [
        {"field": "database.host", "detail": "database host is required"},
        {"field": "name"},
        "not an object",
    ],
}


class TestProblemDocument:
    def test_lifts_every_field_off_a_full_document(self) -> None:
        error = ApiError(403, "Forbidden", PROBLEM)
        assert str(error) == "the Starter plan allows 3 projects"
        assert error.code == "PLAN_LIMIT_REACHED"
        assert error.type == PROBLEM["type"]
        assert error.title == "Plan limit reached"
        assert error.detail == "the Starter plan allows 3 projects"
        assert error.instance == "/v1/projects"
        assert error.request_id == "req_abc123"
        assert error.errors == [{"field": "database.host", "detail": "database host is required"}]
        assert error.status == 403
        assert error.status_text == "Forbidden"
        assert error.body is PROBLEM

    def test_uses_the_title_when_there_is_no_detail(self) -> None:
        body = {"type": "about:blank", "title": "Forbidden", "status": 403, "code": "FORBIDDEN"}
        error = ApiError(403, "", body)
        assert str(error) == "Forbidden"
        assert error.code == "FORBIDDEN"
        assert error.detail is None

    def test_a_title_without_a_status_is_not_a_problem_document(self) -> None:
        assert extract_message({"title": "a project name"}) is None

    def test_detail_wins_over_the_legacy_shapes(self) -> None:
        body = {"detail": "from detail", "error": {"message": "nested"}, "message": "flat"}
        assert extract_message(body) == "from detail"

    def test_fields_are_empty_when_the_body_is_not_a_problem_document(self) -> None:
        error = ApiError(502, "Bad Gateway", "<html>upstream down</html>")
        assert str(error) == "Bad Gateway"
        assert error.code is None
        assert error.type is None
        assert error.title is None
        assert error.detail is None
        assert error.instance is None
        assert error.request_id is None
        assert error.errors == []

    def test_legacy_nested_body_still_names_the_message(self) -> None:
        error = ApiError(409, "Conflict", {"error": {"code": "conflict", "message": "exists"}})
        assert str(error) == "exists"
        assert error.code is None

    def test_legacy_flat_body_still_names_the_message(self) -> None:
        assert str(ApiError(400, "Bad Request", {"message": "bad input"})) == "bad input"


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
