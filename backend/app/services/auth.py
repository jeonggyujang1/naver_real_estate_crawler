import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

password_hasher = PasswordHasher()


def _b64decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _verify_legacy_scrypt(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = encoded_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False

    try:
        salt = _b64decode(salt_b64)
        expected = _b64decode(digest_b64)
    except Exception:
        return False
    candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=64)
    return hmac.compare_digest(candidate, expected)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    if encoded_hash.startswith("scrypt$"):
        return _verify_legacy_scrypt(password, encoded_hash)
    try:
        return password_hasher.verify(encoded_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def maybe_rehash_password(password: str, encoded_hash: str) -> str | None:
    if encoded_hash.startswith("scrypt$"):
        if _verify_legacy_scrypt(password, encoded_hash):
            return password_hasher.hash(password)
        return None
    try:
        if password_hasher.check_needs_rehash(encoded_hash):
            return password_hasher.hash(password)
    except Exception:
        return None
    return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    user_id: UUID,
    secret_key: str,
    algorithm: str,
    issuer: str,
    ttl_minutes: int,
) -> tuple[str, int]:
    now = datetime.now(UTC)
    exp_at = now + timedelta(minutes=ttl_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid4()),
        "iss": issuer,
        "iat": int(now.timestamp()),
        "exp": int(exp_at.timestamp()),
    }
    token = jwt.encode(payload=payload, key=secret_key, algorithm=algorithm)
    return token, int(exp_at.timestamp())


def create_refresh_token(
    user_id: UUID,
    secret_key: str,
    algorithm: str,
    issuer: str,
    ttl_days: int,
) -> tuple[str, str, int]:
    now = datetime.now(UTC)
    exp_at = now + timedelta(days=ttl_days)
    jti = str(uuid4())
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": jti,
        "iss": issuer,
        "iat": int(now.timestamp()),
        "exp": int(exp_at.timestamp()),
        "nonce": secrets.token_hex(8),
    }
    token = jwt.encode(payload=payload, key=secret_key, algorithm=algorithm)
    return token, jti, int(exp_at.timestamp())


def decode_token(token: str, secret_key: str, algorithms: list[str], issuer: str) -> dict | None:
    try:
        payload = jwt.decode(jwt=token, key=secret_key, algorithms=algorithms, issuer=issuer)
        return payload
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str, secret_key: str, algorithm: str, issuer: str) -> UUID | None:
    payload = decode_token(token=token, secret_key=secret_key, algorithms=[algorithm], issuer=issuer)
    if payload is None or payload.get("type") != "access":
        return None
    try:
        return UUID(str(payload.get("sub")))
    except ValueError:
        return None


def decode_refresh_token(token: str, secret_key: str, algorithm: str, issuer: str) -> tuple[UUID, str, int] | None:
    payload = decode_token(token=token, secret_key=secret_key, algorithms=[algorithm], issuer=issuer)
    if payload is None or payload.get("type") != "refresh":
        return None
    try:
        user_id = UUID(str(payload.get("sub")))
        jti = str(payload.get("jti"))
        exp_ts = int(payload.get("exp"))
    except (ValueError, TypeError):
        return None
    if not jti:
        return None
    return user_id, jti, exp_ts
