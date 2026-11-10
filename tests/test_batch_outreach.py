import time
import pytest
from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings
from workbench.demo import DemoProvider


def wait(client,response):
    assert response.status_code==200,response.text
    ident=response.json()['job_id']
    for _ in range(200):
        job=next(j for j in client.get('/api/records/jobs').json() if j['id']==ident)
        if job['status']!='running':return job
        time.sleep(.01)
    raise AssertionError('Job did not finish')


@pytest.mark.parametrize('scenario',['success','stale_note','daily_limit','blocked','uncertain','provider_error'])
def test_batch_review_and_partial_receipts(tmp_path,scenario):
    class Provider(DemoProvider):
        calls=[]
        def send(self,lead):
            self.calls.append(lead['id'])
            if scenario=='provider_error':raise RuntimeError('Fixture transport failed')
            if scenario in ('blocked','uncertain'):return {'status':scenario,'evidence':'Fixture stop'}
            return super().send(lead)
    provider=Provider()
    settings=Settings(tmp_path,'x'*32,'demo','',1 if scenario=='daily_limit' else 10,'','')
    with TestClient(create_app(settings,provider=provider)) as client:
        client.headers['Authorization']='Bearer '+'x'*32
        wait(client,client.post('/api/discover',json={'prompt':'Finance fixture','limit':3}))
        leads=client.get('/api/records/leads').json()
        notes={l['id']:'Hello '+l['name'] for l in leads}
        for lead in leads:
            assert client.post('/api/leads/'+lead['id']+'/approve',json={'note':notes[lead['id']]}).status_code==200
        if scenario=='stale_note':notes[leads[-1]['id']]='Outdated text'
        job=wait(client,client.post('/api/outreach',json={'lead_ids':[l['id'] for l in leads],'expected_notes':notes,'confirm':True}))
        receipts=client.get('/api/records/deliveries').json()
        if scenario=='stale_note':
            assert job['status']=='failed' and not receipts and not provider.calls
        else:
            import json
            assert job['status']=='completed'
            result=json.loads(job['result'])
            expected=3 if scenario=='success' else 1
            assert len(receipts)==len(result['results'])==len(provider.calls)==expected
            if scenario=='daily_limit':assert 'Daily action limit' in result['reason']
            if scenario=='provider_error':assert receipts[0]['status']=='uncertain'
            assert len(set(provider.calls))==len(provider.calls)
