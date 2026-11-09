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
    def __init__(self,settings,store,client=None):
        self.settings=settings;self.store=store;self.client=client

    def sync(self):
        if not self.settings.sheet_id or not self.settings.google_credentials:
            raise ProviderError('Configure GOOGLE_SHEET_ID and a mounted Google service-account JSON file first.')
        client=self.client
        if client is None:
            try:
                creds=service_account.Credentials.from_service_account_file(self.settings.google_credentials,
                    scopes=['https://www.googleapis.com/auth/spreadsheets'])
            except Exception:
                raise ProviderError('Cannot load Google service-account credentials. Check the mounted file.') from None
            client=AuthorizedSession(creds)
        base='https://sheets.googleapis.com/v4/spreadsheets/'+quote(self.settings.sheet_id,safe='')
        owned=self.store.setting('sheets_owned_tabs') or {}
        binding=owned.get(self.settings.sheet_id,{})
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
                    sheet_id=binding.get(title) or secrets.randbelow(2**30)+1
                    binding[title]=sheet_id;owned[self.settings.sheet_id]=binding
                    self.store.setting('sheets_owned_tabs',owned)
                    check_response(client.post(base+':batchUpdate',json={'requests':[{'addSheet':{'properties':{
                        'sheetId':sheet_id,'title':title,'gridProperties':{'frozenRowCount':1}}}}]},timeout=30),'Google Sheets')
                    sheets[title]={'sheetId':sheet_id,'gridProperties':{'rowCount':1000,'columnCount':26}}
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
            return {'verified_rows':reports,'spreadsheet_url':'https://docs.google.com/spreadsheets/d/'+self.settings.sheet_id+'/edit'}
        finally:
            if self.client is None:client.close()
