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


def test_research_starts_without_manual_identity_verification(tmp_path,monkeypatch):
    import time
    from types import SimpleNamespace
    from test_research import Browser,model
    from workbench.research import Discovery
    class SignedIn:
        def __init__(self,*args):pass
        def status(self):return {'signed_in':True}
        def close(self):pass
    class AccountBrowser(Browser):
        def __init__(self,store):super().__init__();self.store=store
        def close_transport(self):pass
    monkeypatch.setattr('workbench.app.CodexAuth',SignedIn)
    monkeypatch.setattr('workbench.providers.LiveProvider',lambda settings,store:SimpleNamespace(linkedin=AccountBrowser(store)))
    monkeypatch.setattr('workbench.app.ResearchBrowser',lambda browser:browser)
    monkeypatch.setattr('workbench.app.Discovery',lambda store,auth,browser,jev:Discovery(store,auth,browser,model=model))
    settings=Settings(tmp_path,'x'*32,'live','',10,'','')
    def wait(api):
        for _ in range(200):
            if not api.get('/api/status').json()['busy']:return
            time.sleep(.01)
        raise AssertionError('Job did not finish')
    with TestClient(create_app(settings)) as api:
        api.headers['Authorization']='Bearer '+'x'*32
        assert api.post('/api/discovery/plan',json={'prompt':'Find accounting professionals','limit':1}).status_code==200
        wait(api)
        assert api.get('/api/status').json()['account'] is None
        assert api.get('/api/status').json()['discovery']['ready']
        plan=api.get('/api/discovery/state').json()['plan']
        response=api.post('/api/discover',json={'prompt':plan['prompt'],'limit':1,'plan_id':plan['id'],'history_ack':True})
        assert response.status_code==200
        wait(api)
        assert len(api.get('/api/records/leads').json())==1
        assert api.get('/api/records/deliveries').json()==[]
    with TestClient(create_app(settings)) as api:
        api.headers['Authorization']='Bearer '+'x'*32
        assert api.get('/api/status').json()['discovery']['ready']
