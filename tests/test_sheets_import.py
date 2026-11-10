import time
from types import SimpleNamespace
import pytest
from workbench.sheets_import import SheetsImport,sheet_id
from workbench.errors import ProviderError
from workbench.store import Store

@pytest.fixture
def importer(tmp_path):
    google=SimpleNamespace(saved=lambda:{'refresh_token':'fixture'})
    imp=SheetsImport(google,Store(tmp_path))
    imp.get=lambda path,params=None: ({'properties':{'title':'Contacts'},'sheets':[{'properties':{'sheetId':0,'title':"Team's leads",'gridProperties':{'columnCount':6}}}]} if '/values/' not in path else {'values':[
        ['Name','LinkedIn','Company','Role','Country','Status'],
        ['Ada','https://www.linkedin.com/in/fixture-ada/','Test','Founder','US','new'],
        ['Bea','https://www.linkedin.com/in/fixture-bea/','Test','Founder','US','sent'],
        ['Ada duplicate','https://www.linkedin.com/in/fixture-ada/','Overwrite','Other','MX','replied'],
        ['Invalid','https://evil.example/','','','','new'],
        ['Unknown','https://www.linkedin.com/in/fixture-unknown/','','','','surprise']]})
    return imp

def preview(imp):
    snap=imp.rows('fixture-sheet-id',0,1)
    return imp.preview(snap['snapshot_id'],dict(name=0,url=1,company=2,role=3,country=4,status=5),False)

def test_preview_commit_history_duplicates_and_idempotency(importer):
    p=preview(importer)
    assert p['import_count']==2 and p['excluded_count']==2 and p['skip_count']==2
    with importer.store.db() as db:assert db.execute('SELECT COUNT(*) FROM leads').fetchone()[0]==0
    with pytest.raises(ProviderError):importer.commit(p['snapshot_id'],False)
    result=importer.commit(p['snapshot_id'],True)
    assert result=={'added':2,'skipped':3,'excluded':2}
    assert importer.commit(p['snapshot_id'],True)==result
    with importer.store.db() as db:
        assert db.execute('SELECT COUNT(*) FROM leads').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM crm_exclusions').fetchone()[0]==2
        assert db.execute("SELECT company FROM leads WHERE name='Ada'").fetchone()[0]=='Test'
        assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==0
    p2=preview(importer)
    assert importer.commit(p2['snapshot_id'],True)['added']==0

def test_mapping_account_and_expiry(importer):
    token=importer.rows('fixture-sheet-id',0,1)['snapshot_id']
    for mapping,ack in [({'name':0},True),({'name':0,'url':0},True),({'name':0,'url':1},False),({'name':0,'url':99},True)]:
        with pytest.raises(ProviderError):importer.preview(token,mapping,ack)
    importer.google.saved=lambda:{'refresh_token':'different'}
    with pytest.raises(ProviderError,match='account changed'):importer.snapshot(token)
    importer.google.saved=lambda:{'refresh_token':'fixture'}
    importer.snapshots[token]['expires']=time.monotonic()-1
    with pytest.raises(ProviderError,match='expired'):importer.snapshot(token)

def test_access_and_bounds(importer):
    importer.get=lambda *a,**k:None
    assert importer.inspect('fixture-sheet-id')['needs_picker']
    with pytest.raises(ProviderError):importer.rows('fixture-sheet-id',0,1)

@pytest.mark.parametrize('value',['http://docs.google.com/spreadsheets/d/test-file-id','https://evil.example/spreadsheets/d/test-file-id','https://user@docs.google.com/spreadsheets/d/test-file-id','https://docs.google.com:99/spreadsheets/d/test-file-id','../secret','https://docs.google.com/document/d/test-file-id'])
def test_invalid_url(value):
    with pytest.raises(ProviderError):sheet_id(value)

def test_url():
    assert sheet_id('https://docs.google.com/spreadsheets/d/test-file-id/edit#gid=0')=='test-file-id'

def test_atomic_failure(importer,monkeypatch):
    from workbench import crm
    p=preview(importer)
    monkeypatch.setattr(crm,'assessment',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('fixture failure')))
    with pytest.raises(RuntimeError):importer.commit(p['snapshot_id'],True)
    with importer.store.db() as db:assert db.execute('SELECT COUNT(*) FROM leads').fetchone()[0]==0

def test_existing_history_preserves_fields_and_blocks(importer):
    importer.store.add_lead(dict(name='Original',url='https://www.linkedin.com/in/fixture-bea/',company='Original Co',role='CFO',country='CO',evidence='original evidence'))
    p=preview(importer);result=importer.commit(p['snapshot_id'],True)
    assert result['added']==1 and result['excluded']==2
    with importer.store.db() as db:
        row=db.execute("SELECT * FROM leads WHERE profile_key='fixture-bea'").fetchone()
        assert row['name']=='Original' and row['evidence']=='original evidence'
        from workbench.crm import enrich
        enriched=enrich(db,[dict(row)])[0]
        assert enriched['excluded'] and not enriched['outreach_available']
        imported=db.execute("SELECT * FROM leads WHERE profile_key='fixture-ada'").fetchone()
        assert enrich(db,[dict(imported)])[0]['qualification']=='unassessed'

def test_google_transport_is_get_only_and_rate_limit_stops(importer,monkeypatch):
    from workbench import sheets_import
    del importer.get
    importer.google.credentials=lambda:object()
    importer.google.persist=lambda creds:None
    state={'status':403,'calls':0}
    class Session:
        def __init__(self,*args):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):
            state['calls']+=1
            assert url.startswith('https://sheets.googleapis.com/v4/spreadsheets/')
            return SimpleNamespace(status_code=state['status'],json=lambda:{})
    monkeypatch.setattr(sheets_import,'AuthorizedSession',Session)
    assert importer.inspect('fixture-sheet-id')['needs_picker']
    state['status']=429
    with pytest.raises(ProviderError,match='rate limit'):importer.inspect('fixture-sheet-id')
    assert state['calls']==2

def test_row_limit_and_tab_range(importer):
    original=importer.get
    def get(path,params=None):
        if '/values/' not in path:return original(path,params)
        assert '%27Team%27%27s%20leads%27%21A2%3AAX1003' in path
        return {'values':[['Name','URL']]*1002}
    importer.get=get
    with pytest.raises(ProviderError,match='1,000'):importer.rows('fixture-sheet-id',0,2)
    with pytest.raises(ProviderError,match='tab'):importer.rows('fixture-sheet-id',999,2)
