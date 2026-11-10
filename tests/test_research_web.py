import json
import socket
import pytest
pytestmark=pytest.mark.usefixtures("short_research_deadline")
from workbench import research_web as web
from workbench.research import Discovery
from workbench.store import Store
from test_research import Browser, PROFILE, PERSON, model
from test_research_model import Auth
from workbench.research_model import reason
from workbench.errors import ProviderError

SOURCE='https://www.ycombinator.com/companies/fictional-roads'
PAGE={'url':SOURCE,'title':'Fictional Roads','text':'Batch: Summer 2024. '+PERSON['sector_quote'],'links':[PROFILE]}

@pytest.mark.parametrize('failure',[None,'wrong_batch','invented_quote','unobserved_profile'])
def test_web_company_evidence_precedes_linkedin_and_persists(tmp_path,monkeypatch,failure):
    def shortlist(*args,**kwargs):
        assert kwargs['web'] is True
        kwargs['on_search']({'query':'fixture','action':{'type':'search'}})
        return {'prospects':[{'name':PERSON['name'],'company':PERSON['company'],'profile_url':PROFILE,'source_url':SOURCE}]}
    monkeypatch.setattr(web,'reason',shortlist)
    monkeypatch.setattr(web,'fetch_source',lambda url:{**PAGE,'links':[] if failure=='unobserved_profile' else [PROFILE]})
    def reasoning(*args):
        if args[3]['title']=='CompanyFit':
            return {'qualified':failure!='wrong_batch','reason':'Fixture company evidence',
                    'quotes':['invented' if failure=='invented_quote' else 'Batch: Summer 2024.']}
        return model(*args)
    store=Store(tmp_path);browser=Browser();engine=Discovery(store,None,browser,model=reasoning)
    plan=engine.prepare('S24 concession operators',3,True)
    result=engine.run(plan['id'],True)
    assert result['staged']==(0 if failure else 1)
    assert browser.visits==(0 if failure else 1)
    assert not store.list('deliveries')
    if not failure:
        lead=store.list('leads')[0];assert lead['status']=='review'
        evidence=json.loads(lead['evidence'])
        assert evidence['company_url']==SOURCE
        assert evidence['company_criteria_quotes']==['Batch: Summer 2024.']
        # Assert the full durable run, not the UI’s rolling 80-event window.
        with store.db() as db:
            events=[dict(row) for row in db.execute('SELECT * FROM research_events ORDER BY id')]
        kinds=[x['kind'] for x in events]
        assert kinds.index('web_source')<kinds.index('visiting')<kinds.index('staged_for_review')

@pytest.mark.parametrize('url',['http://example.org','https://user:pass@example.org','https://example.org:8443','https://localhost/'])
def test_public_sources_reject_unsafe_destinations(monkeypatch,url):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):web.public_address(url)


def test_web_tools_are_opt_in_and_logged_without_enabling_actions(tmp_path):
    class SearchAuth(Auth):
        def _rpc(self,method,params):
            if method=='turn/start':
                self.events.put({'method':'item/completed','params':{'threadId':'fixture-thread',
                    'item':{'type':'webSearch','query':'company','action':{'type':'search'}}}})
            return super()._rpc(method,params)
    events=[];auth=SearchAuth(tmp_path)
    assert reason(auth,'Task',{}, {'type':'object'},web=True,on_search=events.append)=={'answer':'fixture'}
    config=auth.calls[0][1]['config']
    assert config['web_search']=='live' and config['features.shell_tool'] is False
    assert config['permissions.workbench-research']['network']['enabled'] is False
    assert events[0]['query']=='company'
    with pytest.raises(ProviderError,match='unsupported'):
        reason(SearchAuth(tmp_path),'Task',{}, {'type':'object'})


def test_web_mode_cannot_succeed_without_a_search(tmp_path):
    with pytest.raises(ProviderError,match='did not execute web search'):
        reason(Auth(tmp_path),'Task',{}, {'type':'object'},web=True)


def test_source_rate_limit_stops_and_redirect_revalidates(monkeypatch):
    class Connection:
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return self
        def getheader(self,key,default=''):return 'https://localhost/private' if key=='Location' else default
        def close(self):pass
        status=429
    monkeypatch.setattr(web,'PinnedHTTPS',Connection)
    calls=[]
    def address(url):
        calls.append(url)
        if 'localhost' in url:raise ValueError('private')
        from urllib.parse import urlsplit
        return urlsplit(url),'1.1.1.1'
    monkeypatch.setattr(web,'public_address',address)
    with pytest.raises(ProviderError,match='429'):web.fetch_source(SOURCE)
    Connection.status=302
    with pytest.raises(ValueError,match='private'):web.fetch_source(SOURCE)
    assert calls[-1]=='https://localhost/private'


def test_yc_structured_evidence_captures_only_public_company_fields(monkeypatch):
    import html
    from urllib.parse import urlsplit
    payload={'component':'ycdc_new/pages/Companies/ShowPage','props':{'company':{
        'name':'Fictional Roads','batch':'S24','batch_name':'Summer 2024',
        'long_description':'Agent monitoring','logo_url':'DO_NOT_CAPTURE',
        'founders':[{'full_name':'Fictional Person','title':'Founder','linkedin_url':PROFILE}]}}}
    body=('<title>Fictional Roads</title><div data-page="'+html.escape(json.dumps(payload),quote=True)+'"></div>').encode()
    class Connection:
        status=200
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return self
        def getheader(self,*args):return 'text/html'
        def read(self,*args):return body
        def close(self):pass
    monkeypatch.setattr(web,'PinnedHTTPS',Connection)
    monkeypatch.setattr(web,'public_address',lambda u:(urlsplit(u),'1.1.1.1'))
    page=web.fetch_source(SOURCE)
    assert 'batch: S24' in page['text'] and 'Agent monitoring' in page['text']
    assert PROFILE in page['links'] and 'DO_NOT_CAPTURE' not in page['text']
    assert 'batch: S24' not in web.fetch_source('https://example.org')['text']


def test_yc_jobs_resolves_to_company_overview(monkeypatch):
    from urllib.parse import urlsplit
    urls=[]
    def address(url):
        urls.append(url)
        raise ValueError('fixture stops before network')
    monkeypatch.setattr(web,'public_address',address)
    with pytest.raises(ValueError):web.fetch_source(SOURCE+'/jobs/a-job')
    assert urls==[SOURCE]
    with pytest.raises(ValueError):web.fetch_source('https://example.org/companies/example/jobs')
    assert urls[-1]=='https://example.org/companies/example/jobs'


def test_yc_industry_listing_is_not_company_evidence(monkeypatch):
    monkeypatch.setattr(web,'public_address',lambda url:(_ for _ in ()).throw(AssertionError('Should reject before fetching')))
    with pytest.raises(ValueError,match='individual company'):
        web.fetch_source('https://www.ycombinator.com/companies/industry/cloud-computing')
