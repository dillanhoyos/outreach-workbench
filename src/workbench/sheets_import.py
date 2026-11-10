"""Read-only Google source, bounded previews, and explicit atomic local imports."""
import hashlib
import json
import re
import secrets
import time
import uuid
from urllib.parse import urlsplit,quote
from google.auth.transport.requests import AuthorizedSession
from .errors import ProviderError,check_response
from .store import profile_key,now

FIELDS=('name','url','company','role','country','status')
SAFE_STATUSES={'','new','not contacted','not_contacted','review','nuevo','sin contactar'}
HISTORY_STATUSES={'sent','pending','connected','replied','do not contact','do_not_contact','enviado','pendiente','conectado','respondido','no contactar'}
def sheet_id(value):
    value=value.strip()
    if value.startswith('https://'):
        try:
            url=urlsplit(value)
            port=url.port
        except ValueError:raise ProviderError('Paste a valid Google Sheets URL.') from None
        if url.hostname!='docs.google.com' or url.username or url.password or port not in (None,443):
            raise ProviderError('Paste a docs.google.com/spreadsheets URL.')
        match=re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]+)(?:/.*)?',url.path)
        value=match.group(1) if match else ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',value):raise ProviderError('Paste a valid Google Sheets URL or ID.')
    return value

class SheetsImport:
    def __init__(self,google,store):
        self.google=google;self.store=store;self.snapshots={}
    def account(self):
        saved=self.google.saved()
        if not saved.get('refresh_token'):raise ProviderError('Connect Google first.')
        return hashlib.sha256(saved['refresh_token'].encode()).hexdigest()
    def get(self,path,params=None):
        creds=self.google.credentials()
        try:
            with AuthorizedSession(creds) as client:
                response=client.get('https://sheets.googleapis.com/v4/spreadsheets/'+path,params=params,timeout=25)
                if response.status_code in (403,404):
                    self.google.persist(creds)
                    return None
                data=check_response(response,'Google Sheets')
            self.google.persist(creds)
            return data
        except ProviderError:raise
        except Exception:raise ProviderError('Could not read Google Sheets. Check the connection and try again.') from None
    def inspect(self,value):
        ident=sheet_id(value)
        data=self.get(ident,{'fields':'spreadsheetId,properties(title),sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))'})
        if data is None:return {'needs_picker':True,'sheet_id':ident,'message':'Grant this app access in Google Picker. You must already have access to the file.'}
        return {'needs_picker':False,'sheet_id':ident,'title':data['properties']['title'],
                'tabs':[s['properties'] for s in data.get('sheets',[]) if 'gridProperties' in s['properties']]}
    def rows(self,value,tab_id,header_row):
        ident=sheet_id(value);meta=self.inspect(ident)
        if meta['needs_picker']:raise ProviderError('Authorize the spreadsheet with Google Picker first.')
        tab=next((t for t in meta['tabs'] if t['sheetId']==tab_id),None)
        if not tab:raise ProviderError('Select an existing spreadsheet tab.')
        if not 1<=header_row<=100:raise ProviderError('Header row must be between 1 and 100.')
        # One extra row detects truncation; never silently import only part of a source.
        cell_range="'"+tab['title'].replace("'","''")+"'!A"+str(header_row)+":AX"+str(header_row+1001)
        data=self.get(ident+'/values/'+quote(cell_range,safe=''),{'valueRenderOption':'FORMATTED_VALUE'})
        if data is None:raise ProviderError('Spreadsheet access changed. Connect or authorize it again.')
        values=data.get('values',[])
        if len(values)>1001:raise ProviderError('This tab exceeds 1,000 data rows. Split it into smaller tabs before importing.')
        if not values or not any(values[0]):raise ProviderError('No header found at that row.')
        if tab.get('gridProperties',{}).get('columnCount',0)>50:
            # Extra blank columns are normal; only the displayed A:AX columns are supported.
            notice='Only columns A–AX are available for mapping.'
        else:notice=''
        token=secrets.token_urlsafe(24)
        self.snapshots={k:v for k,v in self.snapshots.items() if v['expires']>time.monotonic()}
        if len(self.snapshots)>=10:self.snapshots.pop(next(iter(self.snapshots)))
        self.snapshots[token]={'expires':time.monotonic()+900,'account':self.account(),'sheet_id':ident,'tab':tab['title'],
            'header_row':header_row,'headers':values[0],'rows':values[1:],'mapping':None,'committed':None}
        return {'snapshot_id':token,'headers':values[0],'sample':values[1:6],'row_count':len(values)-1,'notice':notice}
    def snapshot(self,token):
        snap=self.snapshots.get(token)
        if not snap or snap['expires']<time.monotonic():raise ProviderError('Preview expired. Load the tab again.')
        if snap['account']!=self.account():raise ProviderError('Google account changed. Load a fresh preview.')
        return snap
    def preview(self,token,mapping,history_ack):
        snap=self.snapshot(token)
        if snap['committed']:raise ProviderError('This preview has already been imported.')
        if set(mapping)-set(FIELDS) or any(type(i)!=int or i<0 or i>=len(snap['headers']) for i in mapping.values()):
            raise ProviderError('Choose valid columns for the mapping.')
        if not {'name','url'}<=set(mapping):raise ProviderError('Map Name and LinkedIn URL.')
        if len(set(mapping.values()))!=len(mapping):raise ProviderError('Use each column for only one field.')
        if 'status' not in mapping and not history_ack:raise ProviderError('Map outreach status, or confirm this source has no prior outreach history.')
        result=[];seen=set()
        with self.store.db() as db:
            known={r[0] for r in db.execute('SELECT profile_key FROM crm_people')}
        for number,row in enumerate(snap['rows'],snap['header_row']+1):
            if not any(str(v).strip() for v in row):continue
            values={k:str(row[i]).strip() if i<len(row) else '' for k,i in mapping.items()}
            state=values.get('status','').casefold()
            reason='';key=None;valid=False
            try:
                if not values['name']:raise ValueError('Missing name')
                key=profile_key(values['url'])
                if state not in SAFE_STATUSES|HISTORY_STATUSES:raise ValueError('Unknown outreach status: map supported values before importing')
                if any(len(v)>1000 for v in values.values()):raise ValueError('Cell exceeds 1,000 characters')
                valid=True
                if key in seen:reason='Duplicate within this tab'
                elif key in known:reason='Already in CRM; existing record preserved'
                seen.add(key)
            except ValueError as exc:reason=str(exc)
            result.append({'row':number,'values':values,'key':key,'action':('history' if valid and state in HISTORY_STATUSES else 'skip') if reason else 'import',
                'reason':reason,'exclude':state in HISTORY_STATUSES})
        snap['mapping']=dict(mapping);snap['preview']=result
        return {'snapshot_id':token,'rows':result,'import_count':sum(r['action']=='import' for r in result),
                'skip_count':sum(r['action']=='skip' for r in result),
                'excluded_count':len({r['key'] for r in result if r['action']!='skip' and r['exclude']})}
    def commit(self,token,confirm):
        if not confirm:raise ProviderError('Confirm the import preview first.')
        snap=self.snapshot(token)
        if snap['committed'] is not None:return snap['committed']
        if snap['mapping'] is None:raise ProviderError('Preview the column mapping first.')
        added=skipped=excluded=0
        from . import crm
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in snap['preview']:
                if row['action']=='skip':
                    skipped+=1;continue
                existing=db.execute('SELECT id FROM crm_people WHERE profile_key=?',(row['key'],)).fetchone()
                if existing:
                    skipped+=1
                    if row['exclude'] and not db.execute("SELECT 1 FROM crm_exclusions WHERE person_id=? AND scope='all' AND expires_at IS NULL",(existing[0],)).fetchone():
                        db.execute('INSERT INTO crm_exclusions VALUES(?,?,?,?,?,?,?)',
                            (uuid.uuid4().hex,existing[0],None,'all','Imported outreach history: '+row['values']['status'],now(),None))
                        excluded+=1
                    continue
                value=row['values'];ident=uuid.uuid4().hex;stamp=now()
                source='https://docs.google.com/spreadsheets/d/'+snap['sheet_id']+'/edit'
                evidence=json.dumps({'source_url':source,'tab':snap['tab'],'row':row['row'],'imported_at':stamp,'source_status':value.get('status','')})
                record={'id':ident,'name':value['name'],'url':value['url'],'company':value.get('company',''),'role':value.get('role',''),
                    'country':value.get('country',''),'evidence':evidence,'created':stamp,'status':'imported',
                    'run_id':'sheet:'+token,'audience':'Imported from '+snap['tab'],'reason':'Imported source; research qualification required'}
                db.execute('INSERT INTO leads(id,profile_key,name,company,role,url,country,evidence,created) VALUES(?,?,?,?,?,?,?,?,?)',
                    (ident,row['key'],record['name'],record['company'],record['role'],record['url'],record['country'],evidence,stamp))
                crm.assessment(db,record)
                crm.sync_lead(db,ident)
                if row['exclude']:
                    pid=db.execute('SELECT id FROM crm_people WHERE profile_key=?',(row['key'],)).fetchone()[0]
                    db.execute('INSERT INTO crm_exclusions VALUES(?,?,?,?,?,?,?)',
                        (uuid.uuid4().hex,pid,None,'all','Imported outreach history: '+value['status'],stamp,None))
                    excluded+=1
                added+=1
            db.execute('INSERT INTO workspace_changes(name,kind,after_state,detail,created) VALUES(?,?,?,?,?)',
                (snap['tab'],'sheets_import','imported',f'{added} added; {skipped} skipped; {excluded} excluded by source history',now()))
        snap['committed']={'added':added,'skipped':skipped,'excluded':excluded}
        return snap['committed']
