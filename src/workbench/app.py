"""Local authenticated API. Workers never run on a recurring schedule."""
import json
import fcntl
from contextlib import asynccontextmanager, contextmanager
import secrets
import threading
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, SecretStr
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .connections import JevConnection
from .codex_auth import CodexAuth
from .config import Settings
from .store import Store, now
from .demo import DemoProvider
from .errors import ProviderError
from .sheets import SheetsSync
from .google_connection import GoogleConnection
from .research import Discovery
from .research_browser import ResearchBrowser

class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=2, max_length=5000)
    limit: int = Field(default=3, ge=1, le=100)
    plan_id: str = Field(default="",max_length=64)
    history_ack: bool = False
    max_profiles: int = Field(default=0, ge=0, le=500, strict=True)
    max_minutes: int = Field(default=15, ge=1, le=60, strict=True)
    web_first: bool = True
    recheck_failed: bool = False
    profile_url: str = Field(default="",max_length=1000)

class ClearSearchHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False

class BriefMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=2,max_length=3000)
    brief: str = Field(default='',max_length=5000)

class SheetDestination(BaseModel):
    value: str = Field(min_length=10,max_length=500)

class SheetRows(SheetDestination):
    tab_id: int
    header_row: int = Field(default=1,ge=1,le=100)
class SheetMapping(BaseModel):
    snapshot_id: str = Field(min_length=10,max_length=100)
    mapping: dict[str,int]
    history_ack: bool = False
class SheetCommit(BaseModel):
    snapshot_id: str = Field(min_length=10,max_length=100)
    confirm: bool = False

class ConnectionKey(BaseModel):
    key: SecretStr

class Approval(BaseModel):
    campaign_id: str | None = Field(default=None,max_length=100)
    note: str = Field(min_length=1,max_length=200)

class ComposeRequest(BaseModel):
    instructions: str = Field(default="",max_length=3000)
    note: str = Field(default="",max_length=200)
    campaign_id: str | None = Field(default=None,max_length=100)

class SendRequest(BaseModel):
    retry_created: str | None = None
    expected_notes: dict[str,str] | None = None
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
    reader_stop=threading.Event()
    app.state.store=store
    jev_connection = JevConnection(settings)
    codex_connection = CodexAuth(settings.data_dir)
    google_connection = GoogleConnection(settings)
    from .sheets_import import SheetsImport
    sheets_import=SheetsImport(google_connection,store)
    research = Discovery(store,codex_connection,ResearchBrowser(provider.linkedin) if hasattr(provider,"linkedin") else None,jev_connection)
    store.setting("research_active",False)
    from .outreach import Composer
    composer=Composer(store,codex_connection,settings.mode)

    @asynccontextmanager
    async def lifespan(app):
        try:yield
        finally:
            research.stop.set()
            reader_stop.set()
            executor.shutdown(wait=True,cancel_futures=True)
            codex_connection.close()
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

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse(status_code=400, content={'detail': str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo credential inputs in validation error responses.
        return JSONResponse(status_code=422, content={'detail': 'Invalid request fields. Check the form and try again.'})

    @app.middleware('http')
    async def private_connections(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/connections'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @contextmanager
    def connection_idle():
        if not busy.acquire(blocking=False):
            raise HTTPException(409, 'Wait for the current job before changing connections.')
        try:
            yield
        finally:
            busy.release()

    @app.get('/api/connections', dependencies=[Depends(auth)])
    def connections():
        try: codex_status = codex_connection.status()
        except ProviderError as exc:
            codex_status = {'available': False, 'signed_in': False, 'message': str(exc)}
        return {'jev': jev_connection.status(), 'codex': codex_status, 'google':google_connection.status()}

    @app.post('/api/connections/jev', dependencies=[Depends(auth)])
    def connect_jev(body: ConnectionKey):
        with connection_idle():
            return jev_connection.connect(body.key.get_secret_value())

    @app.post('/api/connections/jev/check', dependencies=[Depends(auth)])
    def check_jev():
        with connection_idle():
            return jev_connection.check()

    @app.delete('/api/connections/jev', dependencies=[Depends(auth)])
    def disconnect_jev():
        with connection_idle():
            return jev_connection.disconnect()

    @app.post('/api/connections/codex/login', dependencies=[Depends(auth)])
    def codex_login():
        with connection_idle():
            return codex_connection.start_device()

    @app.post('/api/connections/codex/key', dependencies=[Depends(auth)])
    def codex_key(body: ConnectionKey):
        with connection_idle():
            return codex_connection.connect_key(body.key.get_secret_value())

    @app.post('/api/connections/codex/check', dependencies=[Depends(auth)])
    def codex_check():
        with connection_idle():
            return codex_connection.check()

    @app.post('/api/connections/codex/cancel', dependencies=[Depends(auth)])
    def codex_cancel():
        with connection_idle():
            return codex_connection.cancel()

    @app.delete('/api/connections/codex', dependencies=[Depends(auth)])
    def codex_logout():
        with connection_idle():
            return codex_connection.logout()

    @app.post('/api/connections/google/login', dependencies=[Depends(auth)])
    def google_login():
        with connection_idle():return google_connection.start()

    @app.get('/api/connections/google/callback')
    def google_callback(state: str = '', code: str = '', error: str = ''):
        # OAuth state binds this callback to an authenticated start request.
        try:
            with connection_idle():google_connection.finish(state,code,error)
            message='Google connected. Close this tab and return to Outreach Workbench.'
            status=200
        except (ProviderError,HTTPException):
            message='Google sign-in did not complete. Return to the app and start Google sign-in again.'
            status=400
        return HTMLResponse('<!doctype html><title>Google connection</title><p>'+message+'</p>',status_code=status,
                            headers={'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'"})

    @app.delete('/api/connections/google', dependencies=[Depends(auth)])
    def google_disconnect():
        with connection_idle():return google_connection.disconnect()

    @app.post('/api/connections/google/sheet',dependencies=[Depends(auth)])
    def google_select(body:SheetDestination):
        with connection_idle():return google_connection.select_sheet(store,body.value)

    @app.get('/api/connections/google/picker',dependencies=[Depends(auth)])
    def google_picker():
        with connection_idle():
            return JSONResponse(google_connection.picker_config(),headers={'Cache-Control':'no-store','Pragma':'no-cache'})

    @app.post('/api/sheets/inspect',dependencies=[Depends(auth)])
    def sheet_inspect(body:SheetDestination):
        with connection_idle():return sheets_import.inspect(body.value)

    @app.post('/api/sheets/rows',dependencies=[Depends(auth)])
    def sheet_rows(body:SheetRows):
        with connection_idle():return sheets_import.rows(body.value,body.tab_id,body.header_row)

    @app.post('/api/sheets/preview',dependencies=[Depends(auth)])
    def sheet_preview(body:SheetMapping):
        with connection_idle():return sheets_import.preview(body.snapshot_id,body.mapping,body.history_ack)

    @app.post('/api/sheets/import',dependencies=[Depends(auth)])
    def sheet_import(body:SheetCommit):
        with connection_idle():return sheets_import.commit(body.snapshot_id,body.confirm)

    @app.post('/api/sheets/create', dependencies=[Depends(auth)])
    def google_create():
        if settings.mode!='live':raise HTTPException(400,'Switch to live mode before creating a Google spreadsheet.')
        return job('sheets-create',lambda:google_connection.create_sheet(store))

    def job(kind,fn):
        if not busy.acquire(blocking=False):raise HTTPException(409,'A job is already running')
        ident=uuid.uuid4().hex
        if kind in ('discovery','discovery-plan','discovery-brief'):research.stop.clear()
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

    def discovery_status():
        if settings.mode=='demo':return {'ready':True,'provider':'demo'}
        try:connected=codex_connection.status()['signed_in']
        except ProviderError:connected=False
        reason=('Sign in to Codex under Your connections.' if not connected else
                'Resolve the recorded LinkedIn restriction first.' if store.setting('linkedin_restriction') else '')
        return {'ready':not bool(reason),'plan_ready':connected,'provider':'codex_browser','reason':reason}

    @app.get('/api/status',dependencies=[Depends(auth)])
    def status():
        return {'mode':settings.mode,'daily_limit':settings.daily_limit,
                'browser_advisor':settings.browser_advisor,'jev_configured':bool(jev_connection.key()),
                'discovery':discovery_status(),'sheets_configured':bool((google_connection.status()['connected'] and store.setting('oauth_sheet_id')) or (settings.sheet_id and settings.google_credentials)),
                'google_sheet_id':store.setting('oauth_sheet_id') or '',
                'busy':busy.locked(),'account':store.setting('account'),
                'linkedin_restriction':store.setting('linkedin_restriction'),
                'reader_report':store.setting('last_reader_report')}

    @app.get('/api/browser/status',dependencies=[Depends(auth)])
    def browser_connection():
        from .browser_status import browser_status
        return browser_status(settings)

    @app.get('/api/schema',dependencies=[Depends(auth)])
    def schema():return app.openapi()

    @app.get('/api/crm/history',dependencies=[Depends(auth)])
    def crm_history():
        with store.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM workspace_changes ORDER BY id DESC LIMIT 200')]

    @app.get('/api/crm/report',dependencies=[Depends(auth)])
    def crm_report():
        from .crm import report
        with store.db() as db:return report(db)

    @app.get('/api/records/{table}',dependencies=[Depends(auth)])
    def records(table:str):return research.crm_records() if table=='leads' else store.list(table)

    @app.post('/api/leads/import',dependencies=[Depends(auth)])
    def import_leads(body:LeadImport):
        if busy.locked():raise HTTPException(409,'Wait for the current job')
        from .store import profile_key
        for lead in body.leads:profile_key(lead.url)
        return {'added':sum(store.add_lead(lead.model_dump()) for lead in body.leads)}

    @app.post('/api/discover',dependencies=[Depends(auth)])
    def discover(body:DiscoveryRequest):
        if settings.mode != 'demo':
            state=discovery_status()
            if not state['ready']:raise HTTPException(503,state['reason'])
            if not body.plan_id or not body.history_ack:
                raise HTTPException(400,'Review a research plan and confirm your CRM history before starting.')
            if research.browser is None:raise HTTPException(503,'Live browser provider is unavailable.')
            return job('discovery',lambda:research.run(body.plan_id,body.history_ack))
        def work():
            found=provider.discover(body.prompt,body.limit)
            leads=found.get('candidates',[]) if isinstance(found,dict) else found
            added=sum(store.add_lead(x) for x in leads)
            return {'found':len(leads),'added':added,'duplicates':len(leads)-added}
        return job('discovery',work)

    @app.get('/api/discovery/state',dependencies=[Depends(auth)])
    def research_state():return research.state()

    @app.post('/api/discovery/brief',dependencies=[Depends(auth)])
    def refine_brief(body:BriefMessage):
        if settings.mode!='live' or not discovery_status().get('plan_ready'):
            raise HTTPException(400,'Connect your research agent to discuss your audience.')
        if len(body.message.strip())<2:raise HTTPException(400,'Describe what you want to refine.')
        return job('discovery-brief',lambda:research.refine(body.message.strip(),body.brief.strip()))

    @app.post('/api/discovery/history/clear',dependencies=[Depends(auth)])
    def clear_search_history(body:ClearSearchHistory):
        if not body.confirm:raise HTTPException(400,'Confirm clearing search history first.')
        if not busy.acquire(blocking=False):
            raise HTTPException(409,'Wait for the current job to finish before clearing search history.')
        try:return research.clear_history()
        finally:busy.release()

    @app.post('/api/discovery/brief/reset',dependencies=[Depends(auth)])
    def reset_brief():
        with connection_idle():
            return research.reset_brief()

    @app.post('/api/discovery/plan',dependencies=[Depends(auth)])
    def research_plan(body:DiscoveryRequest):
        state=discovery_status()
        if settings.mode!='live' or not state.get('plan_ready'):
            raise HTTPException(400,state.get('reason') or 'Research plans require live mode.')
        if body.limit>10:raise HTTPException(400,'Use 1–10 candidates per research run.')
        return job('discovery-plan',lambda:research.prepare(body.prompt,body.limit,body.web_first,body.recheck_failed,body.profile_url,body.max_minutes,body.max_profiles))

    @app.post('/api/discovery/stop',dependencies=[Depends(auth)])
    def research_stop():
        research.stop.set()
        return {'message':'Stop requested. The current browser read will finish; no new visits will begin.'}

    @app.get('/api/leads/{ident}/composer',dependencies=[Depends(auth)])
    def composer_state(ident:str):return composer.state(ident)

    @app.post('/api/leads/{ident}/draft',dependencies=[Depends(auth)])
    def draft_note(ident:str,body:ComposeRequest):
        if not body.instructions.strip():raise HTTPException(400,'Describe the message you want to write.')
        return job('message-draft',lambda:composer.generate(ident,body.instructions,body.campaign_id))

    @app.post('/api/leads/{ident}/draft/save',dependencies=[Depends(auth)])
    def save_note(ident:str,body:ComposeRequest):
        with connection_idle():return composer.save(ident,body.note,body.instructions,body.campaign_id)

    @app.post('/api/crm/{ident}/profile',dependencies=[Depends(auth)])
    def crm_profile(ident:str):
        record=next((r for r in research.crm_records() if r['id']==ident),None)
        if not record:raise HTTPException(404,'CRM contact not found.')
        from .store import profile_key
        profile_key(record['url'])
        if settings.mode!='live':return {'message':'Demo contact: no LinkedIn navigation was performed.'}
        if not research.browser:raise HTTPException(503,'Private browser is unavailable.')
        def open_profile():
            research.browser.profile(record['url'])
            return {'message':'Profile opened in your private browser.'}
        return job('crm-profile',open_profile)

    @app.post('/api/leads/{ident}/preview',dependencies=[Depends(auth)])
    def preview_recipient(ident:str):
        if settings.mode!='live':return {'message':'Demo profile is fictional; no browser visit needed.'}
        return job('outreach-preview',lambda:composer.preview(ident,research.browser))

    @app.post('/api/leads/{ident}/approve' ,dependencies=[Depends(auth)])
    def approve(ident:str,body:Approval):
        store.approve(ident,body.note,body.campaign_id);return {'status':'approved'}

    @app.post('/api/outreach',dependencies=[Depends(auth)])
    def outreach(body:SendRequest):
        if not body.confirm:raise HTTPException(400,'Explicit confirmation required')
        if body.retry_created is not None and (len(body.lead_ids)!=1 or body.expected_notes is None):raise HTTPException(400,'Retry requires one recipient and the exact original note')
        if len(set(body.lead_ids))!=len(body.lead_ids):raise HTTPException(400,'Duplicate IDs')
        if body.expected_notes is not None and set(body.expected_notes)!=set(body.lead_ids):raise HTTPException(400,'Confirm the exact note for every selected recipient')
        def work():
            results=[]
            # Reject stale reviewed text before sending any member of a batch.
            if len(body.lead_ids)>1:
                if body.expected_notes is None:raise ValueError('Review the exact note for every batch recipient')
                for ident in body.lead_ids:
                    candidate=store.get_lead(ident)
                    if candidate['status']!='approved' or candidate['note']!=body.expected_notes[ident]:
                        raise ValueError('A recipient or note changed. Review the batch again.')
            for ident in body.lead_ids:
                try:
                    lead=store.reserve(ident,settings.daily_limit,body.expected_notes.get(ident) if body.expected_notes is not None else None,body.retry_created)
                except ValueError as exc:
                    if len(body.lead_ids)==1:raise
                    return {'results':results,'reason':str(exc),'stopped_before':ident}
                try:
                    receipt=provider.send(lead)
                    if receipt['status'] not in ('confirmed','simulated','skipped','blocked','uncertain'):raise ValueError('Unknown receipt')
                except Exception:
                    store.delivery(ident,'uncertain','Provider action did not return a conclusive receipt; no automatic retry.')
                    if len(body.lead_ids)>1:
                        results.append({'lead_id':ident,'status':'uncertain','evidence':'No conclusive provider receipt. Batch stopped without retry.'})
                        return {'results':results,'reason':'Provider action did not return a conclusive receipt'}
                    raise
                store.delivery(ident,receipt['status'],receipt['evidence'])
                results.append({'lead_id':ident,**receipt})
                if receipt['status'] in ('blocked','uncertain') or store.setting('linkedin_restriction'):break
            return {'results':results}
        return job('outreach',work)

    @app.post('/api/replies/read',dependencies=[Depends(auth)])
    def read(body:ReadRequest):
        def work():
            from .reader import run_reader
            reader_stop.clear()
            return run_reader(store,provider,body.limit,reader_stop)
        return job('reader',work)

    @app.post('/api/replies/stop',dependencies=[Depends(auth)])
    def stop_reader():
        reader_stop.set()
        return {'message':'Stop requested. Already verified replies stay saved.'}

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

    @app.post('/api/linkedin/restriction/clear',dependencies=[Depends(auth)])
    def clear_restriction(body:RestrictionRequest):
        if not body.resolved:raise HTTPException(400,'Confirm the restriction has been resolved by LinkedIn')
        if busy.locked():raise HTTPException(409,'Wait for the current job to finish')
        store.setting('linkedin_restriction',False)
        return {'status':'cleared','message':'Next action will check the signed-in browser session.'}

    @app.post('/api/sheets/sync',dependencies=[Depends(auth)])
    def sync():return job('sheets',lambda:SheetsSync(settings,store,google=google_connection).sync())

    @app.post('/api/holds',dependencies=[Depends(auth)])
    def hold(body:HoldRequest):
        with store.db() as db:db.execute('INSERT OR REPLACE INTO holds VALUES(?,?)',(body.company.casefold().strip(),body.reason))
        return {'status':'held'}

    return app
