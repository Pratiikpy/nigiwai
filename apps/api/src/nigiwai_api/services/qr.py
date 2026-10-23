"""QR points: the secret token printed in each QR code, kept hashed for lookup and encrypted so an owner can
reprint the poster (decision D9). The token is the only credential a guest's phone presents."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..security import new_token, token_hash

TOKEN_BYTES = 18  # 24 URL-safe characters, 144 bits


def _key(secret_key: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"nigiwai-qr-token-v1"
    ).derive(secret_key.encode("utf-8"))


@dataclass(frozen=True)
class SealedToken:
    token: str
    hash: bytes
    enc: bytes
    hint: str


def mint(secret_key: str) -> SealedToken:
    token = new_token(TOKEN_BYTES)
    return SealedToken(
        token=token, hash=token_hash(token), enc=seal(secret_key, token), hint=token[-4:]
    )


def seal(secret_key: str, token: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key(secret_key)).encrypt(nonce, token.encode("utf-8"), b"qr_point")


def unseal(secret_key: str, blob: bytes) -> str:
    return AESGCM(_key(secret_key)).decrypt(blob[:12], blob[12:], b"qr_point").decode("utf-8")


def survey_url(public_base_url: str, token: str) -> str:
    return f"{public_base_url.rstrip('/')}/s/{token}"
