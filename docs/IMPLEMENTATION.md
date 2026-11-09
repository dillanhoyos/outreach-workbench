# Architecture and release evidence

The API and UI share one sequential job runner. Provider adapters handle
visible-browser outreach and reading, and optional spreadsheet export. Live
discovery uses a bounded Codex/browser worker; see DISCOVERY.md for its scope and validation limits. SQLite is
the source of truth; demo and live workspaces are isolated. Approvals and send
reservations are durable, and ambiguous sends are never automatically retried.

Verified locally for the initial experimental release:
- 17 unit and API tests with fictional records and provider fixtures.
- Fresh app and browser containers, including fresh persistent volumes.
- Demo discovery, approval, simulated outreach and deduplicated reply import.
- Real Chromium fixture: session reattachment, wrong-recipient rejection,
  approved-note preservation and a single confirmed simulated Send click.

See TESTING.md for reproducible commands and the live verification boundary.
No production contacts, credentials, browser sessions or source Git history are
included. Each installation supplies its own accounts and local configuration.

## Optional Jev configuration

`BROWSER_ADVISOR=jev` and `TYPESAFE_API_KEY` enable a bounded Connect-control
advisor. Browser scope checks and final Send validation remain deterministic.
Setup preserves existing API keys while generating missing local app/viewer
passwords. Tests cover request minimization, invalid choices, changed pages,
rate-limit stops and preservation of existing settings. Paid live Jev access has
not been tested. The original Jev discovery crawler is not included.

## Current limitations

Single local operator; no hosted multi-tenant access control or scheduler.
LinkedIn layouts and language variations may require adapter updates. The reader
covers currently loaded incoming messages for matched CRM profiles only. A fatal
reader error before the batch returns discards that batch; rerun after resolving
the cause. Reply deduplication makes successful repeated imports safe. A timed
reader run can return fewer conversations than requested.

Sheets is a one-way snapshot of installation-owned tabs. There is no lead deletion
workflow or import of edits from Sheets. Live provider account permissions and
paid API availability require verification with the operator's own accounts.
