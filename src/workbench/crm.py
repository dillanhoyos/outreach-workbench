"""Normalized local CRM, with transactional compatibility for legacy delivery receipts."""
import hashlib
import json
import sqlite3
from pathlib import Path
from .store import now, profile_key


def ident(kind, value):
    return kind+'_'+hashlib.sha256(value.encode()).hexdigest()[:24]


def unpack(value):
    if isinstance(value,dict):return value
    try:
        result=json.loads(value or '{}')
        return result if isinstance(result,dict) else {}
    except (ValueError,TypeError):return {}


def backup(path):
    if not path.exists():return
    with sqlite3.connect(path) as source:
        if source.execute("SELECT 1 FROM sqlite_master WHERE name='crm_people'").fetchone():return
        destination=path.with_name('workbench.pre-crm-v1.sqlite')
        # SQLite backup includes committed WAL content; never overwrite the original backup.
        if not destination.exists():
            with sqlite3.connect(destination) as target:source.backup(target)
            destination.chmod(0o600)


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS crm_companies (
      id TEXT PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
      domain TEXT, url TEXT, country TEXT, sector_tags TEXT NOT NULL DEFAULT '[]',
      accelerator TEXT, batch TEXT, aliases TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS crm_people (
      id TEXT PRIMARY KEY, profile_key TEXT UNIQUE NOT NULL, url TEXT NOT NULL,
      name TEXT, country TEXT, first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      last_verified_at TEXT, company_id TEXT REFERENCES crm_companies(id), role TEXT,
      legacy_lead_id TEXT UNIQUE REFERENCES leads(id));
    CREATE TABLE IF NOT EXISTS crm_campaigns (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, brief TEXT NOT NULL, criteria TEXT NOT NULL,
      criteria_version INTEGER NOT NULL DEFAULT 1, exclusions TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS crm_runs (
      id TEXT PRIMARY KEY, campaign_id TEXT REFERENCES crm_campaigns(id), criteria_version INTEGER NOT NULL DEFAULT 1,
      target INTEGER, max_minutes INTEGER, max_profiles INTEGER, started_at TEXT NOT NULL,
      ended_at TEXT, stop_reason TEXT, counters TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS crm_assessments (
      id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES crm_people(id), campaign_id TEXT REFERENCES crm_campaigns(id),
      run_id TEXT, criteria_version INTEGER NOT NULL DEFAULT 1,
      qualification TEXT NOT NULL CHECK(qualification IN ('qualified','not_applicable','missing_evidence','excluded','unassessed','interrupted')),
      reason_code TEXT NOT NULL, explanation TEXT NOT NULL, checked_at TEXT NOT NULL, review_due_at TEXT,
      UNIQUE(person_id,run_id));
    CREATE TABLE IF NOT EXISTS crm_evidence (
      id TEXT PRIMARY KEY, person_id TEXT REFERENCES crm_people(id), company_id TEXT REFERENCES crm_companies(id),
      assessment_id TEXT REFERENCES crm_assessments(id), source_url TEXT, source_type TEXT NOT NULL,
      fact_type TEXT NOT NULL, quotation TEXT, captured_at TEXT NOT NULL, content_hash TEXT NOT NULL, snapshot TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS crm_employment (
      id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES crm_people(id), company_id TEXT REFERENCES crm_companies(id),
      role TEXT NOT NULL, function TEXT, seniority TEXT, state TEXT NOT NULL CHECK(state IN ('current','former','unknown')),
      observed_at TEXT NOT NULL, evidence_id TEXT REFERENCES crm_evidence(id));
    CREATE TABLE IF NOT EXISTS crm_actions (
      id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES crm_people(id), campaign_id TEXT REFERENCES crm_campaigns(id),
      sender_account_id TEXT, channel TEXT NOT NULL DEFAULT 'linkedin', action_type TEXT NOT NULL DEFAULT 'invitation',
      approval TEXT NOT NULL CHECK(approval IN ('review','approved')), delivery_status TEXT NOT NULL,
      note TEXT NOT NULL, scheduled_at TEXT, attempted_at TEXT, sent_at TEXT, idempotency_key TEXT UNIQUE NOT NULL, receipt TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS crm_conversations (
      id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES crm_people(id), sender_account_id TEXT,
      channel TEXT NOT NULL, external_thread_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS crm_messages (
      id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES crm_conversations(id), external_message_id TEXT UNIQUE NOT NULL,
      direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')), body TEXT NOT NULL,
      occurred_at TEXT NOT NULL, imported_at TEXT NOT NULL, classification TEXT);
    CREATE TABLE IF NOT EXISTS crm_exclusions (
      id TEXT PRIMARY KEY, person_id TEXT REFERENCES crm_people(id), company_id TEXT REFERENCES crm_companies(id),
      scope TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT,
      CHECK(person_id IS NOT NULL OR company_id IS NOT NULL));
    CREATE TABLE IF NOT EXISTS crm_visits (
      id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES crm_people(id), run_id TEXT NOT NULL,
      state TEXT NOT NULL, observed_at TEXT NOT NULL, evidence TEXT NOT NULL, UNIQUE(person_id,run_id));
    CREATE TABLE IF NOT EXISTS crm_run_events (
      id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS crm_assessment_campaign ON crm_assessments(campaign_id,qualification);
    CREATE INDEX IF NOT EXISTS crm_assessment_person ON crm_assessments(person_id,checked_at);
    ''')


def company(db,name,url=None):
    if not name or name in ('Company not confirmed','Unknown'):return None
    key=' '.join(name.casefold().split());cid=ident('company',key)
    db.execute('INSERT INTO crm_companies(id,identity_key,name,url) VALUES(?,?,?,?) ON CONFLICT(identity_key) DO UPDATE SET url=COALESCE(excluded.url,crm_companies.url)',(cid,key,name,url))
    return cid


def campaign(db,brief,plan=None,created=None):
    if not brief:return None
    cid=ident('campaign',brief.strip());p=plan or {}
    db.execute('INSERT OR IGNORE INTO crm_campaigns(id,name,brief,criteria,created_at) VALUES(?,?,?,?,?)',
        (cid,brief[:100],brief,json.dumps({'summary':p.get('summary'),'queries':p.get('queries',[]),'brief':brief}),created or now()))
    return cid


def person(db,record):
    key=profile_key(record['url']);existing=db.execute('SELECT id FROM crm_people WHERE profile_key=?',(key,)).fetchone()
    lead=db.execute('SELECT id FROM leads WHERE profile_key=?',(key,)).fetchone()
    pid=existing['id'] if existing else (lead['id'] if lead else ident('person',key))
    ev=unpack(record.get('evidence'));comp=ev.get('company') or {}
    cid=company(db,record.get('company'),comp.get('url') or ev.get('company_url'))
    name=record.get('name');name=None if name in ('Profile not captured','Unknown','') else name
    country=record.get('country') or None
    checked=record.get('visited_at') if record.get('visited') else ev.get('captured_at')
    db.execute('''INSERT INTO crm_people(id,profile_key,url,name,country,first_seen_at,updated_at,last_verified_at,company_id,role,legacy_lead_id)
      VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(profile_key) DO UPDATE SET
      name=COALESCE(excluded.name,crm_people.name),country=COALESCE(excluded.country,crm_people.country),
      updated_at=excluded.updated_at,last_verified_at=COALESCE(excluded.last_verified_at,crm_people.last_verified_at),
      company_id=COALESCE(excluded.company_id,crm_people.company_id),role=COALESCE(excluded.role,crm_people.role),
      legacy_lead_id=COALESCE(excluded.legacy_lead_id,crm_people.legacy_lead_id)''',
      (pid,key,record['url'],name,country,record.get('created') or now(),now(),checked,cid,record.get('role') or None,lead['id'] if lead else None))
    return pid,cid


def assessment(db,record,history=False):
    pid,cid=person(db,record);run=record.get('run_id') or 'legacy:'+pid
    cam=campaign(db,record.get('audience',''),created=record.get('created'))
    status=record.get('status');qualification={'review':'qualified','approved':'qualified','confirmed':'qualified','replied':'qualified','simulated':'qualified',
        'missing_evidence':'missing_evidence','not_applicable':'not_applicable','company_excluded':'excluded','visit_interrupted':'interrupted'}.get(status,'unassessed')
    aid=ident('assessment',pid+run);checked=record.get('assessed_at') or record.get('visited_at') or record.get('created') or now()
    db.execute('''INSERT INTO crm_assessments(id,person_id,campaign_id,run_id,qualification,reason_code,explanation,checked_at)
      VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET qualification=excluded.qualification,
      reason_code=excluded.reason_code,explanation=excluded.explanation,checked_at=excluded.checked_at''',
      (aid,pid,cam,run,qualification,record.get('visit_state') or status or 'legacy',record.get('reason') or 'Imported legacy record',checked))
    if history:return
    ev=unpack(record.get('evidence'));a=ev.get('assessment');a=a if isinstance(a,dict) else ev
    source=(ev.get('profile') or {}).get('url') or record['url']
    company_url=(ev.get('company') or {}).get('url') or ev.get('company_url')
    captured=record.get('visited_at') or ev.get('captured_at') or checked
    evidence_id=None
    for fact,url,quote in [('current_role',source,a.get('current_role_quote')),('location',source,a.get('location_quote')),('sector',company_url,a.get('sector_quote'))]:
        if not quote:continue
        source_page=ev.get('profile' if fact!='sector' else 'company')
        if isinstance(source_page,dict):
            source_text=' '.join(source_page.get('text','').split()).casefold()
            if ' '.join(quote.split()).casefold() not in source_text:continue
        digest=hashlib.sha256(json.dumps(ev,sort_keys=True).encode()).hexdigest()
        eid=ident('evidence',aid+fact+digest)
        db.execute('INSERT OR IGNORE INTO crm_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)',(eid,pid,cid,aid,url,'linkedin' if fact!='sector' else 'company',fact,quote,captured,digest,json.dumps(ev)))
        if fact=='current_role':evidence_id=eid
    # Preserve evidence even for incomplete visits and legacy free-text notes.
    snapshot=record.get('evidence') or '{}';digest=hashlib.sha256(snapshot.encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO crm_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident('evidence',aid+digest),pid,cid,aid,source,'research','snapshot',None,captured,digest,snapshot))
    for quote in (ev.get('company') or {}).get('company_criteria_quotes',ev.get('company_criteria_quotes',[])):
        digest=hashlib.sha256(quote.encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO crm_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident('evidence',aid+'criteria'+digest),pid,cid,aid,company_url,'company','company_criteria',quote,captured,digest,json.dumps(ev)))
    if record.get('role'):
        db.execute('INSERT OR IGNORE INTO crm_employment VALUES(?,?,?,?,?,?,?,?,?)',
            (ident('employment',aid+record['role']+(cid or '')),pid,cid,record['role'],None,None,'current' if qualification=='qualified' and evidence_id else 'unknown',checked,evidence_id))
    if record.get('run_id'):
        db.execute('INSERT INTO crm_visits VALUES(?,?,?,?,?,?) ON CONFLICT(person_id,run_id) DO UPDATE SET state=excluded.state,observed_at=excluded.observed_at,evidence=excluded.evidence',
            (ident('visit',pid+run),pid,run,record.get('visit_state') or status,checked,snapshot))


def sync_lead(db,lead_id,sender=None):
    row=db.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
    if not row:return
    r=dict(row);pid,_=person(db,r)
    if not db.execute('SELECT 1 FROM crm_assessments WHERE person_id=?',(pid,)).fetchone():assessment(db,{**r,'status':'review'})
    latest=db.execute('SELECT campaign_id FROM crm_assessments WHERE person_id=? AND campaign_id IS NOT NULL ORDER BY checked_at DESC LIMIT 1',(pid,)).fetchone()
    delivery=db.execute('SELECT * FROM deliveries WHERE lead_id=?',(lead_id,)).fetchone()
    old=db.execute('SELECT sender_account_id,sent_at FROM crm_actions WHERE id=?',(lead_id,)).fetchone()
    sender=sender or (old['sender_account_id'] if old else None)
    db.execute('''INSERT INTO crm_actions(id,person_id,campaign_id,sender_account_id,approval,delivery_status,note,attempted_at,sent_at,idempotency_key,receipt)
      VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET approval=excluded.approval,delivery_status=excluded.delivery_status,
      campaign_id=COALESCE(crm_actions.campaign_id,excluded.campaign_id),note=excluded.note,attempted_at=excluded.attempted_at,sent_at=excluded.sent_at,receipt=excluded.receipt,
      sender_account_id=COALESCE(crm_actions.sender_account_id,excluded.sender_account_id)''',
      (lead_id,pid,latest['campaign_id'] if latest else None,sender or (old['sender_account_id'] if old else None),
       'approved' if r['status']=='approved' or delivery else 'review',delivery['status'] if delivery else 'not_contacted',r['note'],
       delivery['created'] if delivery else None,old['sent_at'] if old else None,'legacy-invitation:'+lead_id,delivery['evidence'] if delivery else ''))
    for reply in db.execute('SELECT * FROM replies WHERE lead_id=?',(lead_id,)).fetchall():
        conversation=ident('conversation',pid+(sender or '')+reply['thread'])
        db.execute('INSERT OR IGNORE INTO crm_conversations VALUES(?,?,?,?,?)',(conversation,pid,sender,'linkedin',reply['thread']))
        db.execute('INSERT OR IGNORE INTO crm_messages VALUES(?,?,?,?,?,?,?,?)',(reply['id'],conversation,reply['id'],'inbound',reply['body'],reply['received'],reply['imported'],None))


def record_event(db,run,kind,detail,created):
    db.execute('INSERT INTO crm_run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)',(run,kind,json.dumps(detail),created))
    if kind=='started' and detail.get('plan'):
        p=detail['plan'];cam=campaign(db,p['prompt'],p,created)
        db.execute('INSERT OR IGNORE INTO crm_runs(id,campaign_id,target,max_minutes,max_profiles,started_at) VALUES(?,?,?,?,?,?)',(run,cam,p['limit'],p['max_minutes'],p['max_profiles'],created))
    elif kind=='finished':
        db.execute('UPDATE crm_runs SET ended_at=?,stop_reason=?,counters=? WHERE id=?',(created,detail.get('reason'),json.dumps(detail),run))


def backfill(db,research=False):
    marker='crm_v1_research_backfilled' if research else 'crm_v1_leads_backfilled'
    if db.execute('SELECT 1 FROM settings WHERE key=?',(marker,)).fetchone():return
    if research:
        for row in db.execute('SELECT * FROM research_events ORDER BY id').fetchall():record_event(db,row['run_id'],row['kind'],unpack(row['detail']),row['created'])
        for row in db.execute('SELECT record FROM crm_research_profiles').fetchall():
            r=unpack(row['record'])
            for h in r.get('research_history',[])[:-1]:assessment(db,{**r,**h,'evidence':'{}','visited':False},history=True)
            assessment(db,r)
    for row in db.execute('SELECT id FROM leads').fetchall():sync_lead(db,row['id'])
    for hold in db.execute('SELECT * FROM holds').fetchall():
        cid=company(db,hold['company'])
        db.execute('INSERT OR IGNORE INTO crm_exclusions VALUES(?,?,?,?,?,?,?)',(ident('hold',cid),None,cid,'all',hold['reason'],now(),None))
    db.execute('INSERT INTO settings VALUES(?,?)',(marker,'true'))


def enrich(db,records):
    for r in records:
        p=db.execute('SELECT * FROM crm_people WHERE profile_key=?',(r['profile_key'],)).fetchone()
        if not p:continue
        assessments=[dict(a) for a in db.execute('SELECT a.*,c.name campaign_name,c.brief FROM crm_assessments a LEFT JOIN crm_campaigns c ON c.id=a.campaign_id WHERE person_id=? ORDER BY checked_at DESC',(p['id'],))]
        latest=next((a for a in assessments if a['run_id']==r.get('run_id')),assessments[0] if assessments else {})
        action=db.execute('SELECT * FROM crm_actions WHERE person_id=? ORDER BY attempted_at DESC LIMIT 1',(p['id'],)).fetchone()
        r.update(person_id=p['id'],company_id=p['company_id'],qualification=latest.get('qualification','unassessed'),
            campaign_id=latest.get('campaign_id'),campaign=latest.get('campaign_name') or 'Unassigned',assessments=assessments,
            last_verified_at=p['last_verified_at'],outreach_status=action['delivery_status'] if action else 'not_contacted',
            approval=action['approval'] if action else 'review',last_contact_at=action['sent_at'] if action else None)
        r['messages']=[dict(x) for x in db.execute('SELECT m.* FROM crm_messages m JOIN crm_conversations c ON c.id=m.conversation_id WHERE c.person_id=? ORDER BY occurred_at DESC',(p['id'],))]
        r['last_reply_at']=next((m['occurred_at'] for m in r['messages'] if m['direction']=='inbound'),None)
        r['excluded']=excluded(db,p['id'],p['company_id'])
        held=db.execute('SELECT 1 FROM holds WHERE company=?',(r.get('company','').strip().casefold(),)).fetchone()
        receipt=db.execute('SELECT status,evidence FROM deliveries WHERE lead_id=?',(r['id'],)).fetchone()
        r['availability_reason']=(
            'Person or company is excluded' if r['excluded'] else
            'Company is on hold' if held else
            'Prior reply recorded' if r['last_reply_at'] else
            (receipt['evidence'] or receipt['status']) if receipt else
            'Research qualification required' if r['qualification']!='qualified' else '')
        r['outreach_available']=not r['availability_reason'] and not str(r['id']).startswith('visited:') and r.get('status') in ('review','approved')
        r['sources']=[dict(x) for x in db.execute('SELECT source_url,fact_type,quotation,captured_at FROM crm_evidence WHERE person_id=? AND quotation IS NOT NULL',(p['id'],))]
    return records


def report(db):
    """All-time campaign cohorts; never infer acceptance or positive sentiment."""
    result=[]
    for c in db.execute('SELECT id,name FROM crm_campaigns ORDER BY created_at DESC').fetchall():
        people=db.execute('SELECT COUNT(DISTINCT person_id) FROM crm_assessments WHERE campaign_id=?',(c['id'],)).fetchone()[0]
        qualified=db.execute("SELECT COUNT(DISTINCT person_id) FROM crm_assessments a WHERE campaign_id=? AND qualification='qualified' AND checked_at=(SELECT MAX(checked_at) FROM crm_assessments b WHERE b.person_id=a.person_id AND b.campaign_id=a.campaign_id)",(c['id'],)).fetchone()[0]
        attempted=db.execute('SELECT COUNT(DISTINCT person_id) FROM crm_actions WHERE campaign_id=? AND attempted_at IS NOT NULL',(c['id'],)).fetchone()[0]
        sent=db.execute("SELECT COUNT(DISTINCT person_id) FROM crm_actions WHERE campaign_id=? AND delivery_status='confirmed'",(c['id'],)).fetchone()[0]
        replied=db.execute("SELECT COUNT(DISTINCT a.person_id) FROM crm_actions a JOIN crm_conversations c ON c.person_id=a.person_id JOIN crm_messages m ON m.conversation_id=c.id WHERE a.campaign_id=? AND m.direction='inbound' AND a.sent_at IS NOT NULL AND m.occurred_at>=a.sent_at",(c['id'],)).fetchone()[0]
        result.append({**dict(c),'window':'all_time','researched':people,'qualified':qualified,'attempted':attempted,'sent':sent,'replied_after_send':replied,'reply_rate':replied/sent if sent else None,'accepted':None,'positive_replies':None})
    return result


def excluded(db,person_id=None,company_id=None):
    return bool(db.execute('SELECT 1 FROM crm_exclusions WHERE scope=? AND (person_id=? OR company_id=?) AND (expires_at IS NULL OR expires_at>?) LIMIT 1',('all',person_id,company_id,now())).fetchone())
