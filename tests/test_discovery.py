from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings


def test_live_discovery_requires_auth_without_running_or_adding_leads(tmp_path):
    settings = Settings(tmp_path, 'x'*32, 'live', '', 10, '', '')
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + 'x'*32
        assert client.get('/api/status').json()['discovery']['ready'] is False
        result = client.post('/api/discover', json={'prompt': 'Find accounting managers at road operators', 'limit': 3})
        assert result.status_code == 503 and 'Sign in to Codex' in result.json()['detail']
        assert client.get('/api/records/jobs').json() == []
        assert client.get('/api/records/leads').json() == []


def test_discovery_requires_research_brief_and_rejects_provider_filters(tmp_path):
    settings = Settings(tmp_path, 'x'*32, 'demo', '', 10, '', '')
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + 'x'*32
        assert client.post('/api/discover', json={'limit': 3}).status_code == 422
        assert client.post('/api/discover', json={'prompt': 'Find finance people', 'locations': ['Example']}).status_code == 422
        assert client.get('/api/status').json()['discovery'] == {'ready': True, 'provider': 'demo'}


def test_planning_allowed_before_browser_verification_but_research_blocked(tmp_path, monkeypatch):
    import time
    from workbench.research import Discovery
    class SignedIn:
        def __init__(self,*args):pass
        def status(self):return {'signed_in':True}
        def close(self):pass
    monkeypatch.setattr('workbench.app.CodexAuth',SignedIn)
    monkeypatch.setattr(Discovery,'prepare',lambda self,prompt,limit:{'summary':'Fixture plan'})
    with TestClient(create_app(Settings(tmp_path,'x'*32,'live','',10,'',''))) as client:
        client.headers['Authorization']='Bearer '+'x'*32
        state=client.get('/api/status').json()['discovery']
        assert state['plan_ready'] is True and state['ready'] is False
        assert 'Verify my account' in state['reason']
        assert client.post('/api/discovery/plan',json={'prompt':'Find founders','limit':3}).status_code==200
        for _ in range(100):
            if not client.get('/api/status').json()['busy']:break
            time.sleep(.01)
        assert client.post('/api/discover',json={'prompt':'Find founders','plan_id':'fixture','history_ack':True}).status_code==503
        assert client.get('/api/records/leads').json()==[]
