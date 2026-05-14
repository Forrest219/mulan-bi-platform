import base64

import pytest

from services.data_explorer.table_ref import (
    TABLE_REF_ERROR_CODE,
    TableRefError,
    decode_table_ref,
    encode_table_ref,
)

pytestmark = pytest.mark.skip_db


def test_encode_decode_table_ref_uses_unpadded_base64url_with_nul_separator():
    encoded = encode_table_ref("public", "orders")

    assert encoded == "cHVibGljAG9yZGVycw"
    assert "=" not in encoded
    assert decode_table_ref(encoded) == ("public", "orders")


def test_encode_decode_preserves_case_special_chars_and_unicode():
    encoded = encode_table_ref("销售Schema", "Order/明细 表")

    assert "=" not in encoded
    assert "/" not in encoded
    assert decode_table_ref(encoded) == ("销售Schema", "Order/明细 表")


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("publicorders", "exactly one NUL"),
        ("public\x00orders\x00archive", "exactly one NUL"),
        ("\x00orders", "schema must not be empty"),
        ("public\x00", "table must not be empty"),
    ],
)
def test_decode_rejects_missing_extra_or_empty_parts(payload, reason):
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")

    with pytest.raises(TableRefError) as exc_info:
        decode_table_ref(encoded)

    assert exc_info.value.code == TABLE_REF_ERROR_CODE
    assert reason in exc_info.value.reason


@pytest.mark.parametrize(
    "invalid_ref",
    [
        "!!!!",
        "abc=def",
        "abc+def",
        "abc/def",
        "A",
        "",
    ],
)
def test_decode_rejects_invalid_base64url(invalid_ref):
    with pytest.raises(TableRefError) as exc_info:
        decode_table_ref(invalid_ref)

    assert exc_info.value.code == "DEX_001"


@pytest.mark.parametrize(
    ("schema", "table", "reason"),
    [
        ("", "orders", "schema must not be empty"),
        ("public", "", "table must not be empty"),
        ("public\x00extra", "orders", "must not contain NUL"),
        ("public", "orders\x00extra", "must not contain NUL"),
    ],
)
def test_encode_rejects_invalid_parts(schema, table, reason):
    with pytest.raises(TableRefError) as exc_info:
        encode_table_ref(schema, table)

    assert exc_info.value.code == "DEX_001"
    assert reason in exc_info.value.reason
