"""
AES-256-GCM authenticated encryption for sensitive values stored at rest.

Usage
-----
    from api.encryption import encrypt, decrypt, generate_key

    # One-time key generation (run once, store output in APP_ENCRYPTION_KEY):
    print(generate_key())

    # Encrypt a third-party API credential before writing to the database:
    ciphertext = encrypt(raw_api_key)

    # Decrypt when needed:
    raw_api_key = decrypt(ciphertext)

Key management
--------------
Set ``APP_ENCRYPTION_KEY`` in your environment to a base64url-encoded 32-byte
key (produced by ``generate_key()``).  If the env var is absent, the module
falls back to deriving a key from ``APP_SECRET_KEY`` via SHA-256 — this is
deterministic (same key on every restart) but NOT suitable for production
because APP_SECRET_KEY is not a KDF-hardened secret.

For production, consider using a dedicated KMS (AWS KMS, Azure Key Vault,
HashiCorp Vault) to store the encryption key.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12   # 96-bit nonce — standard for AES-GCM
_KEY_ENV     = "APP_ENCRYPTION_KEY"


def generate_key() -> str:
    """
    Generate a new AES-256 key.

    Print the output and set it as ``APP_ENCRYPTION_KEY`` in your .env file.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def _load_key() -> bytes:
    raw = os.getenv(_KEY_ENV, "")
    if raw:
        try:
            decoded = base64.urlsafe_b64decode(raw + "==")
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass

    # Dev fallback: deterministic but NOT production-safe.
    secret = os.getenv("APP_SECRET_KEY", "dev-only-insecure-placeholder-32byte!")
    return hashlib.sha256(secret.encode()).digest()


def encrypt(plaintext: str) -> str:
    """
    Encrypt *plaintext* with AES-256-GCM.

    Returns a URL-safe base64 string encoding: ``nonce (12 B) || ciphertext+tag``.
    The 16-byte GCM authentication tag is appended automatically by the library.
    """
    key   = _load_key()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct    = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).rstrip(b"=").decode("ascii")


def decrypt(token: str) -> str:
    """
    Decrypt a value produced by :func:`encrypt`.

    Raises :exc:`ValueError` if the token is invalid, truncated, or tampered.
    """
    key = _load_key()
    try:
        padding = "=" * (-len(token) % 4)
        raw    = base64.urlsafe_b64decode(f"{token}{padding}")
        nonce  = raw[:_NONCE_BYTES]
        ct     = raw[_NONCE_BYTES:]
        return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
    except Exception as exc:
        raise ValueError("Decryption failed — ciphertext is invalid or tampered") from exc
