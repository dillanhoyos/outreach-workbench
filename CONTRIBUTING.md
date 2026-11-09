# Contributing

Use Python 3.12 and a separate workspace. Start with the demo; you do not need
LinkedIn, Apollo, Google, or paid model credentials to contribute.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -c requirements.lock -e '.[test]'
pytest -q
```

For changes to browser behavior, run the isolated fixture smoke test described in
`docs/TESTING.md`. Add meaningful tests for identity validation, action receipts,
rate limits and recovery, rather than testing selectors alone.

Keep provider integrations separate from workflow state. Do not introduce hidden
retries of sending, bypasses for provider restrictions, hardcoded CRM destinations,
or imports of a user's session. Every live action must remain explicitly reviewed.

Submit focused pull requests with the problem, behavior change and validation.
Use fictional records in examples. Run the public-data audit before committing:

```sh
python3 scripts/audit_public.py
```

New providers should expose the same discover/send/read contract, document their
authentication and costs, and supply fixtures. UI changes should remain usable on
small screens and preserve keyboard access and readable error messages.
