import threading,time,json
from types import SimpleNamespace
from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings
from workbench.demo import DemoProvider

def test_profile_uses_private_browser_and_serializes_jobs(tmp_path,monkeypatch):
    started=threading.Event();release=threading.Event();visited=[]
    def profile(url):
        visited.append(url);started.set();release.wait(5);return {}
    monkeypatch.setattr('workbench.app.ResearchBrowser',lambda client:SimpleNamespace(profile=profile))
    provider=DemoProvider();provider.linkedin=SimpleNamespace(close_transport=lambda:None)
    app=create_app(Settings(tmp_path,'x'*32,'live','',10,'',''),provider=provider)
    app.state.store.add_lead(dict(name='Fixture',company='Test',role='Founder',country='CO',url='https://www.linkedin.com/in/fixture-person/',evidence='fixture'))
    ident=app.state.store.list('leads')[0]['id']
    with TestClient(app) as api:
        assert api.post('/api/crm/'+ident+'/profile').status_code==401
        api.headers['Authorization']='Bearer '+'x'*32
        assert api.post('/api/crm/missing/profile').status_code==404
        result=api.post('/api/crm/'+ident+'/profile');assert result.status_code==200
        try:
            assert started.wait(2)
            assert api.post('/api/crm/'+ident+'/profile').status_code==409
            assert api.post('/api/linkedin/restart').status_code==409
        finally:release.set()
        for _ in range(50):
            jobs=app.state.store.list('jobs')
            if jobs[0]['status']!='running':break
            time.sleep(.02)
        assert jobs[0]['status']=='completed'
        assert visited==['https://www.linkedin.com/in/fixture-person/']
        assert not app.state.store.list('deliveries')
