# Public release implementation checklist

Goal: a separate public, portable, containerized project with lead discovery,
reviewed outreach, message reading, onboarding UI and agent-facing API. No copied
production data, sessions, identifiers, machine configuration or Git history.

Implemented so far:
- Independent repository and Python package.
- Environment-based configuration and local secret generator.
- SQLite lead deduplication, approvals, company holds, reply deduplication.
- Durable send reservation; interrupted sends become uncertain and cannot replay.
- Fictional provider and five passing behavioral / end-to-end API tests.
- Authenticated API, sequential jobs, browser UI, CLI, Dockerfile and Compose.
- Container build launched; verification still pending.

Remaining release gates (not a completed release):
- Complete connection onboarding and polish existing protected API/dashboard.
- Browser container, manual LinkedIn login, verified account identity.
- Live discovery adapter, reviewed invitation adapter, incoming reply reader.
- Optional Google Sheets connector with explicit credentials and destination.
- Extend existing agent CLI with connection and sync commands.
- Container build, clean-volume end-to-end smoke, API and browser fixture tests.
- README, auth guide, license, security/contribution docs, CI and secret audit.
- Create and push public dillanhoyos/outreach-workbench after release audit.

Authentication design: random local app token; LinkedIn sign-in performed by the
operator inside an isolated browser (never collect LinkedIn passwords in the app);
optional provider API keys supplied locally; optional Google service account file
mounted read-only and a user-selected spreadsheet shared with that account.
Secrets and sessions stay outside source control. Live actions require explicit
review and do not run on a schedule by default.
