import argparse
import json
import os
import httpx

def main():
    parser=argparse.ArgumentParser(description='Authenticated agent-friendly Workbench CLI')
    parser.add_argument('--url',default='http://localhost:8080')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('serve')
    sub.add_parser('status')
    sub.add_parser('schema')
    sub.add_parser('login')
    sub.add_parser('sync')
    p=sub.add_parser('import');p.add_argument('file')
    sub.add_parser('reset-browser')
    p=sub.add_parser('verify');p.add_argument('profile_url')
    p=sub.add_parser('discover',help='Preview fictional leads in demo mode; use the UI for live plan review');p.add_argument('prompt');p.add_argument('--limit',type=int,default=10)
    p=sub.add_parser('read');p.add_argument('--limit',type=int,default=100)
    p=sub.add_parser('list');p.add_argument('table',choices=['leads','replies','deliveries','jobs','holds'])
    p=sub.add_parser('approve');p.add_argument('lead_id');p.add_argument('note')
    p=sub.add_parser('send');p.add_argument('lead_ids',nargs='+');p.add_argument('--confirm',action='store_true')
    args=parser.parse_args()
    if args.command=='serve':
        import uvicorn
        uvicorn.run('workbench.app:create_app',factory=True,host='0.0.0.0',port=8080,access_log=False)
        return
    routes={'status':('GET','/api/status',None),'schema':('GET','/api/schema',None),'login':('POST','/api/linkedin/login',{}),'sync':('POST','/api/sheets/sync',{}),'reset-browser':('POST','/api/linkedin/reset',{})}
    if args.command=='discover':route=('POST','/api/discover',{'prompt':args.prompt,'limit':args.limit})
    elif args.command=='import':
        from pathlib import Path
        route=('POST','/api/leads/import',{'leads':json.loads(Path(args.file).read_text())})
    elif args.command=='verify':route=('POST','/api/linkedin/verify',{'profile_url':args.profile_url})
    elif args.command=='read':route=('POST','/api/replies/read',{'limit':args.limit})
    elif args.command=='list':route=('GET','/api/records/'+args.table,None)
    elif args.command=='approve':route=('POST','/api/leads/'+args.lead_id+'/approve',{'note':args.note})
    elif args.command=='send':route=('POST','/api/outreach',{'lead_ids':args.lead_ids,'confirm':args.confirm})
    else:route=routes[args.command]
    with httpx.Client(base_url=args.url,timeout=30,headers={'Authorization':'Bearer '+os.environ.get('WORKBENCH_TOKEN','')}) as client:
        r=client.request(route[0],route[1],json=route[2]);print(json.dumps(r.json(),indent=2));r.raise_for_status()
