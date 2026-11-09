"""Local authenticated API. Workers never run on a recurring schedule."""
import json
import fcntl
from contextlib import asynccontextmanager
import secrets
import threading
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import Settings
from .store import Store, now
from .demo import DemoProvider
from .errors import ProviderError
from .sheets import SheetsSync

class DiscoveryRequest(BaseModel):
    query: str = Field(min_length=2,max_length=500)
    limit: int = Field(default=10,ge=1,le=100)
    locations: list[str] = Field(default_factory=list,max_length=20)
    domains: list[str] = Field(default_factory=list,max_length=20)
    allow_paid_enrichment: bool = False

class Approval(BaseModel):
    note: str = Field(min_length=1,max_length=200)

class SendRequest(BaseModel):
    lead_ids: list[str] = Field(min_length=1,max_length=100)
    confirm: bool = False

class ReadRequest(BaseModel):
    limit: int = Field(default=100,ge=1,le=100)

class LeadInput(BaseModel):
    name: str = Field(min_length=1,max_length=200)
    company: str = Field(min_length=1,max_length=300)
    role: str = Field(min_length=1,max_length=300)
    country: str = Field(min_length=1,max_length=100)
    url: str = Field(min_length=1,max_length=500)
    evidence: str = Field(min_length=1,max_length=3000)

class LeadImport(BaseModel):
    leads: list[LeadInput] = Field(min_length=1,max_length=100)

class AccountRequest(BaseModel):
    profile_url: str = Field(min_length=10,max_length=300)

class RestrictionRequest(BaseModel):
    resolved: bool = False

class HoldRequest(BaseModel):
    company: str = Field(min_length=1,max_length=200)
    reason: str = Field(min_length=1,max_length=500)


def create_app(settings=None, provider=None):
    settings=settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    process_lock=(settings.data_dir/'instance.lock').open('a')
    try:fcntl.flock(process_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        process_lock.close()
        raise RuntimeError('Another Workbench process owns this data directory') from None
    store=Store(settings.data_dir/settings.mode)
    app=FastAPI(title='Outreach Workbench',version='0.1.0',docs_url=None,redoc_url=None,openapi_url=None)
    app.mount('/assets', StaticFiles(directory=Path(__file__).parent/'static'), name='assets')
    # Live implementation supplied independently, never silently fall back to demo.
    if provider is None:
        if settings.mode=='demo':provider=DemoProvider()
        else:
            from .providers import LiveProvider
            provider=LiveProvider(settings,store)
    executor=ThreadPoolExecutor(max_workers=1)
    busy=threading.Lock()
    app.state.store=store

    @asynccontextmanager
    async def lifespan(app):
        try:yield
        finally:
            executor.shutdown(wait=True,cancel_futures=True)
            if hasattr(provider,'linkedin'):provider.linkedin.close_transport()
            fcntl.flock(process_lock,fcntl.LOCK_UN)
            process_lock.close()
    app.router.lifespan_context=lifespan

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
                result={'error':type(exc).__name__,'message':str(exc) if isinstance(exc,ProviderError) else 'Job stopped. Check connection status; uncertain sends must be reconciled.'};status='failed'
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
                'browser_advisor':settings.browser_advisor,'jev_configured':bool(settings.typesafe_key),
                'apollo_configured':bool(settings.apollo_key),'sheets_configured':bool(settings.sheet_id and settings.google_credentials),
                'busy':busy.locked(),'account':store.setting('account'),
                'linkedin_restriction':store.setting('linkedin_restriction'),
                'reader_report':store.setting('last_reader_report')}

    @app.get('/api/browser/status',dependencies=[Depends(auth)])
    def browser_connection():
        from .browser_status import browser_status
        return browser_status(settings)

    @app.get('/api/schema',dependencies=[Depends(auth)])
    def schema():return app.openapi()

    @app.get('/api/records/{table}',dependencies=[Depends(auth)])
    def records(table:str):return store.list(table)

    @app.post('/api/leads/import',dependencies=[Depends(auth)])
    def import_leads(body:LeadImport):
        if busy.locked():raise HTTPException(409,'Wait for the current job')
        from .store import profile_key
        for lead in body.leads:profile_key(lead.url)
        return {'added':sum(store.add_lead(lead.model_dump()) for lead in body.leads)}

    @app.post('/api/discover',dependencies=[Depends(auth)])
    def discover(body:DiscoveryRequest):
        def work():
            found=provider.discover(body.query,body.limit,locations=body.locations,domains=body.domains,allow_paid_enrichment=body.allow_paid_enrichment)
            leads=found.get('candidates',[]) if isinstance(found,dict) else found
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

    def linkedin():
        if settings.mode!='live' or not hasattr(provider,'linkedin'):
            raise HTTPException(400,'Set WORKBENCH_MODE=live and start the browser container first')
        return provider.linkedin

    @app.post('/api/linkedin/login',dependencies=[Depends(auth)])
    def login():
        browser = linkedin()
        from .browser_status import browser_status
        if not browser_status(settings)['available']:
            raise HTTPException(503, 'Browser is unavailable. Run docker compose --profile live up --build -d --wait, then check again.')
        return job('linkedin-login',browser.start_login)

    @app.post('/api/linkedin/reset',dependencies=[Depends(auth)])
    def reset():return job('linkedin-reset',lambda:linkedin().reset_connection())

    @app.post('/api/linkedin/verify',dependencies=[Depends(auth)])
    def verify(body:AccountRequest):
        browser = linkedin()
        return job('linkedin-verify',lambda:browser.verify_account(body.profile_url))

    @app.post('/api/linkedin/restriction/clear',dependencies=[Depends(auth)])
    def clear_restriction(body:RestrictionRequest):
        if not body.resolved:raise HTTPException(400,'Confirm the restriction has been resolved by LinkedIn')
        if busy.locked():raise HTTPException(409,'Wait for the current job to finish')
        store.setting('linkedin_restriction',False)
        return {'status':'cleared','message':'Next action will recheck the account and page.'}

    @app.post('/api/sheets/sync',dependencies=[Depends(auth)])
    def sync():return job('sheets',lambda:SheetsSync(settings,store).sync())

    @app.post('/api/holds',dependencies=[Depends(auth)])
    def hold(body:HoldRequest):
        with store.db() as db:db.execute('INSERT OR REPLACE INTO holds VALUES(?,?)',(body.company.casefold().strip(),body.reason))
        return {'status':'held'}

    return app
