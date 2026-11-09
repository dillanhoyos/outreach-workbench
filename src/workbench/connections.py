"""Private provider credentials and bounded, read-only connection checks."""
import json
import os
import tempfile
from pathlib import Path
import httpx
from .errors import ProviderError, check_response
from .store import now


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.connection-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def validate_key(key):
    key = key.strip()
    if not 8 <= len(key) <= 4096 or any(c.isspace() for c in key):
        raise ProviderError('Enter a valid API key without spaces.')
    return key


def check_key(key, provider, client=None):
    url = {'Jev': 'https://api.typesafe.ai/v1/models', 'Codex': 'https://api.openai.com/v1/models'}[provider]
    def request(c):
        response = c.get(url, headers={'Authorization': 'Bearer ' + key}, timeout=15)
        data = check_response(response, provider)
        models = data.get('models' if provider == 'Jev' else 'data')
        if not isinstance(models, list) or not models:
            raise ProviderError(f'{provider} returned no accessible models. Check account permissions.')
        return {'checked_at': now(), 'message': 'Authentication and model listing succeeded. No model generation was run.'}
    try:
        if client is not None: return request(client)
        with httpx.Client(trust_env=False) as c: return request(c)
    except ProviderError: raise
    except Exception:
        raise ProviderError(f'{provider} connection check failed. Check network access and try again; no automatic retry.') from None


class JevConnection:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.data_dir / 'connections' / 'jev.json'

    def saved(self):
        if not self.path.exists(): return {}
        return json.loads(self.path.read_text())

    def key(self):
        saved = self.saved()
        return saved['key'] if 'key' in saved else self.settings.typesafe_key

    def status(self):
        saved = self.saved()
        return {'configured': bool(self.key()), 'checked_at': saved.get('checked_at'),
                'source': 'workspace' if 'key' in saved else 'environment',
                'advisor_enabled': self.settings.browser_advisor == 'jev'}

    def connect(self, key, client=None):
        key = validate_key(key)
        result = check_key(key, 'Jev', client)
        private_json(self.path, {'key': key, 'checked_at': result['checked_at']})
        return result

    def check(self, client=None):
        key = self.key()
        if not key: raise ProviderError('Connect your Jev API key first.')
        return self.connect(key, client)

    def disconnect(self):
        # Empty override prevents an old environment key from reconnecting silently.
        private_json(self.path, {'key': ''})
        return {'message': 'Jev disconnected from this workspace. Revoke the key at TypeSafe if needed.'}
