from types import SimpleNamespace
from urllib.parse import unquote
import pytest
from workbench.store import Store
from workbench.sheets import SheetsSync,TABS
from workbench.errors import ProviderError
from workbench.demo import DemoProvider

class Response:
    status_code=200
    def __init__(self,data):self.data=data
    def json(self):return self.data

class SheetsFixture:
    def __init__(self):self.sheets={};self.cells={};self.writes=0;self.corrupt=False
    def get(self,url,params=None,timeout=None):
        if '/values/' in url:
            vals=self.cells[unquote(url.split('/values/')[1])]
            return Response({'values':[] if self.corrupt else vals})
        return Response({'sheets':[{'properties':dict(title=k,sheetId=v,gridProperties={'rowCount':1000})} for k,v in self.sheets.items()]})
    def post(self,url,json,timeout=None):
        for r in json['requests']:
            if 'addSheet' in r:
                p=r['addSheet']['properties'];self.sheets[p['title']]=p['sheetId']
        return Response({})
    def put(self,url,params,json,timeout=None):
        assert params['valueInputOption']=='RAW'
        self.cells[unquote(url.split('/values/')[1])]=json['values'];self.writes+=1
        return Response({})


def setup(tmp_path):
    store=Store(tmp_path);store.add_lead(DemoProvider().discover('finance')[0])
    return store,SimpleNamespace(sheet_id='fixture-workbook',google_credentials='fixture-file')


def test_snapshot_sync_idempotent_and_literal(tmp_path):
    store,settings=setup(tmp_path);lead=store.list('leads')[0]
    store.reply('fixture-reply',lead['id'],'=IMPORTXML("https://example.com")','2026-01-01','fixture-thread')
    client=SheetsFixture();sync=SheetsSync(settings,store,client)
    assert sync.sync()['verified_rows']=={'leads':1,'replies':1,'deliveries':0}
    assert sync.sync()['verified_rows']['replies']==1
    assert len(client.sheets)==3
    assert next(v for k,v in client.cells.items() if 'Replies' in k)[1][2].startswith('=IMPORTXML')


def test_never_adopts_existing_tabs(tmp_path):
    store,settings=setup(tmp_path);client=SheetsFixture();client.sheets[TABS['leads']]=123
    with pytest.raises(ProviderError,match='does not own'):SheetsSync(settings,store,client).sync()
    assert client.writes==0


def test_readback_mismatch_stops(tmp_path):
    store,settings=setup(tmp_path);client=SheetsFixture();client.corrupt=True
    with pytest.raises(ProviderError,match='readback'):SheetsSync(settings,store,client).sync()
    assert client.writes==1

def test_oauth_destination_preserves_workbook_binding_across_all_tabs(tmp_path):
    store,settings=setup(tmp_path)
    store.setting('oauth_sheet_id','oauth-fixture-workbook')
    google=SimpleNamespace(status=lambda:{'connected':True})
    client=SheetsFixture()
    sync=SheetsSync(settings,store,client,google)
    assert sync.sync()['spreadsheet_url'].endswith('/oauth-fixture-workbook/edit')
    assert sync.sync()['verified_rows']['leads']==1
    assert set(store.setting('sheets_owned_tabs'))=={'oauth-fixture-workbook'}
    assert len(store.setting('sheets_owned_tabs')['oauth-fixture-workbook'])==3
