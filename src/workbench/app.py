"""Local authenticated API. Workers never run on a recurring schedule."""
import json
import secrets
import threading
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from .config import Settings
from .store import Store, now
from .demo import DemoProvider

class DiscoveryRequest(BaseModel):
    query: str = Field(min_length=2,max_length=500)
    limit: int = Field(default=10,ge=1,le=100)

class Approval(BaseModel):
    note: str = Field(min_length=1,max_length=200)

class SendRequest(BaseModel):
    lead_ids: list[str] = Field(min_length=1,max_length=100)
    confirm: bool = False

class ReadRequest(BaseModel):
    limit: int = Field(default=100,ge=1,le=100)

class HoldRequest(BaseModel):
    company: str = Field(min_length=1,max_length=200)
    reason: str = Field(min_length=1,max_length=500)


def create_app(settings=None, provider=None):
    settings=settings or Settings.from_env()
    store=Store(settings.data_dir)
    app=FastAPI(title='Outreach Workbench',version='0.1.0',docs_url=None,redoc_url=None,openapi_url=None)
    # Live implementation supplied independently, never silently fall back to demo.
    if provider is None:
        if settings.mode=='demo':provider=DemoProvider()
        else:
            from .providers import LiveProvider
            provider=LiveProvider(settings,store)
    executor=ThreadPoolExecutor(max_workers=1)
    busy=threading.Lock()
    app.state.store=store

    def auth(authorization: str = Header(default='')):
        if not secrets.compare_digest(authorization,'Bearer '+settings.token):
            raise HTTPException(401,'Enter your local workbench token')

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400,content={'detail':str(exc)})

    def job(kind,fn):
        if not busy.acquire(blocking=False):raise HTTPException(409,'A job is already running')
        ident=uuid.uuid4().hex
        try:
            with store.db() as db:db.execute('INSERT INTO jobs(id,kind,status,created) VALUES(?,?,?,?)',(ident,kind,'running',now()))
        except Exception:
            busy.release();raise
        def run():
            try:result=fn();status='completed'
            except Exception as exc:
                # Never persist raw HTTP errors, which may contain keys or payloads.
                result={'error':type(exc).__name__,'message':'Job stopped. Check connection status; uncertain sends must be reconciled.'};status='failed'
            finally:
                with store.db() as db:db.execute('UPDATE jobs SET status=?,result=? WHERE id=?',(status,json.dumps(result),ident))
                busy.release()
        executor.submit(run)
        return {'job_id':ident}

    @app.get('/health')
    def health():return {'status':'ok'}

    @app.get('/')
    def index():return FileResponse(Path(__file__).parent/'static/index.html')

    @app.get('/api/status',dependencies=[Depends(auth)])
    def status():
        return {'mode':settings.mode,'daily_limit':settings.daily_limit,
                'apollo_configured':bool(settings.apollo_key),'sheets_configured':bool(settings.sheet_id and settings.google_credentials),
                'busy':busy.locked(),'account':store.setting('account')}

    @app.get('/api/schema',dependencies=[Depends(auth)])
    def schema():return app.openapi()

    @app.get('/api/records/{table}',dependencies=[Depends(auth)])
    def records(table:str):return store.list(table)

    @app.post('/api/discover',dependencies=[Depends(auth)])
    def discover(body:DiscoveryRequest):
        def work():
            leads=provider.discover(body.query,body.limit)
            added=sum(store.add_lead(x) for x in leads)
            return {'found':len(leads),'added':added,'duplicates':len(leads)-added}
        return job('discovery',work)

    @app.post('/api/leads/{ident}/approve',dependencies=[Depends(auth)])
    def approve(ident:str,body:Approval):
        store.approve(ident,body.note);return {'status':'approved'}

    @app.post('/api/outreach',dependencies=[Depends(auth)])
    def outreach(body:SendRequest):
        if not body.confirm:raise HTTPException(400,'Explicit confirmation required')
        if len(set(body.lead_ids))!=len(body.lead_ids):raise HTTPException(400,'Duplicate IDs')
        def work():
            results=[]
            for ident in body.lead_ids:
                lead=store.reserve(ident,settings.daily_limit)
                try:
                    receipt=provider.send(lead)
                    if receipt['status'] not in ('confirmed','simulated','skipped','blocked','uncertain'):raise ValueError('Unknown receipt')
                except Exception:
                    store.delivery(ident,'uncertain','Provider action did not return a conclusive receipt; no automatic retry.')
                    raise
                store.delivery(ident,receipt['status'],receipt['evidence'])
                results.append({'lead_id':ident,**receipt})
                if receipt['status'] in ('blocked','uncertain'):break
            return {'results':results}
        return job('outreach',work)

    @app.post('/api/replies/read',dependencies=[Depends(auth)])
    def read(body:ReadRequest):
        def work():
            rows=provider.read(store.list('leads'),body.limit)
            return {'observed':len(rows),'added':sum(store.reply(**r) for r in rows)}
        return job('reader',work)

    @app.post('/api/holds',dependencies=[Depends(auth)])
    def hold(body:HoldRequest):
        with store.db() as db:db.execute('INSERT OR REPLACE INTO holds VALUES(?,?)',(body.company.casefold().strip(),body.reason))
        return {'status':'held'}

    return app
