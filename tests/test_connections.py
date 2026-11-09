import json
import os
import sys
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from workbench.connections import JevConnection
from workbench.codex_auth import CodexAuth
from workbench.errors import ProviderError
from workbench.app import create_app
from workbench.config import Settings


def client(code=200):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(code, json={'models':['fixture'], 'data':['fixture']})))


def test_jev_private_persistence_and_failed_replacement(tmp_path):
    settings=SimpleNamespace(data_dir=tmp_path, typesafe_key='environment-key', browser_advisor='none')
    connection=JevConnection(settings)
    with client() as c: connection.connect('workspace-key', c)
    assert connection.path.stat().st_mode & 0o777 == 0o600
    assert 'workspace-key' not in json.dumps(connection.status())
    with client(429) as c, pytest.raises(ProviderError): connection.connect('replacement-key', c)
    assert JevConnection(settings).key() == 'workspace-key'
    connection.disconnect()
    assert JevConnection(settings).key() == ''


@pytest.fixture
def fake_codex(tmp_path):
    script=tmp_path/'fake.py'
    script.write_text('''import json, sys, os
account=None
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 method=m['method']; result={}
 if method=='account/read': result={'account':account}
 if method=='account/login/start':
  if m['params']['type']=='apiKey': account={'type':'apiKey'}
  else: result={'loginId':'fixture','verificationUrl':'https://auth.openai.com/codex/device','userCode':'TEST-CODE'}
 if method=='account/logout': account=None
 print(json.dumps({'id':m['id'],'result':result}), flush=True)
''')
    auth=CodexAuth(tmp_path,[sys.executable,str(script)])
    yield auth
    auth.close()


def test_codex_device_cancel_key_and_logout(fake_codex, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','must-not-inherit')
    assert not fake_codex.status()['signed_in']
    pending=fake_codex.start_device()['pending']
    assert pending['user_code']=='TEST-CODE'
    fake_codex.cancel()
    assert fake_codex.status()['pending'] is None
    with client() as c: assert fake_codex.connect_key('fixture-test-key',c)['signed_in']
    assert 'fixture-test-key' not in json.dumps(fake_codex.status())
    assert not fake_codex.logout()['signed_in']
    if os.path.exists(f'/proc/{fake_codex.process.pid}/environ'):
        assert b'must-not-inherit' not in open(f'/proc/{fake_codex.process.pid}/environ','rb').read()


def test_connection_api_protection_and_no_secret_echo(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setattr('workbench.app.CodexAuth',lambda directory:fake_codex)
    settings=Settings(tmp_path/'app','x'*32,'live','',10,'','')
    with TestClient(create_app(settings)) as api:
        assert api.get('/api/connections').status_code==401
        assert api.post('/api/connections/codex/login').status_code==401
        api.headers['Authorization']='Bearer '+'x'*32
        response=api.get('/api/connections')
        assert response.headers['cache-control']=='no-store'
        assert not response.json()['codex']['signed_in']
        response=api.post('/api/connections/jev',json={'key':{'secret':'do-not-echo'}})
        assert response.status_code==422 and 'do-not-echo' not in response.text
        assert api.post('/api/connections/codex/login').json()['pending']
        assert api.post('/api/connections/codex/cancel').status_code==200
        assert api.post('/api/discover',json={'prompt':'Find finance professionals','limit':3}).status_code==503
        assert api.get('/api/records/jobs').json()==[]
