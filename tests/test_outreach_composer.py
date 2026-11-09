import json
import time
import pytest
from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings
from workbench.outreach import Composer,units
from workbench.store import Store
from workbench.errors import ProviderError
from test_research import PERSON,PROFILE


def fixture(tmp_path):
    store=Store(tmp_path);store.add_lead({**PERSON,'url':PROFILE,'evidence':json.dumps({'current_role_quote':PERSON['current_role_quote']})})
    return store,store.list('leads')[0]


def test_drafts_grounded_and_edits_revoke_approval(tmp_path):
    store,lead=fixture(tmp_path)
    def model(*args):return {'suggestions':[{'note':'Hi Fictional, would you like to exchange ideas about accounting?','evidence_quote':PERSON['current_role_quote'],'rationale':'Supported role.'}],'reason':'Ready for review.'}
    composer=Composer(store,None,'live',model=model)
    composer.generate(lead['id'],'English, ask to exchange perspectives')
    assert not store.list('deliveries')
    note=composer.state(lead['id'])['draft']['result']['suggestions'][0]['note']
    store.approve(lead['id'],note)
    composer.save(lead['id'],'Hello, a revised invitation.','More concise')
    assert store.get_lead(lead['id'])['status']=='review'
    with pytest.raises(ValueError):store.reserve(lead['id'],5)
    store.approve(lead['id'],'Another note')
    with pytest.raises(ValueError,match='changed'):store.reserve(lead['id'],5,'outdated note')
    assert not store.list('deliveries')


@pytest.mark.parametrize('note,quote',[('😀'*101,PERSON['current_role_quote']),('Hi Fictional','invented quotation')])
def test_bad_generated_notes_are_not_saved(tmp_path,note,quote):
    store,lead=fixture(tmp_path)
    composer=Composer(store,None,'live',model=lambda *a:{'suggestions':[{'note':note,'evidence_quote':quote,'rationale':'Test'}],'reason':'Test'})
    with pytest.raises(ProviderError):composer.generate(lead['id'],'Write a note')
    assert composer.state(lead['id'])['draft'] is None
    assert not store.list('deliveries')


def test_demo_generate_edit_approve_send_receipt_no_duplicate(tmp_path):
    with TestClient(create_app(Settings(tmp_path,'x'*32,'demo','',10,'',''))) as api:
        api.headers['Authorization']='Bearer '+'x'*32
        def wait(response):
            assert response.status_code==200,response.text
            jid=response.json()['job_id']
            for _ in range(200):
                row=next(j for j in api.get('/api/records/jobs').json() if j['id']==jid)
                if row['status']!='running':return row
                time.sleep(.01)
            raise AssertionError('Job timeout')
        wait(api.post('/api/discover',json={'prompt':'Finance leads','limit':1}))
        lead=api.get('/api/records/leads').json()[0];root='/api/leads/'+lead['id']
        assert wait(api.post(root+'/draft',json={'instructions':'Friendly English, ask to connect'}))['status']=='completed'
        note='Hello, I would like to exchange ideas about finance operations.'
        assert api.post(root+'/draft/save',json={'note':note,'instructions':'Shorter'}).status_code==200
        assert api.post(root+'/approve',json={'note':note}).status_code==200
        assert api.post('/api/outreach',json={'lead_ids':[lead['id']],'expected_notes':{lead['id']:note}}).status_code==400
        assert wait(api.post('/api/outreach',json={'lead_ids':[lead['id']],'confirm':True,'expected_notes':{lead['id']:note}}))['status']=='completed'
        state=api.get(root+'/composer').json();assert state['receipt']['status']=='simulated'
        assert state['receipt']['note']==note
        assert api.post(root+'/draft/save',json={'note':'Try again'}).status_code==400
        assert wait(api.post('/api/outreach',json={'lead_ids':[lead['id']],'confirm':True,'expected_notes':{lead['id']:note}}))['status']=='failed'
        assert len(api.get('/api/records/deliveries').json())==1


def test_preview_checks_identity_and_supplies_source(tmp_path):
    from types import SimpleNamespace
    store,lead=fixture(tmp_path);composer=Composer(store,None,'live')
    bad=SimpleNamespace(profile=lambda url:{'title':'Wrong person','text':'Unrelated'})
    with pytest.raises(ProviderError,match='identity'):composer.preview(lead['id'],bad)
    assert composer.state(lead['id'])['previewed_at'] is None
    good=SimpleNamespace(profile=lambda url:{'title':PERSON['name'],'text':PERSON['current_role_quote'],'url':url})
    composer.preview(lead['id'],good)
    assert composer.state(lead['id'])['previewed_at']
    assert PERSON['current_role_quote'] in composer.context(lead['id'])[1]
    assert not store.list('deliveries')


def test_explicit_retry_preserves_receipt_and_counts_daily_limit(tmp_path):
    store,lead=fixture(tmp_path);ident=lead['id'];note='Hello, I would love to connect.'
    store.approve(ident,note);store.reserve(ident,5,note)
    store.invitation_audit(ident,'awaiting_confirmation',True,{'accepted':False})
    store.delivery(ident,'uncertain','First attempt timed out')
    original=store.list('deliveries')[0]
    with pytest.raises(ValueError):store.reserve(ident,5,note)
    with pytest.raises(ValueError):store.reserve(ident,5,'Changed note',original['created'])
    with pytest.raises(ValueError):store.reserve(ident,5,note,'stale')
    with pytest.raises(ValueError,match='Daily'):store.reserve(ident,1,note,original['created'])
    store.reserve(ident,5,note,original['created'])
    with store.db() as db:
        history=db.execute('SELECT * FROM outreach_attempt_history').fetchone()
        assert json.loads(history['receipt'])==original
        assert json.loads(history['audit'])['click_attempted']==1
    with pytest.raises(ValueError):store.reserve(ident,5,note,original['created'])
    store.delivery(ident,'uncertain','Second attempt timed out')
    second=store.list('deliveries')[0]
    with pytest.raises(ValueError,match='Daily'):store.reserve(ident,2,note,second['created'])
    store.delivery(ident,'confirmed','POST 200')
    with pytest.raises(ValueError):store.reserve(ident,5,note,second['created'])
