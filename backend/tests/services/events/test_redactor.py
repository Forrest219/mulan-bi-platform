"""单元测试：Payload 脱敏（Redactor）"""
import pytest
from services.events.redactor import redact_payload, _redact_string, SENSITIVE_FIELD_PATTERNS, REDACTED


class TestRedactPayload:
    """测试 payload 脱敏"""

    def test_preserve_non_sensitive_fields(self):
        payload = {"event_type": "tableau.sync.failed", "connection_id": 1, "connection_name": "Test"}
        result = redact_payload(payload)
        assert result["event_type"] == "tableau.sync.failed"
        assert result["connection_id"] == 1
        assert result["connection_name"] == "Test"

    def test_redact_password_field(self):
        payload = {"username": "admin", "password": "secret123"}
        result = redact_payload(payload)
        assert result["password"] == REDACTED
        assert result["username"] == "admin"

    def test_redact_token_field(self):
        payload = {"api_token": "sk-abc123xyz", "endpoint": "/api/data"}
        result = redact_payload(payload)
        assert result["api_token"] == REDACTED
        assert result["endpoint"] == "/api/data"

    def test_redact_nested_dict(self):
        payload = {
            "connection": {
                "name": "Prod DB",
                "password": "secret",
            }
        }
        result = redact_payload(payload)
        assert result["connection"]["name"] == "Prod DB"
        assert result["connection"]["password"] == REDACTED

    def test_redact_array_fields(self):
        payload = {
            "connections": [
                {"name": "DB1", "password": "pass1"},
                {"name": "DB2", "password": "pass2"},
            ]
        }
        result = redact_payload(payload)
        assert result["connections"][0]["name"] == "DB1"
        assert result["connections"][0]["password"] == REDACTED

    def test_case_insensitive_field_matching(self):
        """字段名大小写不敏感"""
        payload = {"PASSWORD": "secret", "Token": "abc123", "API_KEY": "key123"}
        result = redact_payload(payload)
        assert result["PASSWORD"] == REDACTED
        assert result["Token"] == REDACTED
        assert result["API_KEY"] == REDACTED

    def test_original_payload_unchanged(self):
        """脱敏不修改原对象"""
        payload = {"username": "admin", "password": "secret"}
        original = dict(payload)
        redact_payload(payload)
        assert payload == original


class TestRedactString:
    """测试字符串脱敏"""

    def test_openai_key_redacted(self):
        input_str = "Bearer sk-1234567890abcdefghijklmnopqrstuvwxyz"
        result = _redact_string(input_str)
        assert REDACTED in result
        assert "sk-" not in result

    def test_generic_bearer_token_redacted(self):
        input_str = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = _redact_string(input_str)
        assert REDACTED in result

    def test_preserve_normal_text(self):
        input_str = "This is normal text without tokens"
        result = _redact_string(input_str)
        assert result == input_str

    def test_long_hex_strings_redacted(self):
        """长 hex 字符串（如 secret）被脱敏"""
        input_str = "secret_key_1234567890abcdefghijklmnopqrstuvwxyz1234567890abcdef"
        result = _redact_string(input_str)
        # Long hex strings should be replaced
        assert REDACTED in result


class TestSensitiveFieldPatterns:
    """测试敏感字段名模式"""

    @pytest.mark.parametrize("field_name,should_match", [
        ("password", True),
        ("PASSWORD", True),
        ("password123", True),
        ("api_key", True),
        ("apiKey", True),
        ("APIKEY", True),
        ("auth_token", True),
        ("authorization", True),
        ("credential", True),
        ("secret", True),
        ("secret_key", True),
        ("private_key", True),
        ("bearer", True),
        ("event_type", False),
        ("connection_name", False),
        ("health_score", False),
        ("user_id", False),
    ])
    def test_field_name_patterns(self, field_name, should_match):
        matched = any(p.search(field_name) for p in SENSITIVE_FIELD_PATTERNS)
        assert matched == should_match