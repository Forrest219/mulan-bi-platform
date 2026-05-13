from services.agent_observability.structured_error import StructuredBIError, best_effort_structured_error


def test_structured_error_from_exception_redacts_message_and_chain():
    try:
        try:
            raise ValueError("password=secret-password")
        except ValueError as cause:
            raise RuntimeError("Authorization: Bearer abcdef123456") from cause
    except RuntimeError as exc:
        payload = StructuredBIError.from_exception(exc, error_code="AGENT_003").to_dict()

    rendered = str(payload)
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_code"] == "AGENT_003"
    assert payload["redaction_applied"] is True
    assert "abcdef123456" not in rendered
    assert "secret-password" not in rendered
    assert payload["caused_by"][0]["type"] == "ValueError"


def test_best_effort_structured_error_from_message():
    payload = best_effort_structured_error("refresh_token=abcd12345678wxyz", error_code="MCP_010")

    assert payload["error_type"] == "Error"
    assert payload["error_code"] == "MCP_010"
    assert "abcd12345678wxyz" not in str(payload)
    assert "abcd******wxyz" in str(payload)


def test_best_effort_structured_error_keeps_structured_dict():
    payload = best_effort_structured_error({
        "error_type": "TimeoutError",
        "message": "provider timeout",
        "error_code": "AGENT_006",
        "caused_by": [{"type": "ReadTimeout", "message": "token=abcd12345678wxyz"}],
    })

    assert payload["error_type"] == "TimeoutError"
    assert payload["error_code"] == "AGENT_006"
    assert payload["caused_by"][0]["type"] == "ReadTimeout"
    assert "abcd12345678wxyz" not in str(payload)
