"""Create local app/viewer passwords; external service keys are supplied by the user."""
from pathlib import Path
import os
import argparse
import re
import shlex
import secrets

PLACEHOLDERS = {
    'WORKBENCH_TOKEN': {'', 'replace-with-a-random-token-of-at-least-24-characters'},
    'VNC_PASSWORD': {'', 'replace-me'},
}


def setup(root, reset_token=False):
    path = root / '.env'
    existed = path.exists()
    original = path.read_text() if existed else (root / '.env.example').read_text()
    lines = original.splitlines()
    generated = []
    for name, placeholders in PLACEHOLDERS.items():
        pattern = re.compile(r'^\s*(?:export\s+)?' + re.escape(name) + r'\s*=')
        matches = [i for i, line in enumerate(lines) if pattern.match(line)]
        if len(matches) > 1:
            raise ValueError(f'Remove duplicate {name} entries from .env before running setup.')
        if matches:
            index = matches[0]
            raw = lines[index].split('=', 1)[1].strip()
            try:
                value = shlex.split(raw, comments=True)[0] if raw.startswith(('"', "'")) else raw.split(' #', 1)[0].rstrip()
            except (ValueError, IndexError):
                if name == 'WORKBENCH_TOKEN' and reset_token:
                    value = ''
                else:
                    raise ValueError(f'Invalid quoting for {name} in .env. Fix the quotes or use --reset-token for the app password.') from None
            invalid = value in placeholders or (name == 'WORKBENCH_TOKEN' and len(value) < 24)
            if not invalid and not (name == 'WORKBENCH_TOKEN' and reset_token):
                continue
        value = secrets.token_urlsafe(32) if name == 'WORKBENCH_TOKEN' else secrets.token_hex(4)
        entry = name + '=' + value
        if matches:
            lines[index] = entry
        else:
            lines.append(entry)
        generated.append(name)
    if not existed or generated:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write('\n'.join(lines) + '\n')
    path.chmod(0o600)
    (root / 'secrets').mkdir(mode=0o700, exist_ok=True)
    print('Created .env from .env.example.' if not existed else 'Kept your existing .env settings and service keys.')
    print('Generated local passwords: ' + ', '.join(generated) if generated else 'Your existing local passwords were preserved.')
    print('1. Start/recreate the app: docker compose up --build -d --force-recreate --wait')
    print('   For live mode, add --profile live after docker compose.')
    print('2. Open http://localhost:8080 (or your configured APP_PORT).')
    print('3. Open .env in your text editor. Copy only the value after WORKBENCH_TOKEN= into the app Connect field.')
    print('VNC_PASSWORD is only for the browser viewer in live mode. It is NOT your LinkedIn password.')
    print('Setup does not create Jev, Apollo or Google accounts/keys. Add your own only when enabling those integrations.')
    print('For Jev: set BROWSER_ADVISOR=jev and TYPESAFE_API_KEY in .env. See docs/AUTHENTICATION.md.')
    print('Keep .env private. No passwords or keys were printed here.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset-token', action='store_true',
                        help='Replace only the app login password; preserve browser password and API keys.')
    args = parser.parse_args()
    setup(Path(__file__).resolve().parents[1], reset_token=args.reset_token)
