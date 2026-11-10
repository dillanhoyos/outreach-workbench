'use strict';
let sheetSnapshot=null,sheetMappingBusy=false,pickerLibrary=null;
const sheetFields={name:'Name *',url:'LinkedIn URL *',company:'Company',role:'Role / title',country:'Country',status:'Outreach status'};
function invalidateSheetPreview(){ $('google-preview-step').hidden=true;$('google-import-confirm').checked=false;$('google-import-commit').disabled=true; }
function resetSheetMapping(){sheetSnapshot=null;$('google-map-step').hidden=true;invalidateSheetPreview();}
function sheetTable(root,headers,rows){
  root.replaceChildren();const table=document.createElement('table'),head=table.createTHead().insertRow();
  for(const name of headers){const th=document.createElement('th');th.textContent=name;head.append(th);}
  const body=table.createTBody();
  for(const values of rows){const row=body.insertRow();for(const value of values)row.insertCell().textContent=String(value ?? '');}
  root.append(table);
}
function sheetsControls(){
  const disabled=sheetMappingBusy || !connections?.google?.connected || !workspace || workspace.busy;
  for(const b of $('google-import').querySelectorAll('button,input,select'))b.disabled=Boolean(disabled);
  $('google-import-commit').disabled=Boolean(disabled) || !$('google-import-confirm').checked || $('google-preview-step').hidden;
}
async function sheetsAction(fn){
  if(sheetMappingBusy)return;sheetMappingBusy=true;
  for(const b of $('google-import').querySelectorAll('button,input,select'))b.disabled=true;
  try{await fn();}catch(e){$('google-import-status').textContent=e.message;}
  finally{sheetMappingBusy=false;sheetsControls();}
}
async function inspectSheet(value){
  resetSheetMapping();$('google-tab-step').hidden=true;
  $('google-import-status').textContent='Checking spreadsheet access…';
  const data=await api('sheets/inspect',{value});
  if(data.needs_picker){$('google-import-status').textContent=data.message+' Click Choose in Google Drive to authorize it.';return;}
  $('google-import-url').value='https://docs.google.com/spreadsheets/d/'+data.sheet_id+'/edit';
  $('google-import-tab').replaceChildren(...data.tabs.map(t=>new Option(t.title,String(t.sheetId))));
  $('google-tab-step').hidden=false;
  $('google-import-status').textContent=data.title+' · select a tab. The spreadsheet will not be modified.';
}
function loadPickerLibrary(){
  if(pickerLibrary)return pickerLibrary;
  pickerLibrary=new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src='https://apis.google.com/js/api.js';
    script.onerror=()=>reject(Error('Google Picker could not load. Check your network and try again.'));
    script.onload=()=>gapi.load('picker',{callback:resolve,onerror:()=>reject(Error('Google Picker failed to initialize.')),timeout:15000,ontimeout:()=>reject(Error('Google Picker timed out.'))});
    document.head.append(script);
  }).catch(e=>{pickerLibrary=null;throw e;});return pickerLibrary;
}
$('google-picker').onclick=()=>sheetsAction(async()=>{
  await loadPickerLibrary();
  const config=await api('connections/google/picker');
  const view=new google.picker.DocsView(google.picker.ViewId.SPREADSHEETS);
  try {
    const url=new URL($('google-import-url').value);
    const parts=url.pathname.split('/');
    if(url.hostname==='docs.google.com' && parts[1]==='spreadsheets' && parts[2]==='d')view.setFileIds(parts[3]);
  } catch (_) { /* An empty URL opens the general spreadsheet picker. */ }
  await new Promise((resolve,reject)=>{
    let picker;
    const callback=async data=>{
      if(data.action===google.picker.Action.CANCEL){$('google-import-status').textContent='Picker cancelled. Nothing imported.';picker.dispose();resolve();}
      if(data.action===google.picker.Action.PICKED){
        try{const id=data.docs?.[0]?.id;if(!id)throw Error('No spreadsheet selected.');picker.dispose();await inspectSheet(id);resolve();}
        catch(e){reject(e);}
      }
    };
    picker=new google.picker.PickerBuilder().addView(view).setOAuthToken(config.access_token).setDeveloperKey(config.api_key)
      .setAppId(config.app_id).setOrigin(location.origin).setCallback(callback).build();
    config.access_token='';picker.setVisible(true);
  });
});
$('google-inspect').onclick=()=>sheetsAction(()=>inspectSheet($('google-import-url').value.trim()));
$('google-import-url').oninput=()=>{resetSheetMapping();$('google-tab-step').hidden=true;};
$('google-import-tab').onchange=resetSheetMapping;
$('google-header-row').oninput=resetSheetMapping;
$('google-load-rows').onclick=()=>sheetsAction(async()=>{
  resetSheetMapping();
  const data=await api('sheets/rows',{value:$('google-import-url').value,tab_id:Number($('google-import-tab').value),header_row:Number($('google-header-row').value)});
  sheetSnapshot=data.snapshot_id;
  const root=$('google-column-mapping');root.replaceChildren();
  const aliases={name:['name','nombre','full name'],url:['linkedin','linkedin url','profile url','url'],company:['company','empresa'],role:['role','title','cargo'],country:['country','pais','país'],status:['status','outreach status','estado']};
  for(const [field,title] of Object.entries(sheetFields)){
    const label=document.createElement('label');label.textContent=title;const select=document.createElement('select');select.dataset.field=field;
    select.add(new Option('Not mapped',''));
    data.headers.forEach((text,i)=>select.add(new Option((i+1)+': '+(text || '(blank header)'),String(i))));
    const index=data.headers.findIndex(h=>aliases[field].includes(String(h).trim().toLowerCase()));
    if(index>=0)select.value=String(index);
    select.onchange=invalidateSheetPreview;label.append(select);root.append(label);
  }
  sheetTable($('google-row-sample'),data.headers,data.sample);
  $('google-history-ack').checked=false;$('google-map-step').hidden=false;
  $('google-import-status').textContent=data.row_count+' data rows loaded. '+data.notice+' Preview expires in 15 minutes.';
});
$('google-history-ack').onchange=invalidateSheetPreview;
$('google-preview').onclick=()=>sheetsAction(async()=>{
  const mapping={};
  for(const select of $('google-column-mapping').querySelectorAll('select'))if(select.value!=='')mapping[select.dataset.field]=Number(select.value);
  invalidateSheetPreview();
  const preview=await api('sheets/preview',{snapshot_id:sheetSnapshot,mapping,history_ack:$('google-history-ack').checked});
  $('google-preview-summary').textContent=preview.import_count+' new contacts · '+preview.skip_count+' skipped · '+preview.excluded_count+' excluded by prior outreach history.';
  sheetTable($('google-preview-rows'),['Row','Name','Action','Reason'],preview.rows.map(r=>[r.row,r.values.name,r.action,r.reason || (r.exclude?'Prior outreach: excluded from sending':'Needs research qualification')]));
  $('google-preview-step').hidden=false;
});
$('google-import-confirm').onchange=()=>{$('google-import-commit').disabled=!$('google-import-confirm').checked;};
$('google-import-commit').onclick=()=>sheetsAction(async()=>{
  const result=await api('sheets/import',{snapshot_id:sheetSnapshot,confirm:$('google-import-confirm').checked});
  resetSheetMapping();$('google-tab-step').hidden=true;
  $('google-import-status').textContent='Imported '+result.added+' contacts; '+result.skipped+' skipped; '+result.excluded+' excluded by prior history. Review them in CRM.';
  await refresh();
});

sheetsControls();
