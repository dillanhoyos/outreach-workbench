# Public release implementation checklist

Goal: separate public portable containerized project with lead discovery,
reviewed outreach, message reading, onboarding UI and agent API. No production
configuration, credentials, data or Git history.

Implemented:
- New repository, environment configuration, local secret generator.
- SQLite deduplication, approvals, holds, durable send reservation, reply records.
- Demo/live databases separated. Fictional data cannot enter live workflows.
- Authenticated API, sequential jobs, onboarding UI, CLI, Dockerfile and Compose.
- Apollo search/enrichment with explicit credit consent and no HTTP retries.
- Google service-account Sheets sync: owned tabs, RAW snapshots, verified readback.
- LinkedIn visible-browser adapter: manual login, account verification,
  recipient checks, single Send click, incoming sender matching, restriction stops.
- README and authentication guide. Fifteen tests passing (including API flow,
  rate limit behavior, identity gates and spreadsheet readback).
- App container built and healthy on localhost:18080 in demo mode.

Next release gates:
- Browser pull/start and real Selenium smoke on fixture pages; UI visual QA.
- More browser tests: no wrong-recipient click, uncertain post-send result,
  known incoming sender extraction, unknown participant skip, exact reader count.
- Ensure browser session survives/reconnects across app restart; lifecycle cleanup.
- Prevent multiple app processes from sharing the state/browser concurrently.
- Deadline/partial-result handling for reader and provider jobs.
- Review Sheets ownership and interrupted sync recovery; stale trailing rows policy.
- Polish error reporting; add import/export for user-provided leads.
- Pin tested dependencies; license, security/contribution docs, CI and secret audit.
- Clean-volume container end-to-end test of documented startup and agent commands.
- Create and push public dillanhoyos/outreach-workbench after release audit.

Current browser startup process: exec session 2811 (docker compose --profile live
up -d browser). Initial pull failed on full host disk; a completed prune of unused
build cache older than one week reclaimed 5.252 GB. No application volumes or
sessions were deleted. Poll existing session before launching another start.

Scope limits to document honestly: LinkedIn adapter is experimental and UI-dependent;
no assertion of current authenticated live acceptance without actual evidence.
Apollo/Sheets tests use protocol fixtures; own account credentials are required.
