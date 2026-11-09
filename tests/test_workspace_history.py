from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings
from workbench.store import Store
from workbench.research import Discovery
from test_research import Browser,PERSON,PROFILE,model


def test_history_committed_changes_and_restart(tmp_path):
    store=Store(tmp_path / "demo")
    store.add_lead({**PERSON,'url':PROFILE,'evidence':'fixture'})
    lead=store.list('leads')[0];ident=lead['id']
    store.approve(ident,'Hello, I would like to connect.')
    store.reserve(ident,10)
    store.invitation_audit(ident,'profile_identity',False,{})
    store.invitation_audit(ident,'custom_note_limit',False,{})
    store.delivery(ident,'blocked','No free custom notes remain')
    with store.db() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM workspace_changes')]
    assert [(r['before_state'],r['after_state']) for r in rows if r['kind']=='crm_status']==[('review','approved'),('approved','blocked')]
    assert rows[-1]['detail']=='No free custom notes remain'
    assert any(r['kind']=='invitation' and r['after_state']=='custom_note_limit' for r in rows)
    Store(tmp_path / "demo")
    with store.db() as db:assert db.execute('SELECT count(*) FROM workspace_changes').fetchone()[0]==len(rows)
    with TestClient(create_app(Settings(tmp_path,'x'*32,'demo','',10,'',''))) as client:
        assert client.get('/api/crm/history').status_code==401
        client.headers['Authorization']='Bearer '+'x'*32
        data=client.get('/api/crm/history').json()
        assert data[0]['after_state']=='blocked'
        contact=client.get('/api/records/leads').json()[0]
        assert not contact['outreach_available']
        assert contact['availability_reason']=='No free custom notes remain'


def test_research_assessments_are_visible_before_run_finishes(tmp_path):
    store=Store(tmp_path);engine=Discovery(store,None,Browser(),model=model)
    engine.remember(PROFILE,'reserved',{},'test-run','Finance leaders')
    with store.db() as db:
        assert db.execute('SELECT after_state FROM workspace_changes ORDER BY id DESC').fetchone()[0]=='visit_interrupted'
    engine.remember(PROFILE,'insufficient_evidence',{'assessment':{'needs_web_evidence':True,'reason':'Missing current role'}},'test-run','Finance leaders')
    with store.db() as db:
        row=db.execute('SELECT * FROM workspace_changes ORDER BY id DESC').fetchone()
        assert row['before_state']=='visit_interrupted' and row['after_state']=='missing_evidence'
        assert row['detail']=='Missing current role'
