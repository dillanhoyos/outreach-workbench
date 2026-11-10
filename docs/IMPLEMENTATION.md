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

Single local operator; no hosted multi-tenant access control. A host cron runner can schedule reply reads through the existing app.
LinkedIn layouts and language variations may require adapter updates. The reader
covers currently loaded incoming messages for matched CRM profiles only. Verified replies save incrementally, so a later reader failure preserves prior saves. Resolve the reported cause before rerunning. Reply deduplication makes successful repeated imports safe. A timed
reader run can return fewer conversations than requested.

Sheets is a one-way snapshot of installation-owned tabs. There is no lead deletion
workflow or import of edits from Sheets. Live provider account permissions and
paid API availability require verification with the operator's own accounts.


## Replies reader workflow and cron

In **CRM → Replies reader**, choose 1–100 recent **conversations**, then click
**Read replies now**. This is not a promise to read the latest 100 individual
messages: each matched thread contributes its currently visible incoming messages.
Opening a conversation may mark it read on LinkedIn. No response is composed or sent.

The reader uses the same signed-in private browser as research/outreach. It checks
thread identity, resolves the participant's canonical profile URL, and imports
only messages whose sender matches a saved CRM lead (research-only visited profiles are not inbox recipients). Unknown people are counted
as outside the CRM; group/ambiguous threads are skipped for review. It does not
create contacts from unrelated inbox conversations. Message IDs deduplicate
imports. Verified dates come from message identifiers; unknown dates are flagged.

Progress shows conversations checked, matched contacts, outside-CRM conversations,
new replies, duplicates and review cases. Replies are saved per verified thread.
They appear when clicking a contact's name, under its messages, and in History.
Use **Show profiles → Replied** to filter. A reply blocks further invitations to
that person; research also excludes companies with recorded replies. Stop finishes
the current bounded browser step and keeps already saved replies.

The scan has a 10-minute budget and can finish below the requested conversation
count. Sign-in challenges, restrictions and 429s stop it without automatic retries.
If every inspected conversation fails verification, the job fails visibly.

### Schedule on this UTC Linux host

After `docker compose up -d --build --wait app`, install once:

```sh
python3 scripts/install-reader-cron.py --preview
python3 scripts/install-reader-cron.py
```

Default: weekdays at **09:00 America/Bogota**, expressed as **14:00 UTC**. The
installer requires a UTC host, backs up the existing crontab privately, preserves
unrelated entries, and replaces only its own marked block on subsequent runs.
It schedules the replies reader only—never research, invitations or Google writes.

Test the exact scheduled command immediately:

```sh
/bin/bash scripts/run-replies.sh
```

The launcher locks against duplicate cron invocations, calls the already-running
app using credentials inside its container, and waits for the recorded job. The
app's job lock rejects a scan when another browser task owns the workspace; the
runner skips rather than queues/retries. It requires an available Docker service,
running app, and signed-in LinkedIn session; it does not restart services or sign
in automatically. A reader observation timeout never starts a replacement job.

Results: CRM reader panel and History. Private local logs:
`~/.local/state/outreach-workbench/reader/last.log` and `previous.log` (no message
bodies or tokens). To pause, create `~/.local/state/outreach-workbench/reader/PAUSED`;
remove that file to resume. To uninstall only this entry:

```sh
python3 scripts/install-reader-cron.py --remove
```

Older NorthLedger schedules are separate; this installer does not resume or alter
them. Do not point an independent legacy automation at this same browser session.
