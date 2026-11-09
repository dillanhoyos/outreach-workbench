# Prompt-driven discovery

## Run your first trial

1. Start the app in live mode. Browser setup can be completed after preparing a plan.
2. Connect Codex using ChatGPT sign-in or an OpenAI API key. Connect Jev optionally.
3. Use **Refine audience** to discuss roles, companies, geography and exclusions
   with the research agent. It asks focused questions and updates the editable
   **Working brief**. Conversation history stays on this installation. Start with 3 leads.
4. Click **Prepare research plan**. This uses your model quota to produce search
   queries and qualification criteria, but does not visit LinkedIn profiles yet.
5. Review the plan and confirm that your local CRM contains previous contacts and
   replies, or that this is a genuinely new campaign. Google sync is an export;
   connecting an old spreadsheet does **not** import its history automatically.
6. Before browsing, start the browser and sign in to LinkedIn. There is no separate
   account verification. Click **Start reviewed plan**. Watch
   the embedded browser and research event log.
7. Review proposed candidates and source evidence in the CRM. Research never
   approves or sends invitations.

Example brief:

> Find finance, accounting, treasury, financial reporting and risk professionals
> at road concession operators in Colombia, Mexico, Chile and Ecuador. Include
> experienced contributors and accounting directors, not only CFOs. Verify current
> employment and the concession business. Exclude companies that already replied.

## Implemented execution

Codex produces structured plans and evidence assessments through the official
app-server using this workspace's stored login. Shell, browser, external app and
web-search tools are disabled for model turns; only the controller navigates.
The controller searches LinkedIn people using the planned keywords, follows
observed profile links and selects current-employer company links observed on the
profile. A connected Jev key prioritizes an observed profile; it cannot invent
URLs or qualify a person by itself. No model can click Connect or Send.

Each run has at most 6 search queries, 1–10 proposed candidates, 30 profile visits
and a 15-minute deadline checked between actions. An in-flight browser read may
take up to its timeout after Stop. Model steps have a 120-second deadline and
are interrupted on cancellation. Rate limits and account challenges stop the run;
provider retries are disabled for research model calls. No account rotation.

The candidate needs exact source quotations for current role/employer (with an
explicit current-employment marker, or an exact role/employer headline labeled as
self-reported evidence), location and the employer's business sector. Former-role
headlines are excluded. LinkedIn h1 and h2 profile layouts are supported.
Quotations are checked against captured page text and the profile name against
its heading. Missing, past-only or conflicting evidence remains in the research
log, not as a sendable contact. Staged candidates always have `review` status.

Profile URLs are durably reserved before navigation. Existing CRM contacts,
previous visits and uncertain interrupted reservations are skipped on later runs.
There is no automatic retry or resume of an uncertain profile visit. Full bounded
snapshots and assessments remain in the private research evidence table.

Company holds and replies are checked again in the same transaction that stages
a candidate. This first version conservatively excludes any company with a local
recorded reply, not only replies classified as financial. Company names are
compared after case, accent and punctuation normalization; parents, subsidiaries
and aliases are not assumed equivalent. Import history and explicit company
holds before using an existing campaign. A blank database cannot establish that
no one replied.

The report includes visited, staged, skipped, elapsed seconds, candidates per
visit and the stop reason. Exhausted searches do not claim the target was reached.

## Scope and validation limits

This is the first bounded public worker, not full parity with the private
company-first engine. It uses people search followed by employer verification;
it does not yet carry a verified company seed catalog, alias review UI, external
web research, search pagination, existing-Sheets history import, or deliberate
reservation-release/resume UI. Search cards and recommendations alone never
qualify a candidate. Profile layout changes can stop a run or yield no candidates.

Tests cover the complete controller flow with fictional browser/model evidence,
fresh replies, known profiles, rate limits, interruptions, quotation checks and
no-send behavior. A separate optional protocol test exercises the pinned real
Codex binary against a local model fixture. Desktop/mobile UI tests exercise plan
and run controls. These tests do not establish real-world lead quality. Validate
three actual profiles using your own authenticated browser and Codex account
before scaling. The developer's host login is never copied into the app.

Official references: [Codex app-server](https://learn.chatgpt.com/docs/app-server),
[permissions](https://learn.chatgpt.com/docs/permissions) and
[configuration](https://learn.chatgpt.com/docs/config-file/config-reference).

For speed, profiles with no observed employer links skip model selection. An
unambiguous company link matching the headline skips employer selection, but
still requires full model qualification and source checks. Jev currently prioritizes
one observed profile per search; Selenium performs navigation. Activity text is
excluded from qualification. An activity link may supply an employer URL only when
its complete label occurs in the person’s own headline; it is not role evidence.

## Refine before searching

The conversation is planning only: it never navigates or saves leads. Each reply
updates the working brief; you can edit that brief directly before preparing a plan.
A new refinement invalidates the prior plan, including when the model fails, so an
old audience cannot accidentally run. Use **New brief** to clear the conversation
and plan without deleting CRM contacts. Conversations are limited to 20 exchanges.

## Watch research decisions

**Research decisions** shows the latest run's query, observed profile count,
Jev prioritization, profile navigation, employer selection, qualification, skips
and saves. Source links and saved role quotes let you inspect the evidence.
These are action summaries and explicit decision explanations, not private model
chain-of-thought. Jev currently returns an ordering choice, not a detailed rationale;
the log does not invent one. Older runs have fewer event types. Full activity is
available below the cards. No search is launched by sending a conversation message.
