import pathlib
import sys
from uuid import uuid4

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

pytest.importorskip("jwt")
pytest.importorskip("argon2")

from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hash_and_verify_roundtrip() -> None:
    raw = "my-secure-password"
    encoded = hash_password(raw)
    assert encoded.startswith("$argon2")
    assert verify_password(raw, encoded) is True
    assert verify_password("wrong-password", encoded) is False


def test_access_token_roundtrip() -> None:
    user_id = uuid4()
    token, _exp = create_access_token(
        user_id=user_id,
        secret_key="test-secret",
        algorithm="HS256",
        issuer="test-issuer",
        ttl_minutes=10,
    )
    decoded = decode_access_token(
        token=token,
        secret_key="test-secret",
        algorithm="HS256",
        issuer="test-issuer",
    )
    assert decoded == user_id


def test_access_token_invalid_secret() -> None:
    user_id = uuid4()
    token, _exp = create_access_token(
        user_id=user_id,
        secret_key="secret-a",
        algorithm="HS256",
        issuer="test-issuer",
        ttl_minutes=10,
    )
    decoded = decode_access_token(
        token=token,
        secret_key="secret-b",
        algorithm="HS256",
        issuer="test-issuer",
    )
    assert decoded is None


def test_refresh_token_roundtrip_and_hash() -> None:
    user_id = uuid4()
    token, jti, exp_ts = create_refresh_token(
        user_id=user_id,
        secret_key="test-secret",
        algorithm="HS256",
        issuer="test-issuer",
        ttl_days=30,
    )
    decoded = decode_refresh_token(
        token=token,
        secret_key="test-secret",
        algorithm="HS256",
        issuer="test-issuer",
    )
    assert decoded == (user_id, jti, exp_ts)
    assert len(hash_token(token)) == 64
