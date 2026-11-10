# Connect Google and import a spreadsheet

Once configured: **Connections → Google Sheets → Connect Google → paste URL →
Open spreadsheet → select tab → Load columns → Preview import → Import into CRM**.
If the file has not been authorized for this app, click **Choose in Google Drive**.
The picker opens the pasted file; select it to grant access. You can also use the
picker without a URL. Sign in with the same Google account in both places.

## One-time setup for the person running this installation

Google sign-in in ChatGPT does not connect this separate app. Each self-hosted
installation needs its own Google Cloud project. No service account is needed.

Use the browser address where you open Workbench. This example uses
`http://localhost:8080`; replace it everywhere if you use another forwarded port.
`localhost` and `127.0.0.1` are different origins.

1. Open [Google Cloud Console](https://console.cloud.google.com/). Create/select
   one project. Enable **Google Sheets API**, **Google Drive API**, and **Google
   Picker API** in APIs & Services → Library.
2. In **Google Auth Platform**, configure Branding and Audience. For a personal
   installation choose External, Testing, and add your Google email as a test user.
   In Data Access add `https://www.googleapis.com/auth/drive.file`.
3. Create an OAuth client with type **Web application**. Enter:

   | Setting | Example value |
   | --- | --- |
   | Authorized JavaScript origins | `http://localhost:8080` |
   | Authorized redirect URIs | `http://localhost:8080/api/connections/google/callback` |

4. Download the client JSON and save it in the repository as
   `secrets/google-oauth-client.json`. Do not paste its contents into the UI.
   Docker mounts `secrets/` read-only; its app user (UID 10001) must be able to read
   this file. On Linux, run from the repository:

   ```sh
   sudo chown 10001:10001 secrets/google-oauth-client.json
   sudo chmod 600 secrets/google-oauth-client.json
   ```

5. In the **same project**, create an API key for Picker. Restrict it to **Websites**
   with these referrers (substitute your actual app origin):
   `http://localhost:8080/*` and `https://docs.google.com/*`.
   Restrict API access to **Google Picker API**. This browser API key is different
   from the OAuth client secret. Copy the numeric **Project number** from the
   project's settings; do not use the project name or project ID.
6. Add these four settings to your private `.env`:

   ```dotenv
   GOOGLE_OAUTH_CLIENT_FILE=/run/secrets/google-oauth-client.json
   GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8080/api/connections/google/callback
   GOOGLE_PICKER_API_KEY=replace-with-your-restricted-picker-key
   GOOGLE_CLOUD_PROJECT_NUMBER=replace-with-your-numeric-project-number
   ```

7. Apply the settings with `docker compose up -d --no-build --force-recreate app`
   after installing the latest app image. Then click **Connect Google**, complete
   consent, and return to Workbench. Sign-in persists in the app's data volume.

## Map and review

Choose the tab and header row (1–100). Name and LinkedIn profile URL are required;
company, role, country and outreach status are optional. Matching headers are
suggested, and the first five rows show whether your choices are correct.

Map status if the sheet contains past outreach. Supported values are `new`,
`not contacted`, `not_contacted`, `review`, `sent`, `pending`, `connected`,
`replied`, `do not contact`, `do_not_contact`, and Spanish equivalents `nuevo`,
`sin contactar`, `enviado`, `pendiente`, `conectado`, `respondido`, `no contactar`.
A blank status means no recorded history. Unknown statuses are skipped for review.
If no status column exists, explicitly confirm the source has no prior history.

Preview shows every action before writing locally. Duplicate LinkedIn URLs retain
existing contact fields and receipts. Prior outreach history adds a sending
exclusion, including for existing contacts; it never invents a confirmed delivery.
New contacts are **unassessed**, not automatically qualified for outreach. Import
is for collecting/reviewing records; it does not launch qualification research.

Imports record the source workbook, tab, row and timestamp. They never edit the
source or make it an export destination. Export controls are separate. Limits:
1,000 data rows per tab, columns A–AX, and a 15-minute preview. Split larger sources
into tabs. A changed account or app restart requires a new preview.

## Troubleshooting

- **redirect_uri_mismatch:** match the exact browser origin/port and callback in
  `.env` and Google's OAuth client. Re-download the JSON after changing its callback.
- **Client file invalid:** check its location and container UID 10001 read permission.
- **Picker error:** check all three APIs, numeric project number, API key restrictions,
  and that the key and OAuth client belong to the same project.
- **File unavailable:** select it in Picker using the same Google account. Picker
  cannot grant permissions you do not already have. A disabled API can also cause
  access errors; check the Cloud project if selecting the file does not resolve it.
- **Session expired:** reconnect. Google Testing-mode refresh tokens for these
  scopes can expire after seven days.
- **After rebuild:** retain the `workbench-data` volume. Do not use `down -v` if you
  want to keep contacts and sign-ins. Disconnect removes this app's stored tokens;
  Google's account permissions page can revoke the grant entirely.

Implementation references: [Picker setup](https://developers.google.com/workspace/drive/picker/guides/web-picker),
[per-file scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth),
[OAuth](https://developers.google.com/identity/protocols/oauth2/web-server).
