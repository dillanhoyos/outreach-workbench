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
    p=sub.add_parser('discover');p.add_argument('query');p.add_argument('--limit',type=int,default=10)
    p=sub.add_parser('read');p.add_argument('--limit',type=int,default=100)
    p=sub.add_parser('list');p.add_argument('table',choices=['leads','replies','deliveries','jobs','holds'])
    p=sub.add_parser('approve');p.add_argument('lead_id');p.add_argument('note')
    p=sub.add_parser('send');p.add_argument('lead_ids',nargs='+');p.add_argument('--confirm',action='store_true')
    args=parser.parse_args()
    if args.command=='serve':
        import uvicorn
        uvicorn.run('workbench.app:create_app',factory=True,host='0.0.0.0',port=8080)
        return
    routes={'status':('GET','/api/status',None),'schema':('GET','/api/schema',None)}
    if args.command=='discover':route=('POST','/api/discover',{'query':args.query,'limit':args.limit})
    elif args.command=='read':route=('POST','/api/replies/read',{'limit':args.limit})
    elif args.command=='list':route=('GET','/api/records/'+args.table,None)
    elif args.command=='approve':route=('POST','/api/leads/'+args.lead_id+'/approve',{'note':args.note})
    elif args.command=='send':route=('POST','/api/outreach',{'lead_ids':args.lead_ids,'confirm':args.confirm})
    else:route=routes[args.command]
    with httpx.Client(base_url=args.url,timeout=30,headers={'Authorization':'Bearer '+os.environ.get('WORKBENCH_TOKEN','')}) as client:
        r=client.request(route[0],route[1],json=route[2]);print(json.dumps(r.json(),indent=2));r.raise_for_status()
