# Grok Orbit portable VM test (no desktop GUI)

Cloud computer / Grok Bot VM cannot drive the Windows Tauri window.
It can run this protocol test if Python 3 exists.

```
python3 scripts/portable_acp_mock_test.py
```

Expect: `OK portable mock permission allow-once` and exit 0.

Do not copy `auth.json`. Do not change operator permission_mode.
Do not tweet. Do not open PRs.

If python3 is missing, report SKIP and stop.
