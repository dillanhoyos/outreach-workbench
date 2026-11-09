# Prompt-driven discovery

## Run your first trial

1. Start the app in live mode. Browser setup can be completed after preparing a plan.
2. Connect Codex using ChatGPT sign-in or an OpenAI API key. Connect Jev optionally.
3. Use **Refine audience** to discuss roles, companies, geography and exclusions
   with the research agent. It asks focused questions and updates the editable
   **Working brief**. Conversation history stays on this installation. Start with 3 leads.
4. Optionally select **Search the web first, then confirm on LinkedIn** in the working brief. Click **Prepare research plan**. This uses your model quota to produce search
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
action tools are disabled for model turns; only the controller navigates LinkedIn.
Hosted web search is enabled only for the optional web-first shortlist step.
The controller searches LinkedIn people using the planned keywords, follows
observed profile links and selects current-employer company links observed on the
profile. A connected Jev key prioritizes an observed profile; it cannot invent
URLs or qualify a person by itself. No model can click Connect or Send.

Each plan starts with at most 6 search queries. General runs can expand to 18
LinkedIn queries and two web passes, with 1–10 proposed candidates, 30 profile visits
and a 15-minute deadline checked between actions. An in-flight browser read may
take up to its timeout after Stop. Model steps have a 120-second deadline and
are interrupted on cancellation. The web shortlist has a 240-second limit. Rate limits and account challenges stop the run;
provider retries are disabled for research model calls. No account rotation.

The candidate needs exact source quotations for current role/employer (with an
explicit current-employment marker, or an exact role/employer headline labeled as
self-reported evidence), location when required, and the employer's business sector. Former-role
headlines are excluded. LinkedIn h1 and h2 profile layouts are supported.
Quotations are checked against captured page text and the profile name against
its heading. Missing, past-only or conflicting evidence remains in the research
log, not as a sendable contact. Staged candidates always have `review` status.

Profile URLs are durably reserved before navigation. Existing CRM contacts,
previous visits and uncertain interrupted reservations are skipped by default.
Explicit rechecks can revisit completed evidence failures, as described below.
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
it does not yet carry a verified company seed catalog, alias review UI,
search pagination, existing-Sheets history import, or deliberate
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


## Optional web-first discovery

Select the checkbox before preparing a new plan. Existing plans keep their original
mode. Codex uses hosted live web search to shortlist companies and founders; the
controller independently downloads the cited primary HTML pages. It checks exact
company-evidence quotations and requires the person's LinkedIn link to occur in
the captured source. Wrong batches, unavailable pages, and unsupported quotations
are excluded before spending a LinkedIn profile visit. Source captures and company
assessments are cached within the run. Current role and identity are then confirmed
in the visible LinkedIn browser, and source provenance is saved with the CRM lead.

For example:

> Find current founders of YC S24 companies building AI agents, sandboxes, agent
> memory infrastructure, or agent monitoring/observability. Worldwide. Require
> exact Summer 2024 batch evidence from YC and current founder roles on LinkedIn.

Here, “agent memory and monitoring” are included product categories, not permission
to relax the S24 requirement. Research conversations, reservations and evidence
already persist in the local data volume. No private model chain-of-thought is stored.

Web searches and source checks appear in Research decisions; hosted searches do
not animate the Selenium browser. The browser shows LinkedIn confirmations. Jev
continues to prioritize LinkedIn search links in the original discovery mode; it
is not the hosted web search provider. Both modes save only review candidates.

This initial web-first mode requires a primary page that establishes the company
criteria and links to the founder's profile (YC directory pages commonly do).
It also reads YC’s public structured company payload. It does not yet combine
multiple primary sources or render other JavaScript-only public sites. Public-source downloads are bounded, HTTPS-only, validate every redirect,
and pin a public IP while retaining TLS verification. No browser cookies or user
credentials are sent. A web source 429 stops the run without retry.

Rebuild the app when upgrading: the pinned Codex installation includes its
code-mode companion executable, required by hosted search. Missing or unavailable
search now stops explicitly, rather than silently producing an empty shortlist.


## Missing evidence and rechecks

LinkedIn-first discovery now attempts a primary-source web lookup when required
company facts are missing, or no employer URL was observed. It does not use a
lookup to override an explicitly wrong batch or a former role. At most two profile
fallbacks run per research job, within the same overall deadline. A matching
primary source must link to that exact LinkedIn profile; fresh qualification still
checks current role against the person's own LinkedIn evidence. Rate limits stop
the run. The activity log records each fallback and the report counts them.

To revisit earlier skips, open **Working brief & candidate target** and select
**Recheck profiles previously skipped for missing evidence**, then prepare a new
plan. This processes the most recent completed evidence failures up to the visit
budget. Optionally paste one URL into **Specific LinkedIn profile** to inspect only
that person. The specific profile takes precedence over the general search mode.
Rechecks preserve the previous assessment in the private event history. They never
revisit a saved CRM contact, a company exclusion, or an interrupted reservation,
and a profile can be reserved only once per run. Older `insufficient_evidence`
records may include true mismatches; fresh qualification must still reject those.

## Continue toward the target

General audience runs filter CRM contacts and ineligible previous visits before
Jev ranking. Finishing the initial query list no longer ends discovery: Codex can
produce two additional rounds of distinct keyword queries using recent rejection
and duplicate feedback, while preserving the audience requirements. If the target
is still unmet, up to two web discovery passes look for new companies and exclude
already visited profile URLs. Web-first runs use those web passes directly.
A recheck queue continues into fresh discovery when it falls short; a deliberately
specified single profile never expands to unrelated people.

The target counts newly saved review candidates, not search hits or visits.
Previously seen results do not consume profile visits. Stop, provider restrictions,
the profile-visit cap and the 15-minute deadline still apply. Exhausting these
additional searches reports `discovery_budget_exhausted`, never success. Repeated
queries are not executed. These bounds prevent an endless loop when the requested
audience is too narrow or evidence is unavailable.

## CRM visit memory and clearing search logs

Every profile the worker opens is now retained in the local CRM, even if it does
not qualify. Rows show a visit tag, date, audience brief and decision. Qualified
candidates retain their review workflow; other rows are labeled **Not qualified
for this audience**, **Missing evidence**, **Company excluded**, or **Visit
interrupted**. These rows cannot be approved or sent. Prior assessments remain in
the profile's research details when an explicit recheck changes its classification.
Existing stored visits are brought into the CRM on upgrade. A visit that failed
before capturing the profile is shown as an attempted visit, not verified identity.
Search-result links that were never opened are not claimed as visited.

**Clear search history** is beside Stop research. Its confirmation clears discovery
run logs, the latest report and transient visit records, but preserves CRM profiles
and their visit memory, contacts, replies, outreach records, company holds, account
restrictions, saved connections, the conversation and current plan. It is blocked
while any job runs. It never deletes the data volume or signs you out.

Clearing logs therefore does not cause duplicate research. To reconsider a profile,
select **Recheck profiles previously skipped for missing evidence** and optionally
supply its URL. Saved CRM contacts remain excluded. An explicit recheck can promote
an unqualified profile to a single qualified CRM entry; it does not create another
copy. Interrupted visits and company exclusions remain protected. The research
target counts qualified review candidates, not every retained CRM visit.

## Filter CRM profiles

Use **Show profiles** above the CRM table to switch between **All profiles**,
**Qualified**, **Visited · not applicable**, **Missing evidence**, and
**Other / interrupted**. Each option shows its count; the table reports how many
profiles are displayed out of the full CRM. Qualified includes contacts already
in the review/outreach workflow. Company exclusions and interrupted visits appear
under Other. Filtering never changes qualification or enables outreach.
The chosen filter survives refreshes, navigation and reloads in the same browser
tab. Switch to All profiles to see the complete CRM again.
