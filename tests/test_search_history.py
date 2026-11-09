import pytest
pytestmark = pytest.mark.usefixtures("fixture_web")
import json
import threading
import pytest
from workbench.research import Discovery
from workbench.store import Store,now,profile_key
from workbench.errors import ProviderError
from test_research import setup,model,PERSON,PROFILE


def test_clear_logs_keeps_crm_visit_memory_connections_and_recheck(tmp_path):
    def reject(*args):
        data=model(*args)
        if args[3]['title']=='Candidate':data.update(qualified=False,needs_web_evidence=False,reason='Wrong sector for this audience')
        return data
    store,browser,engine,plan=setup(tmp_path,reject)
    plan['profile_url']=PROFILE;store.setting('research_plan',plan)
    engine.run(plan['id'],True)
    record=engine.crm_records()[0]
    assert record['status']=='not_applicable' and record['visited']
    assert record['audience']==plan['prompt'] and record['reason']=='Wrong sector for this audience'
    for key,value in {'account':{'name':'Fixture'},'linkedin_restriction':{'reason':'Fixture limit'},'selenium_session':'session-fixture','research_conversation':{'brief':'keep'}}.items():store.setting(key,value)
    secret=tmp_path/'auth-fixture.json';secret.write_text('fictional private connection')
    before=engine.crm_records()
    engine.clear_history()
    assert engine.state()['report'] is None and engine.state()['events']==[]
    assert engine.crm_records()==before and secret.read_text()=='fictional private connection'
    assert store.setting('research_plan')==plan and store.setting('selenium_session')=='session-fixture'
    assert store.setting('linkedin_restriction')=={'reason':'Fixture limit'}
    assert engine.reserve(PROFILE,'after-reset')=='previously_visited_or_reserved'
    assert engine.fresh_links([{'url':PROFILE,'label':'Seen'}],plan,'after-reset')==[]
    engine.model=model
    plan=engine.prepare('New eligible audience',1,recheck_failed=True,profile_url=PROFILE)
    assert engine.run(plan['id'],True)['staged']==1
    records=engine.crm_records()
    assert len(records)==1 and records[0]['status']=='review'
    assert len(records[0]['research_history'])==2
    assert engine.reserve(PROFILE,'another',True)=='known_contact'
    engine.clear_history()
    assert len(engine.crm_records())==1


def test_clear_preserves_all_crm_tables_and_settings_and_blocks_active(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    store.add_lead({**PERSON,'url':PROFILE,'evidence':'fixture'})
    ident=store.list('leads')[0]['id']
    with store.db() as db:
        db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',(ident,'uncertain','note','proof',now()))
        db.execute('INSERT INTO replies VALUES(?,?,?,?,?,?)',('reply',ident,'hello',now(),'thread',now()))
        db.execute('INSERT INTO holds VALUES(?,?)',('Fixture Company','keep'))
        for kind in ('discovery','outreach','read','discovery-plan'):
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(kind,kind,'completed','{}',now()))
    original={t:store.list(t) for t in ('leads','replies','deliveries','holds')}
    engine.reserve('https://www.linkedin.com/in/history-fixture/','fixture')
    engine.event('fixture','started',{})
    store.setting('research_report',{'run_id':'fixture'})
    store.setting('research_active',True)
    with pytest.raises(ProviderError,match='Stop research'):engine.clear_history()
    assert engine.state()['events']
    store.setting('research_active',False)
    engine.clear_history()
    assert {t:store.list(t) for t in original}==original
    assert {j['kind'] for j in store.list('jobs')}=={'outreach','read','discovery-plan'}


def test_backfills_old_visit_into_crm_and_preserves_after_reset(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    engine.event('old','started',{'plan':plan})
    engine.reserve(PROFILE,'old')
    evidence={'profile':browser.profile(PROFILE),'assessment':{**PERSON,'qualified':False,'reason':'Old decision'}}
    with store.db() as db:db.execute('UPDATE research_visits SET state=?,evidence=?',('insufficient_evidence',json.dumps(evidence)))
    reopened=Discovery(store,None,browser)
    assert reopened.crm_records()[0]['audience']==plan['prompt']
    reopened.clear_history()
    assert len(Discovery(store,None,browser).crm_records())==1


def test_clear_api_auth_confirmation_and_busy_lock(tmp_path):
    from fastapi.testclient import TestClient
    from workbench.app import create_app
    from workbench.config import Settings
    from workbench.demo import DemoProvider
    entered=threading.Event();release=threading.Event()
    class BusyProvider(DemoProvider):
        def discover(self,*args):entered.set();release.wait(10);return []
    with TestClient(create_app(Settings(tmp_path,'x'*32,'demo','',10,'',''),provider=BusyProvider())) as client:
        path='/api/discovery/history/clear'
        assert client.post(path,json={'confirm':True}).status_code==401
        client.headers['Authorization']='Bearer '+'x'*32
        assert client.post(path,json={}).status_code==400
        assert client.post(path,json={'confirm':True}).status_code==200
        client.post('/api/discover',json={'prompt':'Fixture','limit':1})
        assert entered.wait(2)
        try:assert client.post(path,json={'confirm':True}).status_code==409
        finally:release.set()
