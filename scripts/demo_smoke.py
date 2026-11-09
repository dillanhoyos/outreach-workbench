"""Exercise the public API against a fresh demo container; no real providers."""
import json
import os
from pathlib import Path
import time
import urllib.request

base=os.getenv('WORKBENCH_URL','http://localhost:8080')
root=Path(__file__).resolve().parents[1]
values=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
token=values['WORKBENCH_TOKEN']

def api(path,body=None):
    req=urllib.request.Request(base+'/api/'+path,data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)

def job(path,body):
    ident=api(path,body)['job_id']
    for _ in range(100):
        result=next(j for j in api('records/jobs') if j['id']==ident)
        if result['status']!='running':
            assert result['status']=='completed',result
            return json.loads(result['result'])
        time.sleep(.1)
    raise RuntimeError('Demo job deadline exceeded')

assert api('status')['mode']=='demo'
job('discover',{'prompt':'Find controllers at infrastructure operators','limit':3})
leads=api('records/leads');assert len(leads)==3
lead=leads[0]
api('leads/'+lead['id']+'/approve',{'note':'Hello from the fictional demo.'})
job('outreach',{'lead_ids':[lead['id']],'confirm':True})
assert api('records/deliveries')[0]['status']=='simulated'
assert job('replies/read',{'limit':100})['added']==1
assert job('replies/read',{'limit':100})['added']==0
assert len(api('records/replies'))==1
print('PASS: fresh container discovery → approval → simulated outreach → deduplicated replies')
