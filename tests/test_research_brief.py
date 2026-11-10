import pytest
pytestmark = pytest.mark.usefixtures("fixture_web")
import pytest
from workbench.errors import ProviderError
from workbench.research import Discovery
from workbench.store import Store


def test_conversation_persists_context_and_invalidates_old_plan(tmp_path):
    calls=[]
    def model(auth,task,data,schema,stop):
        calls.append(data)
        return {'reply':'Which company stage should we focus on?',
                'brief':'Finance and risk leaders at Mexican concessions. Stage: unresolved.'}
    store=Store(tmp_path);engine=Discovery(store,None,None,model=model)
    store.setting('research_plan',{'id':'old'})
    engine.refine('Finance leaders in Mexico')
    assert engine.state()['plan'] is False
    engine.refine('Include risk managers too', 'Finance leaders at Mexican concessions')
    assert len(calls[1]['messages'])==3
    assert calls[1]['working_brief']=='Finance leaders at Mexican concessions'
    assert calls[1]['messages'][0]['content']=='Finance leaders in Mexico'
    assert len(engine.state()['conversation']['messages'])==4
    reopened=Discovery(Store(tmp_path),None,None,model=model)
    assert reopened.state()['conversation']==engine.state()['conversation']
    assert store.list('leads')==[] and store.list('deliveries')==[]
    with pytest.raises(ProviderError,match='new research plan'):
        engine.run('old',True)
    engine.reset_brief()
    assert engine.state()['conversation']['messages']==[]
    assert engine.state()['plan'] is False


def test_model_failure_preserves_user_message_without_stale_plan(tmp_path):
    def fail(*args):raise ProviderError('Model temporarily unavailable')
    engine=Discovery(Store(tmp_path),None,None,model=fail)
    engine.store.setting('research_plan',{'id':'old'})
    with pytest.raises(ProviderError,match='unavailable'):
        engine.refine('Only Colombia', 'Finance leaders in Latin America')
    state=engine.state()
    assert state['plan'] is False
    assert state['conversation']['messages']==[{'role':'user','content':'Only Colombia'}]
    assert state['conversation']['brief']=='Finance leaders in Latin America'


def test_brief_api_uses_authenticated_job_without_browser(tmp_path,monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from workbench.app import create_app
    from workbench.config import Settings
    class Auth:
        def __init__(self,*args):pass
        def status(self):return {'signed_in':True}
        def close(self):pass
    monkeypatch.setattr('workbench.app.CodexAuth',Auth)
    def model(*args):return {'reply':'Which country?','brief':'Finance directors. Geography unresolved.'}
    monkeypatch.setattr('workbench.app.Discovery',lambda store,auth,browser,jev:Discovery(store,auth,None,model=model))
    with TestClient(create_app(Settings(tmp_path,'x'*32,'live','',10,'',''))) as client:
        assert client.post('/api/discovery/brief',json={'message':'Find finance directors'}).status_code==401
        client.headers['Authorization']='Bearer '+'x'*32
        response=client.post('/api/discovery/brief',json={'message':'Find finance directors'})
        assert response.status_code==200
        for _ in range(100):
            if not client.get('/api/status').json()['busy']:break
            time.sleep(.01)
        state=client.get('/api/discovery/state').json()
        assert len(state['conversation']['messages'])==2
        assert client.get('/api/records/leads').json()==[]
        assert client.post('/api/discovery/brief/reset',json={}).status_code==200
        assert client.get('/api/discovery/state').json()['conversation']['messages']==[]


def test_run_emits_observable_decisions_and_saved_quote(tmp_path):
    from test_research import setup,PERSON
    store,browser,engine,plan=setup(tmp_path)
    engine.run(plan['id'],True)
    # Assert the full durable run, not the UI’s rolling 80-event window.
    with store.db() as db:
        events=[dict(row) for row in db.execute('SELECT * FROM research_events ORDER BY id')]
    kinds=[event['kind'] for event in events]
    assert kinds.index('checking_browser')<kinds.index('web_worker_started')<kinds.index('visiting')
    assert kinds.index('employer_selected')<kinds.index('qualifying')<kinds.index('staged_for_review')
    import json
    saved=json.loads(next(e['detail'] for e in events if e['kind']=='staged_for_review'))
    assert saved['role_quote']==PERSON['current_role_quote']
    assert saved['company_url'].startswith('https://www.linkedin.com/company/')
