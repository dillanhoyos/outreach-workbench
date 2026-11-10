# Reviewed invitation workflow

Switch to **Outreach**, describe the message and select available CRM contacts.
Alternatively, open **CRM** in the header and choose **Compose message**. The inline composer stays beside the live browser and keeps one
recipient active and displays their company, role and campaign. Its recipient
selector can switch to another saved contact. Archived profiles without a
qualified contact record cannot be sent invitations.

1. Review source evidence. **View in live browser** opens the selected profile,
   checks its name, and makes the captured text available for drafting. The composer and browser remain visible together. This step sends nothing.
2. Describe the message: your purpose or offer, desired language, tone and ask.
   Codex returns up to three notes with supporting source quotations. Missing
   evidence or invalid output stops generation. Demo uses a labeled fictional
   template, not a model.
3. Choose a suggestion or write your own. Edit freely; the counter uses UTF-16
   units, matching JavaScript and the conservative 200-character invitation cap.
   **Save draft** preserves your text and instructions across reloads. Draft
   versions remain in `outreach_drafts`; they are never delivery receipts.
4. **Approve this note**, then select the explicit recipient confirmation and
   **Send invitation**. The API checks the exact approved text again while
   reserving the action. Editing/saving/regenerating requires fresh approval.
5. Sending reveals the live browser with the recipient, exact note and outcome above it. The detailed receipt remains in the inline composer. A confirmed send requires the exact invitation POST HTTP 200 or a verified
   Pending state; an existing Pending/connection is skipped, not called a new send.
   Blocked and uncertain results stop the batch and are never retried automatically.

The composer sends connection invitation notes. It does not send DMs to existing
connections or automate follow-ups. It uses the currently signed-in browser;
no account switching is performed. Preview, drafting and sending share the same
job lock as research. Existing company holds, replies, campaign qualification,
daily limits, recipient checks and durable duplicate-send protection still apply.

Implementation follows the other project's evidence-first drafting and sequential
recipient workflow, without copying its account identity, product positioning,
contact data, production configuration, or spreadsheet dependencies. Operator
instructions supply positioning; model output is a proposal requiring review.

API: `GET /api/leads/{id}/composer`, `POST .../preview`, `POST .../draft`,
`POST .../draft/save`, existing `POST .../approve`, and `POST /api/outreach` with
`expected_notes` keyed by recipient ID. Existing API clients remain compatible;
the composer always submits the exact-note check. Generation and preview run as
observable jobs; saving a draft and approval are local operations.

Tests cover generated evidence/length rejection, Unicode counts, draft persistence,
approval invalidation, exact-note mismatches, confirmed demo receipts and blocked
repeated sends. Browser UI testing uses an isolated demo workspace, never real
recipient sends. Live model generation can be checked independently without approval.

See [Invitation receipts](INVITATION_RECEIPTS.md) for request correlation, failure
stages and the explicit retry policy.

## Workspace history and CRM availability

Research records a visit when inspection begins and commits each assessment as it
finishes. The UI polls every second, including while a run is active; saves are
shown only after the database transaction commits. A persistent change journal
records contact creation, before/after qualification and outreach states,
invitation phases and terminal receipts. History combines this with research
activity and job outcomes. Existing reply records continue to prevent outreach,
but reply reading and inbox controls are not part of the interface.

Available recipients must be qualified and have no previous attempt, reply,
company hold or exclusion. These checks come from the server and are enforced
again when reserving a send. A visible account in the LinkedIn browser is the
active account; the app does not claim a cached identity is current.

Saved drafts and job records survive restarts. Mode switching retains the same
iframe and form nodes; local research inputs and the last selected recipient are
restored after a tab refresh and workspace unlock. Workspace credentials are
never placed in browser storage.

## Selecting and sending a batch

The Outreach list contains only contacts the CRM currently considers available.
Search by person, company or role. **Select all shown** selects the filtered list,
up to 100 recipients; clearing the filter preserves selections. The count shows
the actual batch size.

**Generate messages** creates a separate evidence-based draft for each selected
contact. Review and edit each note, then check the explicit confirmation and send
the batch. Editing a note or changing selection clears that confirmation. Notes
and selections survive a tab refresh; they never trigger sending automatically.

Sending checks every approved note before the first action, then processes
recipients sequentially in the visible browser. Limits, exclusions, blocked
actions, rate restrictions and uncertain receipts stop the batch. Completed
receipts remain visible; remaining contacts are not reported as sent. A stored
job ID lets the UI resume observing an active batch after refresh without
submitting another send.
