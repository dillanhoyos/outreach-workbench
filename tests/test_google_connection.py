import json
import time
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
import pytest
from google.oauth2.credentials import Credentials
from workbench.google_connection import GoogleConnection,SCOPE
from workbench.errors import ProviderError

@pytest.fixture
def google(tmp_path,monkeypatch):
    callback='http://localhost:18080/api/connections/google/callback'
    config={'web':{'client_id':'fixture.apps.googleusercontent.com','client_secret':'fixture-client-value',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
        'redirect_uris':[callback]}}
    path=tmp_path/'client.json';path.write_text(json.dumps(config))
    monkeypatch.setenv('GOOGLE_OAUTH_CLIENT_FILE',str(path));monkeypatch.setenv('GOOGLE_OAUTH_REDIRECT_URI',callback)
    return GoogleConnection(SimpleNamespace(data_dir=tmp_path))

def test_google_authorization_uses_pkce_state_and_narrow_scope(google):
    params=parse_qs(urlsplit(google.start()['authorization_url']).query)
    assert params['scope']==[SCOPE] and params['access_type']==['offline']
    assert params['code_challenge_method']==['S256']
    assert params['state']==[google.pending['state']]
    with pytest.raises(ProviderError,match='state'):google.finish('wrong-state','fixture-code')
    assert not google.path.exists()

def test_google_callback_single_use_private_persistent_and_disconnect(google):
    google.start();state=google.pending['state']
    class Flow:
        credentials=Credentials(token='fixture-access',refresh_token='fixture-refresh',token_uri='https://oauth2.googleapis.com/token',
            client_id='fixture-client',client_secret='fixture-secret',scopes=[SCOPE])
        def fetch_token(self,**kwargs):assert kwargs['code']=='fixture-code'
    google.pending['flow']=Flow()
    google.finish(state,'fixture-code')
    assert google.path.stat().st_mode & 0o777==0o600
    assert google.status()['connected']
    assert 'fixture-refresh' not in json.dumps(google.status())
    assert google.credentials().refresh_token=='fixture-refresh'
    with pytest.raises(ProviderError):google.finish(state,'fixture-code')
    google.disconnect();assert not google.status()['connected']

def test_google_expired_denied_and_wrong_callback_do_not_store_tokens(google):
    google.start();google.pending['expires']=time.monotonic()-1
    with pytest.raises(ProviderError,match='expired'):google.finish(google.pending['state'],'fixture-code')
    google.start()
    with pytest.raises(ProviderError,match='cancelled'):google.finish(google.pending['state'],'','access_denied')
    assert not google.path.exists()
    google.redirect='http://attacker.example/api/connections/google/callback'
    assert not google.status()['configured']

def test_callback_rejects_unbound_request_without_echoing_code(tmp_path):
    from fastapi.testclient import TestClient
    from workbench.app import create_app
    from workbench.config import Settings
    with TestClient(create_app(Settings(tmp_path,'x'*32,'demo','',10,'',''))) as api:
        assert api.post('/api/connections/google/login').status_code==401
        response=api.get('/api/connections/google/callback?state=wrong&code=private-test-code')
        assert response.status_code==400 and 'private-test-code' not in response.text
        assert response.headers['cache-control']=='no-store'
        assert response.headers['referrer-policy']=='no-referrer'

def test_picker_config_only_short_lived_token(google,monkeypatch):
    monkeypatch.setenv('GOOGLE_PICKER_API_KEY','fixture-key')
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT_NUMBER','123456')
    creds=Credentials(token='fixture-access',refresh_token='fixture-refresh',token_uri='https://oauth2.googleapis.com/token',client_id='fixture-client',client_secret='fixture-secret',scopes=[SCOPE])
    monkeypatch.setattr(google,'credentials',lambda:creds)
    value=google.picker_config()
    assert value=={'access_token':'fixture-access','api_key':'fixture-key','app_id':'123456'}
    assert 'fixture-refresh' not in json.dumps(value) and 'fixture-secret' not in json.dumps(value)
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT_NUMBER','project-name')
    with pytest.raises(ProviderError,match='PROJECT_NUMBER'):google.picker_config()

def test_import_endpoints_require_auth_and_picker_no_store(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from workbench.app import create_app
    from workbench.config import Settings
    monkeypatch.setattr(GoogleConnection,'picker_config',lambda self:{'access_token':'fixture-access'})
    with TestClient(create_app(Settings(tmp_path,'x'*32,'demo','',10,'',''))) as api:
        for path in ('inspect','rows','preview','import'):
            assert api.post('/api/sheets/'+path,json={}).status_code==401
        assert api.get('/api/connections/google/picker').status_code==401
        response=api.get('/api/connections/google/picker',headers={'Authorization':'Bearer '+'x'*32})
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
