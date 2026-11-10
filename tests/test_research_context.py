import json
from types import SimpleNamespace
import httpx
import pytest
from workbench.jev import JevAdvisor
from workbench.errors import ProviderError
from workbench.research import Discovery
from workbench.research_context import asset
from workbench.research_web import PageText, jev_company_fit
from workbench.store import Store


def test_archive_survives_history_clear_and_deduplicates_assets(tmp_path):
    store=Store(tmp_path);engine=Discovery(store,None,None)
    engine.context('run','web_page',{'text':'Captured evidence','metadata':{'batch':'S24'}})
    image=asset(store,b'fixture-png');assert asset(store,b'fixture-png')==image
    engine.clear_history()
    with store.db() as db:
        assert json.loads(db.execute('SELECT payload FROM research_context').fetchone()[0])['metadata']['batch']=='S24'
        assert db.execute('SELECT count(*) FROM research_assets').fetchone()[0]==1


def test_metadata_parser_keeps_jsonld_out_of_visible_quotes():
    p=PageText();p.feed('<meta property="og:title" content="Company"><link rel="canonical" href="https://example.org"><script type="application/ld+json">{"name":"Org"}</script><p>Visible source</p>')
    assert p.metadata['og:title']=='Company' and p.jsonld==[{'name':'Org'}]
    assert 'Org' not in ' '.join(p.parts)


def test_jev_image_payload_and_archive_redaction():
    def handle(req):
        body=json.loads(req.content);ref=body['state']['page_image']
        assert body['assets'][ref]['data_base64'] and req.headers['TypeSafe-Danger-Zone-Images']=='true'
        return httpx.Response(200,json={'model':'jev-test','answers':{'visible':{'type':'noul','noul':.98}}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result=JevAdvisor('private-key',client).research_questions({}, {'visible':{'type':'noul','instructions':'Visible?'}},image=b'png-fixture')
    encoded=json.dumps(result)
    assert 'data_base64' not in encoded and 'private-key' not in encoded
    assert result['request']['assets']

@pytest.mark.parametrize('status,payload',[(429,{}),(200,{'answers':{'x':{'type':'noul','noul':1.5}}})])
def test_jev_failed_research_does_not_retry(status,payload):
    calls=[]
    def handle(req):calls.append(req);return httpx.Response(status,json=payload)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError):JevAdvisor('fixture',client).research_questions({}, {'x':{'type':'noul'}})
    assert len(calls)==1


def test_company_quotes_are_observed_and_uncertainty_falls_back():
    captured=[]
    def ask(state,questions):
        choices=questions['batch_quote']['criteria']
        assert 'invented' not in choices.values()
        def choice(index):return {'type':'choice','choice':str(index),'confidence':.99,'probabilities':{k:float(k==str(index)) for k in choices}}
        return {'answers':{'eligible':{'noul':.99},'batch_quote':choice(0),'product_quote':choice(1)}}
    engine=SimpleNamespace(jev_advisor=lambda:SimpleNamespace(research_questions=ask),event=lambda *a:None,context=lambda *a:captured.append(a))
    page={'url':'https://example.org','text':'Batch: S24. AI agent sandboxes.','evidence_spans':['Batch: S24.','AI agent sandboxes.','invented']}
    fit=jev_company_fit(engine,{'prompt':'S24 sandbox'},'r',page)
    assert fit.qualified and fit.quotes==['Batch: S24.','AI agent sandboxes.'] and captured
    engine.jev_advisor=lambda:None
    assert jev_company_fit(engine,{'prompt':'S24'},'r',page) is None


def test_image_fallback_only_for_sparse_capture(tmp_path):
    engine=Discovery(Store(tmp_path),None,SimpleNamespace(evidence_image=lambda url:b'png'))
    calls=[]
    def ask(state,questions,image):calls.append(image);return {'answers':{'readable':{'noul':1}}}
    engine.jev_advisor=lambda:SimpleNamespace(research_questions=ask)
    full={'url':'https://www.linkedin.com/in/fixture/','headline':'Founder','text':'x'*400}
    engine.inspect_profile_image({'prompt':'Founder'},'r',full);assert not calls
    sparse={**full,'headline':''}
    engine.inspect_profile_image({'prompt':'Founder'},'r',sparse)
    assert calls==[b'png'] and sparse['visual_metadata']
    assert sparse['headline']==''  # visual inference never manufactures role quotes


def test_context_and_images_are_authenticated_and_scoped(tmp_path):
    from fastapi.testclient import TestClient
    from workbench.app import create_app
    from workbench.config import Settings
    from workbench.research_context import capture
    app=create_app(Settings(tmp_path,'x'*32,'demo','',10,'',''))
    store=app.state.store
    capture(store,'a','web_page',{'text':'source a'})
    capture(store,'b','web_page',{'text':'source b'})
    image=asset(store,b'fixture-png')
    with TestClient(app) as c:
        assert c.get('/api/discovery/context?run_id=a').status_code==401
        assert c.get('/api/discovery/assets/'+image).status_code==401
        c.headers['Authorization']='Bearer '+'x'*32
        records=c.get('/api/discovery/context?run_id=a').json()['records']
        assert len(records)==1 and records[0]['payload']['text']=='source a'
        assert c.get('/api/discovery/assets/'+image).content==b'fixture-png'
        assert c.get('/api/discovery/assets/missing').status_code==404
