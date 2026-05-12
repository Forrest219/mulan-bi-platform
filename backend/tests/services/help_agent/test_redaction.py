from services.help_agent.redaction import redact_text, redact_value


def test_redact_mapping_secrets_without_leaking_originals():
    payload = {
        "password": "plain-password",
        "access_token": "tok_1234567890abcdef",
        "headers": {
            "Authorization": "Bearer secret-token",
            "Cookie": "sessionid=secret-cookie",
        },
        "nested": "api_key=sk-proj-1234567890 password=hunter2",
    }

    redacted = redact_value(payload)
    rendered = str(redacted)

    assert redacted["password"] == "******"
    assert redacted["access_token"].startswith("tok_")
    assert redacted["access_token"].endswith("cdef")
    assert "plain-password" not in rendered
    assert "secret-token" not in rendered
    assert "secret-cookie" not in rendered
    assert "hunter2" not in rendered
    assert "sk-proj-1234567890" not in rendered


def test_redact_private_key_block_and_headers():
    text = """
Authorization: Bearer abcdef123456
-----BEGIN PRIVATE KEY-----
super-secret-key-material
-----END PRIVATE KEY-----
cookie=session=abcdef
"""

    redacted = redact_text(text)

    assert "abcdef123456" not in redacted
    assert "super-secret-key-material" not in redacted
    assert "session=abcdef" not in redacted
    assert "******" in redacted


def test_redact_does_not_treat_path_as_pat_secret():
    redacted = redact_value({"path": "/agents/agent-monitor", "pat": "plain-pat-secret"})

    assert redacted["path"] == "/agents/agent-monitor"
    assert redacted["pat"] == "******"
