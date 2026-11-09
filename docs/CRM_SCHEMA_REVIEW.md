# CRM schema review and proposed next model

This is a proposal, not an applied database migration. Reviewed against
`store.py`, `research.py`, and the combined `/api/records/leads` view.

## What exists

- `leads`: UUID, unique normalized LinkedIn profile key, name, company, role,
  profile URL, country, evidence JSON stored as text, status, invitation note,
  and creation timestamp. This is the actionable contact table.
- `crm_research_profiles`: one JSON record per profile, including visited state,
  latest audience, assessment, evidence, run, timestamps, and a summary history.
  This preserves rejected and incomplete profiles when search logs are cleared.
- `research_visits`: deduplication/reservation state and evidence per profile.
- `research_events`: timestamped run decisions and source activity.
- `deliveries`: one reserved/attempted invitation per lead, status and receipt.
- `replies`: message ID, contact, body, received/imported timestamps, thread.
- `holds`: company-name-based exclusions and reasons.
- `jobs` and `settings`: execution and configuration, including the current plan.

The UI merges leads and archived research profiles. A person therefore appears in
one list, but the underlying data has two shapes. Qualification, approval,
invitation delivery and replies currently share the `status` field. Company
identity is a display name, which makes spelling variants difficult to reconcile.
Qualification history retains summaries, not independently addressable assessments
with their own complete evidence snapshots. Prior-visit dedupe is global, although
fit is relative to an audience.

## Recommended entities

| Entity | Essential fields | Purpose |
| --- | --- | --- |
| People | ID, canonical LinkedIn key/URL, name, nullable country/location, first_seen_at, updated_at, last_verified_at | One person record, whether qualified, rejected or incomplete. Unknown facts remain null. |
| Companies | ID, canonical domain, name, aliases, LinkedIn/company URLs, sector tags, country, accelerator/batch when relevant | Stable identity for dedupe, company exclusions and shared evidence. |
| Employment | person_id, company_id, role title, function, seniority, current/former/unknown, observed_at, evidence_id | Preserve role changes and separate current employment from older experience. |
| Campaigns | ID, name, original brief, structured criteria, criteria version, target, exclusions, created_at | Make audience definitions explicit and reproducible. |
| Assessments | person_id, campaign_id, criteria_version, run_id, qualification, reason_code, explanation, checked_at, review_due_at | Keep qualified / not_applicable / missing_evidence / excluded separate from outreach. |
| Evidence | ID, source URL/type, captured_at, quoted fact, fact type, content hash, linked person/company/assessment | Explain exact batch, product and role claims with dated sources. Preserve bounded snapshots separately. |
| Outreach actions | ID, person_id, campaign_id, sender_account_id, channel, action type, approval, delivery status, scheduled/attempted/sent timestamps, idempotency key, receipt | Separate reviewed/approved from attempted/sent/uncertain, and identify the sending account. |
| Conversations/messages | conversation ID, person_id, sender_account_id, channel, external thread/message IDs, direction, body, sent/received/imported_at | Deduplicate messages, connect replies to outreach and measure response rates. |
| Exclusions | person_id or company_id, scope, reason, created_at, optional expiry | Persist explicit do-not-contact, holds and company reply exclusions independently of campaign fit. |
| Research runs/visits | run ID, campaign/version, requested target, time and visit caps, start/end, stop reason, worker/query activity, counters; visit source/outcome/timestamps | Explain what was attempted, why a run ended, and what may safely be rechecked. |

Use foreign keys for relationships, unique canonical profile keys and provider
message IDs, and explicit enums/check constraints for states. Company domain
merges need review: subsidiaries may share a domain. Model-derived role/function
tags should retain evidence and an unknown state; avoid unsupported precision.

## What should be visible in the CRM

Default columns: person, company, current role, campaign, qualification, short
reason, outreach status, last verified, last contact, last reply, and next action.
The detail panel should show the source quotations, campaign criteria, research
history, messages and operator notes. Tags supplement these fields rather than
replacing qualification or delivery status.

A person rejected for campaign A may qualify for campaign B. Reuse their fresh
profile/company evidence and assess the new criteria before deciding whether a
new LinkedIn visit is necessary. A cleared search log must not clear contact,
assessment, outreach, or exclusion history.

## Suggested implementation order

1. Introduce canonical people/companies and campaign assessments. Backfill both
   current CRM shapes, retaining IDs, timestamps, evidence and dedupe protections.
   Records with an unknown historical campaign remain explicitly unassigned.
2. Split qualification, human approval and outreach state; keep compatibility views
   for the existing UI and exports during migration. Never turn a historical
   approval or incomplete visit into permission for a new send.
3. Add durable evidence and employment history, then conversation/action records
   keyed to sender accounts. Preserve existing delivery idempotency and receipts.
4. Add campaign-level reporting: unique researched people, qualified people,
   attempted/sent invitations, accepted connections when actually observed, replies,
   and positive replies if explicitly classified. Show denominators and date windows;
   a missing response is not an inferred rejection.

Migration needs a backup and repeatable backfill tests. No new external CRM,
Google Sheets connection or authentication dependency is needed: SQLite can hold
this model locally.
