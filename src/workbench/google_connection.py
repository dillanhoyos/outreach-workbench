"""Per-installation Google OAuth, with a fixed callback and private token storage."""
import json
import os
import secrets
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession
from .connections import private_json
from .errors import ProviderError, check_response

SCOPE='https://www.googleapis.com/auth/drive.file'

class GoogleConnection:
    def __init__(self,settings):
        self.path=settings.data_dir/'connections'/'google.json'
        self.client_path=os.getenv('GOOGLE_OAUTH_CLIENT_FILE','')
        self.redirect=os.getenv('GOOGLE_OAUTH_REDIRECT_URI','')
        self.pending=None;self.lock=threading.Lock()

    def config(self):
        if not self.client_path or not self.redirect:
            raise ProviderError('Configure GOOGLE_OAUTH_CLIENT_FILE and GOOGLE_OAUTH_REDIRECT_URI first. See Google connection setup.')
        try:
            u=urlsplit(self.redirect)
            if (u.username or u.password or u.query or u.fragment or u.path!='/api/connections/google/callback'
                or not (u.scheme=='https' or (u.scheme=='http' and u.hostname in ('localhost','127.0.0.1')))):
                raise ValueError()
            config=json.loads(Path(self.client_path).read_text())
            web=config['web']
            if web['auth_uri']!='https://accounts.google.com/o/oauth2/auth' or web['token_uri']!='https://oauth2.googleapis.com/token':
                raise ValueError()
            if self.redirect not in web['redirect_uris']:raise ValueError()
            return config
        except (ValueError,KeyError,OSError,TypeError):
            raise ProviderError('Google OAuth client file or callback is invalid. Register the exact callback URL in your Google web application client.') from None

    def saved(self):
        if not self.path.exists():return {}
        try:return json.loads(self.path.read_text())
        except (ValueError,OSError):raise ProviderError('Google credentials could not be read. Reconnect Google.') from None

    def status(self):
        try:self.config();configured=True;message=''
        except ProviderError as exc:configured=False;message=str(exc)
        return {'configured':configured,'connected':bool(self.saved().get('refresh_token')),
                'message':message,'redirect_uri':self.redirect}

    def start(self):
        with self.lock:
            flow=Flow.from_client_config(self.config(),scopes=[SCOPE],redirect_uri=self.redirect,
                                         autogenerate_code_verifier=True)
            url,state=flow.authorization_url(access_type='offline',prompt='consent',include_granted_scopes='false')
            self.pending={'state':state,'flow':flow,'expires':time.monotonic()+600}
            return {'authorization_url':url}

    def finish(self,state,code,error=''):
        with self.lock:
            pending=self.pending
            if not pending or not secrets.compare_digest(state,pending['state']) or time.monotonic()>pending['expires']:
                raise ProviderError('Google sign-in expired or its state did not match. Start again from the app.')
            self.pending=None
            if error or not code:raise ProviderError('Google sign-in was cancelled or denied.')
            try:
                # Passing the code directly avoids accepting an untrusted callback origin.
                pending['flow'].fetch_token(code=code,timeout=20)
                creds=pending['flow'].credentials
                if not creds.refresh_token or not creds.has_scopes([SCOPE]):raise ValueError()
                private_json(self.path,json.loads(creds.to_json()))
            except Exception:
                raise ProviderError('Google token exchange failed. Check the OAuth client, consent and callback settings, then reconnect.') from None

    def credentials(self):
        try:
            saved=self.saved()
            if not saved.get('refresh_token'):raise ValueError()
            return Credentials.from_authorized_user_info(saved,scopes=[SCOPE])
        except (ValueError,KeyError):raise ProviderError('Connect Google first.') from None

    def persist(self,creds):private_json(self.path,json.loads(creds.to_json()))

    def disconnect(self):
        with self.lock:
            self.pending=None
            private_json(self.path,{})
        return {'message':'Google disconnected locally. You can also revoke access in your Google account.'}

    def create_sheet(self,store):
        existing=store.setting('oauth_sheet_id')
        if existing:return {'spreadsheet_url':'https://docs.google.com/spreadsheets/d/'+existing+'/edit'}
        if store.setting('google_creation_pending'):
            raise ProviderError('A prior spreadsheet creation is uncertain. Check Google Drive before reconnecting a destination; creation will not be repeated automatically.')
        creds=self.credentials()
        store.setting('google_creation_pending',True)
        try:
            with AuthorizedSession(creds) as client:
                data=check_response(client.post('https://sheets.googleapis.com/v4/spreadsheets',
                    json={'properties':{'title':'Outreach Workbench CRM'}},timeout=30),'Google Sheets')
            ident=data['spreadsheetId']
            store.setting('oauth_sheet_id',ident)
            store.setting('google_creation_pending',False)
            self.persist(creds)
            return {'spreadsheet_url':'https://docs.google.com/spreadsheets/d/'+ident+'/edit'}
        except ProviderError:raise
        except Exception:raise ProviderError('Could not confirm spreadsheet creation. Check Google Drive; no automatic retry.') from None

    def select_sheet(self,store,value):
        value=value.strip()
        if value.startswith('https://'):
            url=urlsplit(value)
            if url.hostname!='docs.google.com' or url.username or url.password or url.port not in (None,443):
                raise ProviderError('Use a Google Sheets URL or spreadsheet ID.')
            match=re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]+)(?:/.*)?',url.path)
            value=match.group(1) if match else ''
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',value):raise ProviderError('Use a valid spreadsheet ID.')
        creds=self.credentials()
        try:
            with AuthorizedSession(creds) as client:
                data=check_response(client.get('https://sheets.googleapis.com/v4/spreadsheets/'+value,
                    params={'fields':'spreadsheetId'},timeout=20),'Google Sheets')
            if data.get('spreadsheetId')!=value:raise ProviderError('Could not verify the spreadsheet.')
            store.setting('oauth_sheet_id',value)
            store.setting('google_creation_pending',False)
            self.persist(creds)
            return {'message':'Spreadsheet access verified. Sync still protects tabs owned by other installations.'}
        except ProviderError:raise
        except Exception:raise ProviderError('Could not verify spreadsheet access. Use a file previously created by this app and Google account, or create a new CRM.') from None
