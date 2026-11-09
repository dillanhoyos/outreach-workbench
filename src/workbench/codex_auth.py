"""Official Codex app-server auth over private stdio. No model turns or shell tools."""
import json
import os
import queue
import subprocess
import threading
import time
from urllib.parse import urlsplit
from .connections import validate_key, check_key
from .errors import ProviderError


class CodexAuth:
    def __init__(self, directory, command=None):
        self.directory = directory / 'codex'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.command = command or ['codex', 'app-server',
                                   '-c', 'cli_auth_credentials_store="file"', '--listen', 'stdio://']
        self.process = None
        self.lock = threading.RLock()
        self.waiters = {}
        self.sequence = 0
        self.pending = None
        self.login_message = ''

    def _reader(self, process):
        try:
            for line in process.stdout:
                try: message = json.loads(line)
                except ValueError: continue
                if 'id' in message and message['id'] in self.waiters:
                    self.waiters[message['id']].put(message)
                elif message.get('method') == 'account/login/completed':
                    event = message.get('params', {})
                    if self.pending and event.get('loginId') == self.pending.get('login_id'):
                        self.pending = None
                        self.login_message = ('Sign-in completed.' if event.get('success') else
                                              'Sign-in did not complete. Enable device-code login in your OpenAI settings or try again.')
        finally:
            if self.process is process:
                for waiter in list(self.waiters.values()):
                    waiter.put({'error': {}})

    def _start(self):
        if self.process and self.process.poll() is None: return
        self.pending = None
        # Deliberately isolate from the host's Codex/OpenAI sessions and other API keys.
        env = {'PATH': os.environ.get('PATH', os.defpath), 'CODEX_HOME': str(self.directory.resolve()),
               'NO_COLOR': '1', 'LANG': 'C.UTF-8'}
        try:
            self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env, cwd=self.directory,
                start_new_session=True, umask=0o077)
        except OSError:
            raise ProviderError('Codex runtime is unavailable. Rebuild the app container to install it.') from None
        threading.Thread(target=self._reader, args=(self.process,), daemon=True).start()
        try:
            self._rpc('initialize', {'clientInfo': {'name': 'outreach_workbench', 'title': 'Outreach Workbench', 'version': '0.1.0'}})
            self.process.stdin.write(json.dumps({'method': 'initialized', 'params': {}}) + '\n')
            self.process.stdin.flush()
        except (ProviderError, OSError):
            self.close()
            raise ProviderError('Codex authentication service could not start. Rebuild the app and check connectivity.') from None

    def _rpc(self, method, params=None):
        with self.lock:
            self._start()
            self.sequence += 1
            ident = self.sequence
            waiter = queue.Queue()
            self.waiters[ident] = waiter
            try:
                self.process.stdin.write(json.dumps({'id': ident, 'method': method, 'params': params or {}}) + '\n')
                self.process.stdin.flush()
                message = waiter.get(timeout=25)
                if 'error' in message:
                    raise ProviderError('Codex could not complete this authentication action. Check connectivity and account permissions; device login may need enabling in OpenAI settings.')
                return message.get('result', {})
            except (OSError, queue.Empty):
                self.close()
                raise ProviderError('Codex authentication service timed out or stopped. Check the connection before trying again.') from None
            finally:
                self.waiters.pop(ident, None)

    def status(self, refresh=False):
        with self.lock:
            account = self._rpc('account/read', {'refreshToken': refresh}).get('account')
            if self.pending and time.monotonic() > self.pending['deadline']:
                self.cancel()
                self.login_message = 'Sign-in expired. Start again to get a new code.'
            if account:
                self.pending = None
            return {'available': True, 'signed_in': bool(account),
                    'account': {k: account.get(k) for k in ('type', 'email', 'planType')} if account else None,
                    'pending': {k: self.pending[k] for k in ('verification_url', 'user_code')} if self.pending else None,
                    'message': self.login_message}

    def start_device(self):
        with self.lock:
            if self.pending: return self.status()
            if self.status()['signed_in']:
                raise ProviderError('Codex is already signed in. Disconnect before switching accounts.')
            result = self._rpc('account/login/start', {'type': 'chatgptDeviceCode'})
            url = urlsplit(result.get('verificationUrl', ''))
            if (url.scheme != 'https' or url.hostname != 'auth.openai.com' or url.username or url.password
                    or url.port not in (None, 443) or not result.get('userCode') or not result.get('loginId')):
                self.close()
                raise ProviderError('Codex returned an unexpected sign-in link. No link was opened.')
            self.pending = {'login_id': result['loginId'], 'verification_url': result['verificationUrl'],
                            'user_code': result['userCode'], 'deadline': time.monotonic() + 900}
            self.login_message = 'Open the official sign-in page and enter the one-time code. Do not share it.'
            return self.status()

    def connect_key(self, key, client=None):
        with self.lock:
            if self.status()['signed_in'] or self.pending:
                raise ProviderError('Disconnect or cancel the existing Codex login before switching accounts.')
            key = validate_key(key)
            result = check_key(key, 'Codex', client)
            self._rpc('account/login/start', {'type': 'apiKey', 'apiKey': key})
            self.login_message = result['message']
            return self.status()

    def check(self, client=None):
        with self.lock:
            state = self.status(refresh=True)
            if not state['signed_in']: raise ProviderError('Sign in to Codex first.')
            if state['account']['type'] == 'apiKey':
                try: key = json.loads((self.directory / 'auth.json').read_text())['OPENAI_API_KEY']
                except (OSError, ValueError, KeyError):
                    raise ProviderError('Reconnect your Codex API key to check it.') from None
                check_key(key, 'Codex', client)
            self.login_message = 'Authentication checked. No model generation was run; model access and quotas are checked when research runs.'
            return self.status()

    def cancel(self):
        with self.lock:
            if self.pending:
                ident = self.pending['login_id']
                self._rpc('account/login/cancel', {'loginId': ident})
                self.pending = None
            self.login_message = 'Pending sign-in cancelled.'
            return {'message': self.login_message}

    def logout(self):
        with self.lock:
            self.cancel()
            self._rpc('account/logout')
            self.login_message = 'Codex disconnected from this workspace.'
            return self.status()

    def close(self):
        with self.lock:
            process, self.process = self.process, None
            self.pending = None
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
            if process:
                for stream in (process.stdin, process.stdout):
                    if stream: stream.close()
