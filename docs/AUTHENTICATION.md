# Authentication and connections

No hosted NorthLedger account, Codex subscription, or shared production account is
required. Each operator supplies their own connections. Never commit `.env`, the
`secrets/` directory, database exports, browser profiles or captured messages.

## Local workbench

Run `python3 scripts/setup.py` once from the project folder. It copies the
commented `.env.example` template into a private `.env` and creates two random
local passwords: `WORKBENCH_TOKEN` for the app and `VNC_PASSWORD` for the browser
viewer. Open `.env` in your text editor; copy the value to the right of `=` when
asked for that password. Neither value is a LinkedIn password or an API key.

You do not need to invent these passwords. The setup script does not call any
external service, create provider accounts or sign you in. If `.env` already
exists, it fills missing/blank/example local passwords and repairs app passwords shorter than 24 characters and preserves configured
values and API keys. The file is readable/writable only by your OS user.
Use `python3 scripts/setup.py --reset-token` to deliberately replace the app
password while preserving your browser password and API keys. Recreate the app
container afterward so it receives the new value.

The UI
accepts it into tab memory only; it is not placed in a URL, localStorage or cookie.
Every data/action API requires the token. The unauthenticated page contains only
the static UI; `/health` only reports process health.

This is a local single-operator tool. Do not expose it directly to the internet.
For a remote machine use SSH forwarding for both 8080 and 7900. Shared hosting
would require TLS, user accounts, per-user storage and additional authorization.

## LinkedIn

1. Set `WORKBENCH_MODE=live` in `.env`.
2. Run `docker compose --profile live up --build -d`.
3. Click **Start LinkedIn login** in the app.
4. Open http://localhost:7900 and enter `VNC_PASSWORD` from `.env`.
5. Sign in directly on LinkedIn and complete any 2FA or verification yourself.
6. Paste your own public LinkedIn profile URL into the app and verify it.

The app never requests your LinkedIn password or OTP. Chrome retains the session
in the private browser-profile Docker volume. That volume grants account access;
protect it like a password. The application checks the signed-in account before
sending or reading. It never switches to another account after a restriction.

Browser automation is an optional experimental adapter, not an official LinkedIn
API integration. Check the service's applicable terms and your authorization
before enabling it. No claim is made that automation avoids account restrictions.
The supported send path requires a visible top-card Connect button; unsupported
layouts stop for review. No InMail or recipient email guessing is implemented.

## Jev / TypeSafe (optional browser assistance)

The original private scripts use Jev for several tasks. This public release
currently supports only Connect-control selection, not the original discovery
crawler, employer qualification or reply intent classification. Apollo remains
the live discovery provider; you can also import your own leads.

1. Obtain your own API key at https://console.typesafe.ai/keys.
2. In your private `.env`, set `BROWSER_ADVISOR=jev` and
   `TYPESAFE_API_KEY=` followed by your key.
3. Keep `WORKBENCH_MODE=live` for real browser operations and run
   `docker compose --profile live up --build -d` to load your changes.

The app calls `jev-latest` at the TypeSafe System One endpoint only when multiple
eligible Connect controls remain in the verified recipient's top card. A single
clear control needs no model call. The request includes bounded button text and
accessibility labels, which can contain the recipient's name. It does not send
cookies, passwords, the invitation note, inbox messages or the CRM to Jev.
Provider usage may incur charges.

Jev returns a choice among observed controls; the browser rechecks those controls
before clicking. It cannot supply selectors/URLs or select Send. Unknown/invalid
responses, API failures and HTTP 429 stop the operation without retry. Changing
`BROWSER_ADVISOR` back to `none` disables Jev calls even if the key remains set.
Demo mode never calls Jev. A configured key is not proof that its account access
works; this adapter is fixture-tested, not validated with a paid live account.

## Apollo (lead finder)

Create your own API key with access to People API Search and People Enrichment.
Put `APOLLO_API_KEY=...` in `.env` and restart the app. Search uses comma-separated
job titles, optional locations and optional company domains. It does not interpret
arbitrary natural-language queries as filters.

Search results are partially redacted. To obtain names and LinkedIn URLs the app
uses People Enrichment, which may consume credits. Each live search requires
`allow_paid_enrichment=true`; the request limit bounds enrichment calls. Personal
email and phone reveal are disabled. Check your plan's pricing and permissions.
The app stops on 429 or denied access, without automatic HTTP retries.

Sources: [People API Search](https://docs.apollo.io/reference/people-api-search),
[retrieving LinkedIn profiles](https://docs.apollo.io/docs/retrieve-linkedin-profiles-for-prospects).

## Google Sheets (optional)

1. Create a Google Cloud project and enable the Google Sheets API.
2. Create a service account and download a JSON key into
   `secrets/google-service-account.json`. Keep the file private.
3. Create an empty spreadsheet and share it as Editor with the service-account
   email inside that JSON file. Do not upload the key into the spreadsheet.
4. Set `GOOGLE_SHEET_ID` to the ID from the spreadsheet URL and
   `GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google-service-account.json` in `.env`.
5. Restart the app and click **Sync spreadsheet**.

Compose mounts `secrets/` read-only. The application creates Workbench Leads,
Workbench Replies and Workbench Deliveries. It refuses to adopt same-named tabs
owned by another installation. A sync failure preserves local records; repeating
sync replaces the same cells by stable record ID rather than appending duplicates.

There is no shared OAuth client, consent-server deployment or account password
handling. Organizations that prohibit service-account keys will need an alternative
credential provider before enabling this optional connector. Demo and browser
workflows do not require Google.

## Revocation

Rotate the local token in `.env` and recreate the app container. Revoke Apollo keys
in Apollo; revoke Google keys and spreadsheet sharing in Google. Sign out of
LinkedIn through the browser. Removing a browser volume destroys its saved session;
removing the app data volume destroys the local CRM. Back up deliberately before
any destructive volume operation.
