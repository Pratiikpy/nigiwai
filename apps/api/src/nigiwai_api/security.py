"""Passwords, session tokens, CSRF tokens, signed nonces and daily-salted IP hashes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2id with the library's current defaults (RFC 9106 low-memory profile or stronger).
_hasher = PasswordHasher()
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200


class WeakPassword(ValueError):
    pass


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    """Known-breached passwords of 10 or more characters (the shorter ones fail the length rule anyway)."""
    path = Path(__file__).resolve().parent / "assets" / "common_passwords.txt"
    return frozenset(path.read_text(encoding="utf-8").split())


def check_password_policy(password: str, email: str) -> None:
    """Length is what matters (NIST SP 800-63B): at least 10, at most 200, and not the email or a trivial repeat."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"use at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPassword(f"use at most {MAX_PASSWORD_LENGTH} characters")
    lowered = password.lower()
    if lowered == email.lower() or lowered.split("@")[0] == email.lower().split("@")[0]:
        raise WeakPassword("the password must not be your email")
    if len(set(password)) < 5:
        raise WeakPassword("the password is too repetitive")
    if lowered in _common_passwords():
        raise WeakPassword(
            "that password is on lists of passwords attackers try first; choose another"
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# A hash of a random string, verified against when the account does not exist so login time does not reveal it.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def new_token(nbytes: int = 32) -> str:
    """URL-safe random token. 32 bytes is 256 bits; QR tokens use 16 bytes (128 bits) as in ARCHITECTURE 7."""
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _mac(secret: str, *parts: str) -> bytes:
    return hmac.new(
        secret.encode("utf-8"), "\x1f".join(parts).encode("utf-8"), hashlib.sha256
    ).digest()


def csrf_token(secret_key: str, csrf_secret: str) -> str:
    return base64.urlsafe_b64encode(_mac(secret_key, "csrf", csrf_secret)).decode().rstrip("=")


def check_csrf(secret_key: str, csrf_secret: str, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(csrf_token(secret_key, csrf_secret), presented)


# ---- signed nonces for the public survey (single use, short lived) -------------------------------------------
def make_nonce(
    secret_key: str, qr_hash_hex: str, ttl_seconds: int, now: float | None = None
) -> str:
    """`nonce_id.expiry.mac`. The id makes it single-use (stored in Redis on use); the mac binds it to the QR point."""
    expiry = int((now if now is not None else time.time()) + ttl_seconds)
    nonce_id = secrets.token_urlsafe(12)
    mac = (
        base64.urlsafe_b64encode(_mac(secret_key, "nonce", nonce_id, str(expiry), qr_hash_hex))
        .decode()
        .rstrip("=")
    )
    return f"{nonce_id}.{expiry}.{mac}"


def parse_nonce(
    secret_key: str, qr_hash_hex: str, nonce: str, now: float | None = None
) -> tuple[str, int] | None:
    """Return (nonce_id, issued_at_estimate) when the nonce is genuine for this QR point and not expired."""
    try:
        nonce_id, expiry_s, mac = nonce.split(".")
        expiry = int(expiry_s)
    except ValueError:
        return None
    expected = (
        base64.urlsafe_b64encode(_mac(secret_key, "nonce", nonce_id, str(expiry), qr_hash_hex))
        .decode()
        .rstrip("=")
    )
    if not hmac.compare_digest(expected, mac):
        return None
    if expiry < (now if now is not None else time.time()):
        return None
    return nonce_id, expiry


def ip_hash(secret_key: str, ip: str, day: str | None = None) -> str:
    """Daily-rotating salted hash of an IP address. It lives only in Redis and expires within 24 hours."""
    day = day or datetime.now(UTC).strftime("%Y-%m-%d")
    return base64.urlsafe_b64encode(_mac(secret_key, "ip", day, ip))[:22].decode()


def canonical_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
