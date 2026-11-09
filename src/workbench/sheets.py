"""Optional snapshot export into exclusively owned workbook tabs.

RAW writes preserve literal message text. Stable record IDs and complete snapshots
make a retry idempotent: no blind append and no modification of pre-existing tabs.
"""
from urllib.parse import quote
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from .errors import ProviderError, check_response

HEADERS={
 'leads':['id','name','company','role','country','url','status','note','evidence','created'],
 'replies':['id','lead_id','body','received','thread','imported'],
 'deliveries':['lead_id','status','note','evidence','created'],
}
TABS={'leads':'Workbench Leads','replies':'Workbench Replies','deliveries':'Workbench Deliveries'}

class SheetsSync:
    def __init__(self,settings,store,client=None,google=None):
        self.settings=settings;self.store=store;self.client=client;self.google=google

    def sync(self):
        oauth = bool(self.google and self.google.status()['connected'])
        sheet_id = self.store.setting('oauth_sheet_id') if oauth else self.settings.sheet_id
        if not sheet_id or (not oauth and not self.settings.google_credentials):
            raise ProviderError('Connect Google and create your CRM spreadsheet, or configure a service account and workbook first.')
        client=self.client
        if client is None:
            try:
                creds=self.google.credentials() if oauth else service_account.Credentials.from_service_account_file(self.settings.google_credentials,
                    scopes=['https://www.googleapis.com/auth/spreadsheets'])
            except Exception:
                raise ProviderError('Cannot load Google credentials. Reconnect Google or check the service-account file.') from None
            client=AuthorizedSession(creds)
        base='https://sheets.googleapis.com/v4/spreadsheets/'+quote(sheet_id,safe='')
        owned=self.store.setting('sheets_owned_tabs') or {}
        binding=owned.get(sheet_id,{})
        try:
            metadata=check_response(client.get(base,params={'fields':'spreadsheetId,sheets.properties'},timeout=30),'Google Sheets')
            sheets={s['properties']['title']:s['properties'] for s in metadata.get('sheets',[])}
            for table,title in TABS.items():
                if title in sheets:
                    if binding.get(title)!=sheets[title]['sheetId']:
                        raise ProviderError(f'The destination already contains {title}, which this installation does not own. Use an empty workbook.')
                else:
                    # Reserve a stable ID before attempting creation. A timeout can be
                    # reconciled by the next metadata read, without duplicate sheets.
                    import secrets
                    tab_id=binding.get(title) or secrets.randbelow(2**30)+1
                    binding[title]=tab_id;owned[sheet_id]=binding
                    self.store.setting('sheets_owned_tabs',owned)
                    check_response(client.post(base+':batchUpdate',json={'requests':[{'addSheet':{'properties':{
                        'sheetId':tab_id,'title':title,'gridProperties':{'frozenRowCount':1}}}}]},timeout=30),'Google Sheets')
                    sheets[title]={'sheetId':tab_id,'gridProperties':{'rowCount':1000,'columnCount':26}}
            reports={}
            for table,title in TABS.items():
                headers=HEADERS[table]
                rows=[[str(row.get(k,'')) for k in headers] for row in self.store.list(table)]
                values=[headers]+rows
                props=sheets[title];grid=props.get('gridProperties',{})
                if len(values)>grid.get('rowCount',0):
                    check_response(client.post(base+':batchUpdate',json={'requests':[{'updateSheetProperties':{
                        'properties':{'sheetId':binding[title],'gridProperties':{'rowCount':len(values)}},'fields':'gridProperties.rowCount'}}]},timeout=30),'Google Sheets')
                end=chr(64+len(headers));area=f"'{title}'!A1:{end}{len(values)}"
                url=base+'/values/'+quote(area,safe='')
                check_response(client.put(url,params={'valueInputOption':'RAW'},json={'range':area,'majorDimension':'ROWS','values':values},timeout=30),'Google Sheets')
                result=check_response(client.get(url,timeout=30),'Google Sheets').get('values',[])
                padded=[r+['']*(len(headers)-len(r)) for r in result]
                if padded!=values:raise ProviderError(f'{title} readback differs. Local records are preserved; sync stopped.')
                reports[table]=len(rows)
            return {'verified_rows':reports,'spreadsheet_url':'https://docs.google.com/spreadsheets/d/'+sheet_id+'/edit'}
        finally:
            if self.client is None:
                client.close()
                if oauth:self.google.persist(creds)
