"""Cron entry point: call the running app; never open a second browser or database."""
import argparse,json,os,time,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

def run(limit=100,timeout=1200):
    token=os.environ.get('WORKBENCH_TOKEN','')
    if not token:raise RuntimeError('WORKBENCH_TOKEN missing in the app container.')
    def api(path,body=None):
        request=Request('http://127.0.0.1:8080/api/'+path,data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with urlopen(request,timeout=30) as response:return json.load(response)
    status=api('status')
    if status['mode']!='live':return {'status':'skipped','reason':'Workspace is not in live mode.'}
    if status['busy']:return {'status':'skipped','reason':'Workspace busy; no overlapping browser job started.'}
    if status.get('linkedin_restriction'):return {'status':'skipped','reason':'LinkedIn restriction requires review.'}
    try:job_id=api('replies/read',{'limit':limit})['job_id']
    except HTTPError as exc:
        if exc.code==409:return {'status':'skipped','reason':'Workspace became busy.'}
        raise
    print(json.dumps({'status':'started','job_id':job_id}),flush=True)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        jobs=api('records/jobs');job=next((j for j in jobs if j['id']==job_id),None)
        if job and job['status']!='running':
            result=json.loads(job['result'])
            return {'status':job['status'],'job_id':job_id,'result':result}
        time.sleep(5)
    return {'status':'observation_timeout','job_id':job_id,'reason':'Inspect the existing job. No second scan was submitted.'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=100,choices=range(1,101),metavar='1..100');args=parser.parse_args()
    try:
        result=run(args.limit);print(json.dumps(result),flush=True)
        return 0 if result['status'] in ('completed','skipped') else 1
    except (HTTPError,URLError,TimeoutError,RuntimeError) as exc:
        print(json.dumps({'status':'failed','reason':type(exc).__name__,'message':'Reader could not finish. Check app health and History; no automatic retry.'}),flush=True);return 1
if __name__=='__main__':sys.exit(main())
