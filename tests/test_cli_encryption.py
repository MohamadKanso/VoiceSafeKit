import json

from voicesafekit.cli import main
from voicesafekit.encryption import decrypt_json_payload


def test_cli_out_is_encrypted_by_default(tmp_path, monkeypatch) -> None:
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("My email is alex@example.com.", encoding="utf-8")
    output = tmp_path / "result.enc.json"
    monkeypatch.setenv("VOICESAFEKIT_EXPORT_KEY", "correct horse battery staple")

    exit_code = main(["check", str(transcript), "--out", str(output)])

    stored = output.read_text(encoding="utf-8")
    encrypted = json.loads(stored)
    decrypted = decrypt_json_payload(encrypted, "correct horse battery staple")
    assert exit_code == 0
    assert encrypted["format"] == "voicesafekit.encrypted_export"
    assert "alex@example.com" not in stored
    assert decrypted["redaction_map"][0]["found"] == "alex@example.com"


def test_cli_plain_out_requires_explicit_flag(tmp_path) -> None:
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("My email is alex@example.com.", encoding="utf-8")
    output = tmp_path / "result.json"

    exit_code = main(["check", str(transcript), "--out", str(output), "--plain-out"])

    stored = output.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "alex@example.com" in stored
    assert json.loads(stored)["redaction_map"][0]["found"] == "alex@example.com"


def test_cli_decrypt_restores_encrypted_export(tmp_path, monkeypatch) -> None:
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("My email is alex@example.com.", encoding="utf-8")
    encrypted_output = tmp_path / "result.enc.json"
    decrypted_output = tmp_path / "result.json"
    monkeypatch.setenv("VOICESAFEKIT_EXPORT_KEY", "correct horse battery staple")

    main(["check", str(transcript), "--out", str(encrypted_output)])
    exit_code = main(["decrypt", str(encrypted_output), "--out", str(decrypted_output)])

    decrypted = json.loads(decrypted_output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert decrypted["redaction_map"][0]["found"] == "alex@example.com"
