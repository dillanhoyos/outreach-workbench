# Reviewed invitation workflow

In Local CRM, choose **Compose message** on a contact. The composer keeps one
recipient active and displays their company, role and campaign. Its recipient
selector can switch to another saved contact. Archived profiles without a
qualified contact record cannot be sent invitations.

1. Review source evidence. **View in live browser** opens the selected profile,
   checks its name, and makes the captured text available for drafting. Return
   to the composer with **Return to message draft**. This step sends nothing.
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
5. Read the result in the composer and CRM. A confirmed send requires the exact invitation POST HTTP 200 or a verified
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
stages and the no-retry policy.
