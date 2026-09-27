"""AES (Fernet) encryption for per-user LLM API keys at rest.

Fernet = AES-128-CBC + HMAC-SHA256 authenticated encryption. Keys are
URL-safe base64-encoded 32-byte values generated server-side (never sent
to the browser). The encrypted blob (not the plaintext key) is what gets
stored in ``users.llm_api_key``.

Hard rules:
- Never log or return a decrypted API key from anywhere that imports this.
- ``decrypt_api_key`` on a value encrypted with a different
  ``LLM_ENCRYPTION_KEY`` raises ``InvalidToken`` — callers (the resolve
  factory) must treat that as "no personal key" and fall back to default.
"""

from cryptography.fernet import Fernet

from app.config import settings


def get_fernet() -> Fernet:
    """Build a Fernet cipher from the server-side encryption key."""
    return Fernet(settings.LLM_ENCRYPTION_KEY.encode())


def encrypt_api_key(plain: str) -> str:
    """Encrypt a plaintext API key for storage. Empty input stays empty."""
    if not plain:
        return ""
    return get_fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt a stored API key. Empty input stays empty.

    Raises:
        cryptography.fernet.InvalidToken: wrong LLM_ENCRYPTION_KEY or
        corrupted blob — callers fall back to the system default client.
    """
    if not encrypted:
        return ""
    return get_fernet().decrypt(encrypted.encode()).decode()
