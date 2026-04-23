# V1 Chunk 5 Google Workspace Validation

Command:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk5_google_workspace.py
```

Validated behavior:
- Gmail, Calendar, Contacts, and Drive actions resolve through an explicit user-owned Google connection.
- Action provenance records the Google connection id, owning user id, and Google account email used.
- A second Gmail connection for the same user causes Gmail access without `google_connection_id` to fail rather than silently choosing an account.
- Cross-user Gmail access is denied before tool invocation when no authority grant exists.
- A bounded explicit authority grant allows a cross-user Calendar action and cites the matched grant.
- A separate user's own Gmail action uses that user's Google connection, not another user's account.
- Authority, policy, tool invocation, and Google action records are audit-linked.

Expected validation shape:

```json
{
  "ok": true,
  "connections": {
    "count": 3
  },
  "ambiguity": {
    "gmail_without_connection_id_blocked": true
  },
  "blocked_cross_user": {
    "blocked": true
  }
}
```

Security note:

The validation uses opaque credential refs and simulated action completion. It is intentionally not an OAuth or live Google API test. The gate for this chunk is per-user connection resolution, authority enforcement, ambiguity blocking, and provenance.
