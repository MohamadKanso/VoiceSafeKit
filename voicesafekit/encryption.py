from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

FORMAT = "voicesafekit.encrypted_export"
VERSION = 1
ALGORITHM = "AES-256-GCM"
KDF = "PBKDF2-HMAC-SHA256"
ITERATIONS = 600_000
SALT_BYTES = 16
NONCE_BYTES = 12
MIN_PASSPHRASE_LENGTH = 12
ASSOCIATED_DATA = b"VoiceSafeKit encrypted export v1"


def encrypt_json_payload(
    payload: dict[str, Any],
    passphrase: str,
    *,
    iterations: int = ITERATIONS,
) -> dict[str, object]:
    """Encrypt a JSON-compatible payload for storage at rest."""
    if not passphrase:
        raise ValueError("A passphrase is required to encrypt a VoiceSafeKit export.")
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise ValueError("Use an export passphrase with at least 12 characters.")

    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    key = _derive_key(passphrase, salt, iterations)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, data, ASSOCIATED_DATA)

    return {
        "format": FORMAT,
        "version": VERSION,
        "algorithm": ALGORITHM,
        "kdf": KDF,
        "iterations": iterations,
        "salt": _b64encode(salt),
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
    }


def decrypt_json_payload(bundle: dict[str, Any], passphrase: str) -> dict[str, Any]:
    """Decrypt a VoiceSafeKit encrypted export."""
    if bundle.get("format") != FORMAT:
        raise ValueError("Unsupported encrypted export format.")
    if bundle.get("version") != VERSION:
        raise ValueError("Unsupported encrypted export version.")
    if bundle.get("algorithm") != ALGORITHM:
        raise ValueError("Unsupported encrypted export algorithm.")
    if bundle.get("kdf") != KDF:
        raise ValueError("Unsupported encrypted export key derivation.")

    iterations = int(bundle["iterations"])
    salt = _b64decode(str(bundle["salt"]))
    nonce = _b64decode(str(bundle["nonce"]))
    ciphertext = _b64decode(str(bundle["ciphertext"]))
    key = _derive_key(passphrase, salt, iterations)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, ASSOCIATED_DATA)
    return json.loads(plaintext.decode("utf-8"))


def _derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))
