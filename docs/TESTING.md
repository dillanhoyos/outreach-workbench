# Verification

Unit/API tests use fictional identities, temporary databases, and HTTP fixtures.
They require no real provider accounts. Browser fixture tests use actual Chromium
against a local HTML document; they never navigate to LinkedIn or send invitations.

```sh
pip install -c requirements.lock -e '.[test]'
pytest -q
python scripts/audit_public.py
```

## Fresh container test

Use a separate Compose project to avoid existing data. Generate `.env` first.
The following ports must be free; select alternatives if needed.

```sh
APP_PORT=18081 BROWSER_PORT=17900 docker compose -p workbench-test --profile live up --build -d --wait
WORKBENCH_URL=http://localhost:18081 python scripts/demo_smoke.py
APP_PORT=18081 BROWSER_PORT=17900 docker compose -p workbench-test run --rm -v "$PWD:/workspace:ro" app python /workspace/scripts/browser_smoke.py
```

The fixture script exercises Chrome startup, session reattachment, a rejected
wrong-recipient action, exact invitation-note preservation, and one successful
simulated click. All identities and invitation events are fictional.

Cleanup only the disposable test project:

```sh
docker compose -p workbench-test --profile live down --volumes
```

`--volumes` deletes that project's demo data and test browser profile. Never use
that option against a real workspace without an intentional backup.

## Live verification boundary

Google writes and Jev control selection are contract-tested with fixtures. A user's
account permissions and workspace policies must still be
checked during their own onboarding. LinkedIn UI compatibility can change. No
claim is made that fixture results establish current authenticated production
behavior, inbox completeness, accepted invitations or account safety.

The reader reports unique conversation-card checks and imports visible incoming
messages only for matched CRM profiles. Time limits and identity review cases
are reported separately. An ambiguous send is permanently reserved until a human
reconciles it; there is deliberately no automatic resend endpoint.

If a fatal error interrupts reading before the batch returns, that batch is not
imported. Resolve the error before rerunning; successfully imported replies are
deduplicated. See IMPLEMENTATION.md for remaining scope limits.

## Embedded browser onboarding

Use a disposable Compose project in live mode with an empty browser profile and
no provider keys. Install `playwright` as a separate test tool, then run
`playwright install chromium`. Set `WORKBENCH_URL` to that project's app URL;
`WORKBENCH_TOKEN` and `VNC_PASSWORD` can come from your private environment or `.env`.
Run `python scripts/onboarding_smoke.py` to check the app password, offline
instructions, the actual embedded noVNC connection/password prompt, and mobile
layout. `PLAYWRIGHT_CHROMIUM_EXECUTABLE` can select an existing test Chromium.

The optional `--login-page` flag opens LinkedIn's real sign-in page in that
**disposable** browser. It does not enter LinkedIn credentials, complete 2FA,
verify a signed-in identity or send invitations. Never point that flag at a real
account's browser. API tests cover demo-mode and missing-browser login failures.
An iframe load event alone is not proof of a working VNC connection: this test
waits for noVNC's connected state after password entry.

The browser entrypoint holds an exclusive profile lock and clears only Chromium's
three temporary Singleton lock/socket links on startup. Browser recreation tests
reuse the same volume to verify that saved profile data is retained and Chrome
can launch after the container hostname changes. Never share a profile volume
with a separately managed Chrome process.
