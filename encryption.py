"""
AEGLOS Analytics Pro - Security / Encryption Module
AES-256-GCM with PBKDF2HMAC key derivation.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from config import settings


def derive_key(password: Union[str, bytes], salt: bytes) -> bytes:
    """Derive a 256-bit key using PBKDF2-HMAC-SHA256."""
    if isinstance(password, str):
        password = password.encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=settings.ENCRYPTION_ITERATIONS,
    )
    return kdf.derive(password)


def encrypt(plaintext: Union[str, bytes], password: str) -> dict[str, str]:
    """
    Encrypt plaintext using AES-256-GCM.
    Returns a dict with base64-encoded salt, nonce, and ciphertext.
    """
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()

    salt = os.urandom(16)
    nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    return {
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": settings.ENCRYPTION_ITERATIONS,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def decrypt(payload: dict[str, str], password: str) -> str:
    """
    Decrypt an AES-256-GCM payload produced by encrypt().
    Returns the plaintext string.
    """
    salt = base64.b64decode(payload["salt"])
    nonce = base64.b64decode(payload["nonce"])
    ciphertext = base64.b64decode(payload["ciphertext"])
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()


def generate_token(length: int = settings.TOKEN_LENGTH) -> str:
    """Generate a cryptographically secure random token (hex string)."""
    return secrets.token_hex(length)


def generate_api_key() -> str:
    """Generate a formatted API key: AAP-<random>."""
    raw = secrets.token_urlsafe(24)
    return f"AAP-{raw}"


def hash_data(data: Union[str, bytes]) -> str:
    """SHA-256 hash (hex digest)."""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def hmac_sign(data: Union[str, bytes], key: Union[str, bytes]) -> str:
    """HMAC-SHA256 signature (hex digest)."""
    if isinstance(data, str):
        data = data.encode()
    if isinstance(key, str):
        key = key.encode()
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def benchmark_encryption(iterations: int = 100) -> dict[str, Any]:
    """Benchmark encryption/decryption throughput."""
    sample = "AEGLOS Analytics Pro benchmark payload — TOP SECRET//SCI" * 10
    password = "benchmark-password"

    # Encrypt timing
    t0 = time.perf_counter()
    for _ in range(iterations):
        payload = encrypt(sample, password)
    enc_time = (time.perf_counter() - t0) / iterations * 1000  # ms per op

    # Decrypt timing
    t0 = time.perf_counter()
    for _ in range(iterations):
        decrypt(payload, password)
    dec_time = (time.perf_counter() - t0) / iterations * 1000

    return {
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-HMAC-SHA256",
        "kdf_iterations": settings.ENCRYPTION_ITERATIONS,
        "payload_bytes": len(sample.encode()),
        "iterations_tested": iterations,
        "avg_encrypt_ms": round(enc_time, 2),
        "avg_decrypt_ms": round(dec_time, 2),
        "operations_per_sec": round(1000 / enc_time, 1),
    }
