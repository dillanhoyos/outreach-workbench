import time
from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings


def test_end_to_end_demo_and_auth(tmp_path):
    settings=Settings(tmp_path,'x'*32,'demo','',10,'','')
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/status').status_code==401
        client.headers['Authorization']='Bearer '+'x'*32
        assert client.get('/api/status').json()['mode']=='demo'
        def wait():
            for _ in range(100):
                if not client.get('/api/status').json()['busy']:return
                time.sleep(.01)
            raise AssertionError('Job did not finish')
        assert client.post('/api/discover',json={'prompt':'Find finance professionals','limit':3}).status_code==200
        wait()
        leads=client.get('/api/records/leads').json();assert len(leads)==3
        ident=leads[0]['id']
        assert client.post('/api/leads/'+ident+'/approve',json={'note':'Hello from the demo'}).status_code==200
        assert client.post('/api/outreach',json={'lead_ids':[ident]}).status_code==400
        assert client.post('/api/outreach',json={'lead_ids':[ident],'confirm':True}).status_code==200
        wait()
        assert client.get('/api/records/deliveries').json()[0]['status']=='simulated'
        client.post('/api/replies/read',json={'limit':100});wait()
        assert len(client.get('/api/records/replies').json())==1
        client.post('/api/replies/read',json={'limit':100});wait()
        assert len(client.get('/api/records/replies').json())==1


def test_process_lock_and_mode_isolation(tmp_path):
    demo=Settings(tmp_path,'x'*32,'demo','',10,'','')
    with TestClient(create_app(demo)) as client:
        import pytest
        with pytest.raises(RuntimeError,match='Another'):
            create_app(demo)
        client.headers['Authorization']='Bearer '+'x'*32
        record={'name':'Example Person','role':'Controller','company':'Example Company','country':'Example',
                'url':'https://www.linkedin.com/in/example-import','evidence':'Synthetic fixture'}
        assert client.post('/api/leads/import',json={'leads':[record]}).json()['added']==1
        assert client.post('/api/leads/import',json={'leads':[record]}).json()['added']==0
    from workbench.demo import DemoProvider
    live=Settings(tmp_path,'x'*32,'live','',10,'','')
    with TestClient(create_app(live,provider=DemoProvider())) as client:
        client.headers['Authorization']='Bearer '+'x'*32
        assert client.get('/api/records/leads').json()==[]
