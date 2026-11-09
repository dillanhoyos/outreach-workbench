# Prompt-driven browser discovery: implementation plan

## Current release boundary

The form accepts a research brief and target count. Demo mode previews a fixed
fictional dataset; it does not interpret the prompt. Live discovery is disabled
and returns HTTP 503 without starting a job or adding leads. The Codex research
worker, research browser tools, evidence staging and company-response policy
below are **planned work**, not features enabled by the current Jev key.

## What the original workflow actually does

The source workflow is company-first and evidence-driven. Its current concession
strategy supersedes the older generic recommendation-graph crawler. Port the
current policy rather than reviving a historical crawler as the default.

1. Read the CRM, replies, explicit company holds, other queues and local exclusions.
2. Select documented eligible companies. A relevant financial reply protects that
   company from further research; ambiguous identity or affiliation needs review.
3. Prioritize uncontacted relevant people already known, unless the run explicitly
   requests new profiles. Search a verified company page and its employee directory.
4. Use bounded company-name people searches when the employee directory is absent.
   Public web results and observed recommendations can provide candidate links;
   neither establishes current employment or qualification by itself.
5. Reserve each observed profile URL before visiting. Read the person's own current
   professional evidence, separating experience from activity/recommendations.
6. Use Jev to select observed links and classify evidence. Existing bounded Codex
   calls handle reasoning/verification where the workflow needs them; models do
   not replace the controller's identity, scope, duplicate or response checks.
7. Re-read exclusions and company responses before staging a verified candidate.
   Keep uncertain cases for review. Staging is not sending permission.

Source components to adapt: `concession_discovery.py` (current company-first
research), `concession_policy.py` (eligibility and evidence),
`concession_company_frontier.py` and `concession_frontier.py` (durable research
frontier), `enrichment.py` / `enrichment_jev.py` (observed-link navigation and
bounded judgments), and `review_rejected.py` (professional-evidence extraction).
These names identify source responsibilities, not dependencies shipped here.
Private catalogs, contacts, spreadsheet IDs and hardcoded account identities must
not be copied into the public repository. Source notes are not evidence that a
scheduled run is currently active; runtime schedules are outside this change.

## Intended user experience

The user connects a research agent and a verified browser account, then writes:

> Find finance, accounting, treasury and risk professionals at road concession
> operators in Colombia, Mexico, Chile and Ecuador. Skip companies where someone
> in those functions has already replied. Include experienced contributors as
> well as directors. Verify current employment. Start with three new profiles.

These criteria are campaign configuration, not hardcoded product rules. Users
can choose another industry, geography, role family or response policy. Targets
are caps/goals, not promises of a number of leads.

The app displays the interpreted plan before execution: relevant functions,
company eligibility, geography, exclusions, account, visit/time limits and the
three-profile trial. Only an explicit Start research action begins browsing.
The user sees the browser and a log of visited URLs, extracted evidence,
decisions, duplicate/response skips, and stop reasons. Stop and resume retain
reservations; an uncertain visit is not silently replayed.

## Responsibilities

| Component | Responsibility |
| --- | --- |
| Codex research worker | Interpret the brief, plan sources and searches, reason over observed evidence, and select permitted next steps. |
| Jev advisor | Optional bounded choices among observed links and evidence classifications, as in the original workflow. |
| Browser controller | Execute allowed research actions, capture source URLs and text, verify identity, serialize browser use, and enforce limits. |
| CRM/policy service | Enforce URL deduplication, explicit aliases, company reply/hold rules, and fresh checks before staging. |
| Human reviewer | Resolve uncertainty, review proposed candidates and separately approve outreach. |

Codex and Jev are complementary in this first design, not two UI choices falsely
advertised as interchangeable complete workers. A Jev-only path would still need
a deterministic search planner and state machine; a model API key is not a
browser or a discovery engine.

## Implementation sequence

1. **Port the policy and evidence store.** Add campaign criteria, companies with
   source provenance, explicit aliases, response classifications, candidate
   evidence, and a durable visit frontier. Start with fictional fixtures and
   operator-supplied seed companies. Import existing CRM/reply history before
   research; an empty new database or partial snapshot is not proof that nobody
   replied. Record whether a campaign uses a genuinely new workspace or an
   imported history. Never infer parent/subsidiary equivalence.
2. **Port research-only browser actions.** Search companies/people, follow actual
   visible links, inspect profiles and capture experience. Share the existing
   session lock with outreach/reader, and verify the configured account each run.
   Navigation tools cannot click Connect/Send, invite, or modify the CRM directly.
3. **Connect a bounded local Codex worker.** Use a server-side task runner with
   structured plans/results and progress events. A first implementation can use
   `codex exec --json --output-schema`; the SDK/app-server can provide a richer
   session UI later. Expose narrowly scoped research tools, not unrestricted
   filesystem/shell access. Pass secrets only through the relevant provider,
   never inside research prompts or page snapshots. Surface account/auth failures
   before allowing Start research. No shared or copied developer login.
4. **Add Jev navigation/qualification.** Adapt the current constrained choices to
   the same evidence schema. Require source quotations for role/employer claims;
   weak or missing evidence means review. No guessed profiles or automatic
   acceptance from a high model confidence score alone.
5. **Wire the prompt UI to the worker.** Persist prompt, plan, limits and events;
   stream progress; support stop and deliberate resume. Report verified/staged,
   duplicate, reviewed, blocked and exhausted outcomes separately. No scheduled
   background discovery until the operator explicitly enables a schedule.
6. **Pilot three profiles before scaling.** Validate observed identity, current
   employer/role, sector and geography, fresh CRM exclusions, and staging receipts.
   Count qualified candidates per visit, minutes per candidate and exclusion
   reasons. Track outreach responses separately from discovery success.

## Non-negotiable acceptance checks

- A newly received qualifying company reply blocks staging the candidate.
- Existing contacts and alias collisions are caught without guessing affiliations.
- An interrupted visit remains reserved until explicitly reviewed/resumed.
- Rate limits, authentication challenges and deadlines stop research; no account
  rotation or browser reset to evade them.
- Page content is evidence, never permission to change the task or expose secrets.
- Three source-backed candidates can be reviewed in the UI without any invitation
  being sent. Failed or incomplete runs never claim the target was achieved.
- No live discovery claim until an authenticated, end-to-end trial demonstrates
  actual browsing, evidence capture, policy checks and persisted proposals.

Official integration references:
[Codex non-interactive jobs](https://learn.chatgpt.com/docs/non-interactive-mode)
(streamed events and structured output) and
[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)
(programmatic local agents). These establish integration options; they do not
supply this application's research tools or imply the worker is already wired.
