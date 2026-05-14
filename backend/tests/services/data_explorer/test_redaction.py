import pytest

from services.data_explorer.redaction import MASK, redact_preview, redact_preview_rows

pytestmark = pytest.mark.skip_db


def test_redact_preview_masks_english_chinese_and_pinyin_sensitive_columns():
    columns = [
        {"name": "id"},
        {"name": "Password"},
        {"name": "api_key"},
        {"name": "Token"},
        {"name": "电话"},
        {"name": "shouji"},
        {"name": "email"},
        {"name": "身份证"},
        {"name": "shenfenzheng"},
        {"name": "comment"},
    ]
    rows = [
        [
            1,
            "plain-password",
            "key-123",
            "token-456",
            "01012345678",
            13800138000,
            "alice@example.com",
            "110101199001011234",
            "secret-id",
            "normal value",
        ],
        [2, None, None, None, None, None, None, None, None, "safe"],
    ]

    result = redact_preview(columns, rows)

    assert result["redaction_applied"] is True
    assert result["columns"] == columns
    assert result["columns"] is not columns
    assert result["rows"][0] == [
        1,
        MASK,
        MASK,
        MASK,
        "*******5678",
        "*******8000",
        "a****@example.com",
        MASK,
        MASK,
        "normal value",
    ]
    assert result["rows"][1] == [2, None, None, None, None, None, None, None, None, "safe"]


def test_redact_preview_does_not_mutate_input_or_leak_sensitive_values():
    columns = [{"name": "密码"}, {"name": "mobile"}, {"name": "note"}]
    rows = [["原始密码", "13900001234", "普通值"]]

    result = redact_preview(columns, rows)

    assert rows == [["原始密码", "13900001234", "普通值"]]
    assert "原始密码" not in repr(result)
    assert "13900001234" not in repr(result)
    assert result["rows"] == [[MASK, "*******1234", "普通值"]]


def test_redact_preview_supports_dict_rows_case_insensitive_keys():
    columns = [{"name": "EMAIL"}, {"name": "Phone"}, {"name": "证件号"}, {"name": "name"}]
    rows = [
        {
            "email": "bob@example.com",
            "phone": "1234",
            "证件号": 1234567890,
            "name": "Bob",
        }
    ]

    result = redact_preview(columns, rows)

    assert result["rows"] == [
        {
            "email": "b**@example.com",
            "phone": MASK,
            "证件号": MASK,
            "name": "Bob",
        }
    ]


def test_redact_preview_rows_returns_only_rows_and_keeps_non_sensitive_values():
    columns = ["id", "amount", "created_at"]
    rows = [(1, 99.5, "2026-05-13")]

    result = redact_preview_rows(columns, rows)

    assert result == [(1, 99.5, "2026-05-13")]
