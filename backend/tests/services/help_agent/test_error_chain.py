import time

from services.help_agent.error_chain import read_structured_error


def test_read_structured_error_prefers_json_and_redacts_it():
    result = read_structured_error(
        structured_error={
            "error_type": "TableauMCPError",
            "message": "token=abcd12345678expired",
            "error_code": "MCP_010",
        },
        legacy_error_text="ValueError: should not be used",
        source="task_run.error_message",
    )

    assert result["source"] == "structured_error"
    assert result["error_type"] == "TableauMCPError"
    assert result["error_code"] == "MCP_010"
    assert "abcd12345678expired" not in str(result)
    assert result["redaction_applied"] is True


def test_legacy_fallback_marks_source_and_extracts_error():
    result = read_structured_error(
        legacy_error_text='File "/app/backend/services/tableau/mcp_client.py", line 10, in execute\n'
        "TableauMCPError: Tableau token expired MCP_010",
        source="task_run.error_message",
    )

    assert result["source"] == "legacy_fallback"
    assert result["legacy_source"] == "task_run.error_message"
    assert result["error_type"] == "TableauMCPError"
    assert result["error_code"] == "MCP_010"
    assert result["business_frames"] == ["services.tableau.mcp_client.execute"]


def test_legacy_fallback_hard_truncates_long_input_and_does_not_hang():
    legacy = ("(" * 200_000) + "\nTailError: should not be parsed after cutoff"

    started = time.perf_counter()
    result = read_structured_error(legacy_error_text=legacy)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    assert result["source"] == "legacy_fallback_failed"
    assert "TailError" not in str(result)
    assert len(result["summary"]) <= 500
