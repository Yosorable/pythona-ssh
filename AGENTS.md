# Agent guide

Read README.md for architecture, runtime limits and validation commands.

- Keep `main.py` as the root entry point. Import UIKit/Rubicon only on the iOS path.
- Frontend source lives in `frontend/src`; rebuild and include `frontend/dist/index.html`
  whenever the source changes. The installed project must run without Node.js or a CDN.
- Use `pythona.packages` for missing Python dependencies. Require an explicit UI
  confirmation before installation; never copy dependency source into this project.
- Keep network operations off UIKit's main thread. UI calls go through `run_on_ui`.
- Preserve stream byte order, acknowledgment-based output limits and independent input.
- Reject changed host keys. First-use trust must be confirmed before authentication.
- Persist credentials only after successful authentication when saving is selected.
  Use Fernet with the fixed application key in `ssh_app/credentials.py`; never store
  plaintext secrets or expose saved secrets in frontend snapshots. Clear credentials
  when the endpoint, username or authentication method changes. No legacy migration.
- Keep the host list and terminal as separate pages. Preserve the live terminal when
  returning to the list. On iOS, use the native navigation bar and one compact key bar.
- Explicitly close sockets, channels, workers, notifications and WebKit handlers.
- Preview remains simulated and loopback-only, with no real SSH or filesystem API.
- Keep product strings in `frontend/src/i18n.ts`, with English as the fallback.
- Keep UI copy functional: show host details, connection state and actions.
  Do not add marketing taglines or decorative welcome illustrations.
- Run the relevant Python and built-frontend integration tests after behavior changes.
  Native smoke tests use their own temporary host store and never saved connections.
