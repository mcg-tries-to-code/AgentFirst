# Validation, V1 Secret Broker Slice Phase 1

## Goal
Validate the bounded phase-1 secret broker slice without leaking plaintext secrets into validation output.

## Validation script
- `scripts/validate_v1_secret_broker_slice_phase_1.py`

## Commands run
```bash
python3 -m compileall src
python3 scripts/validate_v1_secret_broker_slice_phase_1.py
```

## Observed result
Both commands completed successfully.

Representative validation result:
```json
{
  "status": "ok",
  "checks": {
    "cli_ingest_masked": true,
    "vault_payload_encrypted": true,
    "telegram_brokered_retrieval_audited": true,
    "revoked_secret_denied": true
  },
  "telegram_transport_status": "send_failed",
  "macos_keychain": {
    "status": "passed"
  }
}
```

## What was exercised
### Canonical metadata and audit
- `secret_records` creation
- `secret_access_events` creation
- mirrored audit/event-log entries for secret operations

### Trusted local ingest
- CLI `secret put` via stdin
- CLI `secret list`
- CLI `secret rotate` via stdin
- CLI `secret revoke`
- validation explicitly checked that CLI stdout/stderr did not echo the test token

### Encrypted local vault
- secret payload written under dedicated `secure-secrets/`
- validation scanned vault files to confirm plaintext token bytes were not present
- validation scanned ordinary artifact files to confirm plaintext token bytes did not leak there

### Root key providers
- `OperatorPassphraseRootKeyProvider` fully exercised in store, rotate, retrieve, revoke flow
- `MacOSKeychainRootKeyProvider` exercised on Darwin with a temporary validation service name and roundtrip retrieval

### Telegram migration slice
- Telegram transport configured with `bot_token_secret_id` plus `secret_broker`
- outbound send path attempted live resolution against a loopback sink URL
- network delivery intentionally failed, but brokered secret retrieval occurred first and was audited

## Important interpretation
`telegram_transport_status = send_failed` is expected in this validation. The script deliberately points live transport at a local sink so it can prove brokered token retrieval without requiring a real external send.

## Residual limitations observed honestly
- payload encryption currently uses AES-256-CBC plus HMAC-SHA256 through OpenSSL rather than a fuller AEAD-native or KEK/DEK hierarchy
- Python cannot guarantee strong in-memory zeroization of plaintext once resolved
- broker access control is still minimal and trusted-local oriented
- only Telegram is migrated end to end in this slice; broader integrations remain follow-on work

## Conclusion
The bounded phase-1 slice is working:
- secrets now have canonical metadata without plaintext payload storage in ordinary tables
- payloads are kept in a separate encrypted local vault
- access is audited
- root-key custody is abstracted across macOS Keychain and operator passphrase modes
- Telegram now has a real brokered secret retrieval path
