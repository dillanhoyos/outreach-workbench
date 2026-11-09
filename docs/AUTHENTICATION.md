# Authentication and connections

No hosted NorthLedger account, Codex subscription, or shared production account is
required. Each operator supplies their own connections. Never commit `.env`, the
`secrets/` directory, database exports, browser profiles or captured messages.

## Local workbench

`python3 scripts/setup.py` generates a random token in a mode-0600 `.env`. The UI
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
