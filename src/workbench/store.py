"""Durable records. Reserve an action before calling an external provider."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from urllib.parse import urlsplit, unquote


def now():
    return datetime.now(timezone.utc).isoformat()


def profile_key(url):
    u = urlsplit(url)
    host = u.hostname or ''
    if u.scheme != 'https' or u.username or u.password or u.port not in (None,443):
        raise ValueError('Use an HTTPS LinkedIn person profile URL')
    if host not in ('linkedin.com','www.linkedin.com') and not (len(host.split('.')[0])==2 and host.endswith('.linkedin.com')):
        raise ValueError('Expected a LinkedIn profile')
    parts = u.path.strip('/').split('/')
    if len(parts)!=2 or parts[0]!='in' or not parts[1]:
        raise ValueError('Expected /in/profile')
    return unquote(parts[1]).casefold()


class Store:
    def __init__(self, directory):
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=directory/'workbench.sqlite'
        from . import crm
        crm.backup(self.path)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS leads (
              id TEXT PRIMARY KEY, profile_key TEXT UNIQUE NOT NULL,
              name TEXT NOT NULL, company TEXT NOT NULL, role TEXT NOT NULL,
              url TEXT NOT NULL, country TEXT NOT NULL, evidence TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'review', note TEXT NOT NULL DEFAULT '',
              created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries (
              lead_id TEXT PRIMARY KEY REFERENCES leads(id), status TEXT NOT NULL,
              note TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS replies (
              id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
              body TEXT NOT NULL, received TEXT NOT NULL, thread TEXT NOT NULL,
              imported TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS holds (company TEXT PRIMARY KEY, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
              result TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            crm.initialize(db)
            # An interrupted action is uncertain, never automatically retryable.
            db.execute("UPDATE deliveries SET status='uncertain' WHERE status='sending'")
            db.execute("UPDATE jobs SET status='interrupted' WHERE status='running'")
            crm.backfill(db)
            for row in db.execute("SELECT lead_id FROM deliveries WHERE status='uncertain'").fetchall():crm.sync_lead(db,row[0])

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=20)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db: yield db
        finally: db.close()

    def add_lead(self, lead):
        key=profile_key(lead['url'])
        required=('name','company','role','url','country','evidence')
        if any(not isinstance(lead.get(k),str) or not lead[k].strip() for k in required):
            raise ValueError('Name, company, role, profile, country and source evidence are required')
        ident=uuid.uuid4().hex
        with self.db() as db:
            n=db.execute('INSERT OR IGNORE INTO leads(id,profile_key,name,company,role,url,country,evidence,created) VALUES(?,?,?,?,?,?,?,?,?)',
                (ident,key,*[lead[k].strip() for k in required],now())).rowcount
            from .crm import sync_lead
            if n:sync_lead(db,ident)
        return bool(n)

    def list(self, table):
        if table not in ('leads','deliveries','replies','holds','jobs'):raise ValueError('Unknown table')
        with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM '+table)]

    def get_lead(self, ident):
        with self.db() as db:r=db.execute('SELECT * FROM leads WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('Lead not found')
        return dict(r)

    def approve(self, ident, note, campaign_id=None):
        if not 1 <= len(note.strip().encode('utf-16-le'))//2 <= 200:raise ValueError('Invitation note must contain 1–200 characters')
        with self.db() as db:
            if db.execute('SELECT 1 FROM deliveries WHERE lead_id=?',(ident,)).fetchone():raise ValueError('An action already exists for this lead')
            if not db.execute("UPDATE leads SET status='approved',note=? WHERE id=?",(note.strip(),ident)).rowcount:raise ValueError('Lead not found')
            from .crm import sync_lead
            sync_lead(db,ident)
            if campaign_id:
                fit=db.execute('SELECT a.qualification FROM crm_assessments a JOIN crm_people p ON p.id=a.person_id WHERE p.legacy_lead_id=? AND a.campaign_id=? ORDER BY a.checked_at DESC LIMIT 1',(ident,campaign_id)).fetchone()
                if not fit or fit['qualification']!='qualified':raise ValueError('This person is not qualified for that campaign')
                db.execute('UPDATE crm_actions SET campaign_id=? WHERE id=?',(campaign_id,ident))

    def reserve(self, ident, limit, expected_note=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            lead=db.execute('SELECT * FROM leads WHERE id=?',(ident,)).fetchone()
            if not lead or lead['status']!='approved':raise ValueError('Review and approve this lead first')
            if expected_note is not None and lead['note']!=expected_note:raise ValueError('The approved note changed. Review it again before sending.')
            from .crm import excluded
            person=db.execute('SELECT id,company_id FROM crm_people WHERE legacy_lead_id=?',(ident,)).fetchone()
            if person and excluded(db,person['id'],person['company_id']):raise ValueError('Person or company is excluded')
            if db.execute('SELECT 1 FROM holds WHERE company=?',(lead['company'].casefold().strip(),)).fetchone():raise ValueError('Company is on hold')
            if db.execute('SELECT 1 FROM replies WHERE lead_id=?',(ident,)).fetchone():raise ValueError('This person has already replied')
            count=db.execute('SELECT count(*) FROM deliveries WHERE substr(created,1,10)=?',(now()[:10],)).fetchone()[0]
            if count>=limit:raise ValueError('Daily action limit reached (UTC)')
            try:db.execute("INSERT INTO deliveries(lead_id,status,note,created) VALUES(?,'sending',?,?)",(ident,lead['note'],now()))
            except sqlite3.IntegrityError:raise ValueError('Already attempted; inspect the existing receipt')
            from .crm import sync_lead
            account=db.execute("SELECT value FROM settings WHERE key='account'").fetchone()
            sender=json.loads(account[0]).get("key") if account else None
            sync_lead(db,ident,sender)
            return dict(lead)

    def delivery(self, ident, status, evidence):
        with self.db() as db:
            db.execute('UPDATE deliveries SET status=?,evidence=? WHERE lead_id=?',(status,evidence,ident))
            db.execute('UPDATE leads SET status=? WHERE id=?',(status,ident))
            from .crm import sync_lead
            sync_lead(db,ident)
            if status=='confirmed':db.execute('UPDATE crm_actions SET sent_at=COALESCE(sent_at,?) WHERE id=?',(now(),ident))

    def reply(self, ident, lead_id, body, received, thread):
        with self.db() as db:
            inserted=db.execute('INSERT OR IGNORE INTO replies VALUES(?,?,?,?,?,?)',(ident,lead_id,body,received,thread,now())).rowcount
            if inserted:db.execute("UPDATE leads SET status='replied' WHERE id=?",(lead_id,))
            from .crm import sync_lead
            sync_lead(db,lead_id)
        return bool(inserted)

    def setting(self,key,value=None):
        with self.db() as db:
            if value is not None:db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))
            r=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return json.loads(r[0]) if r else None
