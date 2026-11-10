import json
import sqlite3
from workbench.store import Store
from workbench.research import Discovery
from test_research import PERSON,PROFILE,COMPANY,Browser,model
from workbench import crm


def test_migration_backup_idempotent_and_delivery_protection(tmp_path):
    # A genuine pre-migration database, including a receipt that must never be resent.
    path=tmp_path/'workbench.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE leads(id TEXT PRIMARY KEY,profile_key TEXT UNIQUE,name TEXT,company TEXT,role TEXT,url TEXT,country TEXT,evidence TEXT,status TEXT,note TEXT,created TEXT);
        CREATE TABLE deliveries(lead_id TEXT PRIMARY KEY,status TEXT,note TEXT,evidence TEXT,created TEXT);""")
        db.execute('INSERT INTO leads VALUES(?,?,?,?,?,?,?,?,?,?,?)',('old','fictional-finance',PERSON['name'],PERSON['company'],PERSON['role'],PROFILE,'Colombia','legacy evidence','confirmed','hello','2026-01-01'))
        db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',('old','confirmed','hello','receipt','2026-01-02'))
    store=Store(tmp_path)
    assert (tmp_path/'workbench.pre-crm-v1.sqlite').exists()
    with store.db() as db:
        assert db.execute('SELECT id FROM crm_people').fetchone()[0]=='old'
        assert db.execute('SELECT sender_account_id FROM crm_actions').fetchone()[0] is None
        assert db.execute('SELECT receipt FROM crm_actions').fetchone()[0]=='receipt'
    Store(tmp_path)
    with store.db() as db:assert db.execute('SELECT COUNT(*) FROM crm_people').fetchone()[0]==1
    import pytest
    with pytest.raises(ValueError):store.approve('old','another note')


def test_two_campaigns_keep_separate_assessments_and_evidence(tmp_path):
    store=Store(tmp_path);engine=Discovery(store,None,Browser(),model=model)
    record={'url':PROFILE,'name':PERSON['name'],'company':PERSON['company'],'role':PERSON['role'],'country':'Colombia','created':'2026-01-01','visited_at':'2026-01-01','visited':True,
        'run_id':'one','audience':'CFOs only','status':'not_applicable','reason':'Accounting role','evidence':json.dumps({'assessment':PERSON,'profile':{'url':PROFILE}})}
    with store.db() as db:
        crm.assessment(db,record)
        crm.assessment(db,{**record,'run_id':'two','audience':'Accounting leaders','status':'review','reason':'Current accounting role','visited_at':'2026-02-01'})
        assert db.execute('SELECT COUNT(*) FROM crm_people').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM crm_campaigns').fetchone()[0]==2
        assert {r[0] for r in db.execute('SELECT qualification FROM crm_assessments')}=={'qualified','not_applicable'}
        assert db.execute('SELECT COUNT(*) FROM crm_evidence').fetchone()[0]>=2
    engine.clear_history()
    with store.db() as db:assert db.execute('SELECT COUNT(*) FROM crm_assessments').fetchone()[0]==2


def test_actions_and_messages_update_without_changing_qualification(tmp_path):
    store=Store(tmp_path)
    store.add_lead({**PERSON,'url':PROFILE,'evidence':'source'})
    lead=store.list('leads')[0]
    store.setting('account',{'key':'sender-fixture'})
    store.approve(lead['id'],'Hi there')
    store.reserve(lead['id'],5)
    store.delivery(lead['id'],'confirmed','receipt')
    assert store.reply('message',lead['id'],'Hello','2026-11-10','thread')
    assert not store.reply('message',lead['id'],'Hello','2026-11-10','thread')
    with store.db() as db:
        assert db.execute('SELECT qualification FROM crm_assessments').fetchone()[0]=='qualified'
        assert db.execute('SELECT sender_account_id FROM crm_actions').fetchone()[0]=='sender-fixture'
        assert db.execute('SELECT COUNT(*) FROM crm_messages').fetchone()[0]==1
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_new_campaign_does_not_reuse_other_audience_evidence(tmp_path,fixture_web):
    from workbench.store import now
    store=Store(tmp_path);browser=Browser();engine=Discovery(store,None,browser,model=model)
    profile=browser.profile(PROFILE);company=browser.company(COMPANY)
    engine.remember(PROFILE,'insufficient_evidence',{'profile':profile,'company':company,'assessment':{**PERSON,'qualified':False}},'old','Only CEOs')
    plan=engine.prepare('Accounting directors',1)
    browser.profile=lambda _:(_ for _ in ()).throw(AssertionError('No repeat visit'))
    result=engine.run(plan['id'],True)
    assert result['staged']==0 and result['visited']==0 and not result.get('cached_assessments')
    with store.db() as db:
        assert db.execute('SELECT COUNT(DISTINCT campaign_id) FROM crm_assessments WHERE campaign_id IS NOT NULL').fetchone()[0]==1
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_restart_preserves_research_campaign_and_source_rows(tmp_path):
    store=Store(tmp_path);engine=Discovery(store,None,Browser(),model=model)
    engine.remember(PROFILE,'insufficient_evidence',{'profile':Browser().profile(PROFILE),'company':Browser().company(COMPANY),'assessment':{**PERSON,'qualified':False}},'old','Accounting directors')
    def counts():
        with store.db() as db:return [db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('crm_people','crm_campaigns','crm_assessments','crm_evidence')]
    before=counts()
    Discovery(Store(tmp_path),None,Browser(),model=model)
    assert counts()==before


def test_exclusion_blocks_reserved_send(tmp_path):
    import pytest
    from workbench.store import now
    store=Store(tmp_path);store.add_lead({**PERSON,'url':PROFILE,'evidence':'source'})
    lead=store.list('leads')[0];store.approve(lead['id'],'Hello')
    with store.db() as db:
        pid=db.execute('SELECT id FROM crm_people').fetchone()[0]
        db.execute('INSERT INTO crm_exclusions VALUES(?,?,?,?,?,?,?)',('stop',pid,None,'all','Do not contact',now(),None))
    with pytest.raises(ValueError,match='excluded'):store.reserve(lead['id'],5)
    assert not store.list('deliveries')


def test_campaign_report_uses_confirmed_sends_and_unique_people(tmp_path):
    store=Store(tmp_path);store.add_lead({**PERSON,'url':PROFILE,'evidence':'source'})
    lead=store.list('leads')[0]
    with store.db() as db:
        crm.assessment(db,{**lead,'run_id':'campaign-run','audience':'Accounting','status':'review','visited_at':'2026-11-09'})
        crm.sync_lead(db,lead['id'])
    store.approve(lead['id'],'Hello');store.reserve(lead['id'],5);store.delivery(lead['id'],'confirmed','receipt')
    store.reply('report-message',lead['id'],'Yes','2099-01-01','thread')
    with store.db() as db:
        result=crm.report(db)[0]
        assert result['researched']==1 and result['qualified']==1
        assert result['sent']==1 and result['replied_after_send']==1 and result['reply_rate']==1
        assert result['accepted'] is None and result['positive_replies'] is None


def test_approval_uses_selected_qualified_campaign_and_rejects_mismatch(tmp_path):
    import pytest
    store=Store(tmp_path);store.add_lead({**PERSON,'url':PROFILE,'evidence':'source'})
    lead=store.list('leads')[0]
    with store.db() as db:
        crm.assessment(db,{**lead,'run_id':'fit','audience':'Accounting','status':'review'})
        crm.assessment(db,{**lead,'run_id':'no-fit','audience':'CEOs','status':'not_applicable'})
    bad=crm.ident('campaign','CEOs');good=crm.ident('campaign','Accounting')
    with pytest.raises(ValueError,match='not qualified'):store.approve(lead['id'],'Hello',bad)
    assert store.get_lead(lead['id'])['status']=='review'
    store.approve(lead['id'],'Hello',good)
    with store.db() as db:assert db.execute('SELECT campaign_id FROM crm_actions').fetchone()[0]==good
