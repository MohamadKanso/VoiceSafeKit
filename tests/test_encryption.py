import json

from voicesafekit.encryption import decrypt_json_payload, encrypt_json_payload


def test_encrypted_export_round_trips_and_hides_sensitive_values() -> None:
    payload = {
        "decision": "BLOCK",
        "safe_transcript": "My SSN is [SSN removed].",
        "redaction_map": [{"found": "471-55-8843", "replaced_with": "[SSN removed]"}],
    }

    encrypted = encrypt_json_payload(payload, "correct horse battery staple")

    serialized = json.dumps(encrypted)
    assert encrypted["algorithm"] == "AES-256-GCM"
    assert encrypted["kdf"] == "PBKDF2-HMAC-SHA256"
    assert "471-55-8843" not in serialized
    assert decrypt_json_payload(encrypted, "correct horse battery staple") == payload
