# Security

This is a single-operator local application. Bind its ports to localhost and use
SSH forwarding for remote access. Do not publish the web UI, Selenium port or VNC
viewer directly to the internet.

Protect `.env`, `secrets/`, application databases and the browser-profile volume.
All API operations except static HTML and health require a random local bearer
token. The browser password is separate. Never submit credentials, real contacts,
private conversations, screenshots of your inbox or browser cookies in an issue.

For a vulnerability, use the repository's private vulnerability reporting feature
if enabled. Otherwise open a minimal issue requesting a private reporting channel,
without including exploit details or sensitive information. Supported security
fixes target the latest main branch; this early release has no long-term support
commitment.

Incoming messages and provider data are untrusted. The app displays them as text,
writes Sheets values as RAW, and never treats them as executable instructions.
A downstream agent must preserve that boundary. State reservation and uncertainty
handling reduce duplicate actions; they cannot guarantee platform availability or
protect an account from a provider restriction.

Before sharing a bug report, reproduce it with fictional fixtures. Tests and CI
must never send real invitations or consume live provider credits.
