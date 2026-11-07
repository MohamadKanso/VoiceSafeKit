# Security Policy

VoiceSafeKit is a first-layer privacy filter for voice assistant transcripts. It is
pattern-based and can miss things; do not use it as your only privacy control.

## Reversible placeholders

`PrivacySession` keeps the placeholder-to-value map in process memory only. It never
writes it to disk or sends it anywhere. Credentials (passwords, PINs, CVVs, one-time
codes, API keys) are never stored in the map, so they cannot be restored into model
output or spoken back by a TTS voice. Call `session.clear()` when a conversation ends.

## Saved export encryption

VoiceSafeKit filters transcripts in memory because the detectors need readable
text to find PII and safety risks. When a result is saved as a file, the browser
export and CLI `--out` path can store that JSON as AES-256-GCM encrypted data.

- Browser exports use the Web Crypto API and require a local export key.
- CLI `--out` uses `VOICESAFEKIT_EXPORT_KEY` by default and needs `pip install "voicesafekit[crypto]"`.
- CLI `decrypt` restores an encrypted export only when the same passphrase is available.
- `--plain-out` is available only as an explicit local debugging escape hatch.
- TLS/HTTPS should still be used for network transport. TLS is not local file
  encryption.

Please do not put real secrets, private customer data, medical records, or live
passwords into public issues.

If you find a security issue, open a private GitHub security advisory.
