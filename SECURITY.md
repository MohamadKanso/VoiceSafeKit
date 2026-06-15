# Security Policy

VoiceSafeKit is a demo safety layer for voice assistant transcripts.

## Saved export encryption

VoiceSafeKit filters transcripts in memory because the detectors need readable
text to find PII and safety risks. When a result is saved as a file, the browser
export and CLI `--out` path can store that JSON as AES-256-GCM encrypted data.

- Browser exports use the Web Crypto API and require a local export key.
- CLI `--out` uses `VOICESAFEKIT_EXPORT_KEY` by default.
- CLI `decrypt` restores an encrypted export only when the same passphrase is available.
- `--plain-out` is available only as an explicit local debugging escape hatch.
- TLS/HTTPS should still be used for network transport. TLS is not local file
  encryption.

Please do not put real secrets, private customer data, medical records, or live
passwords into public issues.

If you find a security issue, open a private GitHub security advisory.
