'use strict';
let token = '', workspace = null, browserState = null, refreshing = false, browserChecking = false, connectionBusy = false, connections = null, researchState = null, researchJobId = null, researchSubmitting = false, researchRestored = false, researchSeenJobId = null, briefSubmitting = false, briefRevision = null, briefJobId = null, decisionRevision = null;
const $ = id => document.getElementById(id);
let latestReaderJob=null,readerSubmitting=false;
let researchViewOverride=null,researchViewKey=null,researchLatestJob=null;
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
async function api(path, body, method) {
  const response = await fetch('/api/' + path, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the entered values and try again.');
  return data;
}
async function run(fn) { try { error(''); await fn(); } catch (e) { error(e.message); } }
function controls() {
  if (typeof sheetsControls === 'function') sheetsControls();
  const connected = Boolean(workspace), idle = connected && !workspace.busy;
  for (const id of ['discover', 'refresh']) $(id).disabled = !idle;
  $('brief-send').disabled = !idle || briefSubmitting || workspace.mode !== 'live' || !(workspace.discovery.plan_ready ?? workspace.discovery.ready);
  $('clear-search-history').disabled = !idle || briefSubmitting;
  $('brief-reset').disabled = !idle || briefSubmitting;
  $('discovery-prompt').disabled = !idle || briefSubmitting;
  $('discover').disabled = !idle || !(workspace.discovery.plan_ready ?? workspace.discovery.ready);
  $('discovery-visits').disabled = !idle;
  $('discovery-minutes').disabled = !idle;
  $('research-adjust-time').disabled = !idle;
  $('research-adjust-time').textContent = 'Adjust limits · '+($('discovery-minutes').value || '15')+' min';
  const plan = researchState?.plan;
  const changed = Boolean(plan) && (plan.prompt !== $('discovery-prompt').value.trim() || plan.limit !== Number($('discovery-limit').value) || (plan.max_minutes ?? 15) !== Number($('discovery-minutes').value) || (plan.max_profiles ?? 0) !== Number($('discovery-visits').value) || Boolean(plan.recheck_failed) !== $('discovery-recheck').checked || (plan.profile_url || '') !== $('discovery-profile').value.trim());
  const blocked = !connected ? 'Connect your workspace first.'
    : researchSubmitting ? 'Starting research…'
    : workspace.busy ? 'Wait for the current job to finish.'
    : !plan ? 'Prepare a research plan first.'
    : !workspace.discovery.ready ? workspace.discovery.reason || 'Complete the research connections first.'
    : changed ? 'Your brief or limits changed. Prepare an updated plan before starting.'
    : !$('research-history').checked ? 'Confirm the CRM history checkbox above to continue.' : '';
  // Only local prerequisites disable submission. Server checks current auth,
  // account, restrictions and job ownership and returns the precise failure.
  $('research-start').disabled = !connected || researchSubmitting || workspace.busy || changed || !plan || !$('research-history').checked;
  $('research-start').textContent = plan ? 'Start reviewed plan (' + plan.limit + ')' : 'Start research';
  $('research-start-help').textContent = blocked || 'Ready. Start research will browse profiles and save candidates to your local CRM.';
  $('research-start-browser').hidden = !connected || workspace.mode !== 'live';
  $('research-use-plan').hidden = !changed;
  $('research-use-plan').disabled = !idle;
  $('research-stop').disabled = !connected || !workspace.busy;
  $('discover').hidden=Boolean(plan) && !changed && workspace?.mode==='live';
  $('sync').disabled = !idle || workspace.mode !== 'live' || !workspace.sheets_configured;
  $('check-browser').disabled = !connected || browserChecking;
  $('open-browser').disabled = !browserState?.available;
  $('login').disabled = !idle || workspace.mode !== 'live' || !browserState?.available || Boolean(workspace.linkedin_restriction);
  $('reset-browser').disabled = !idle || workspace.mode !== 'live';
  for (const id of ['codex-login', 'codex-key-save', 'codex-check', 'codex-logout', 'codex-cancel', 'jev-save', 'jev-check', 'jev-disconnect', 'google-login', 'google-disconnect', 'google-create', 'google-select']) $(id).disabled = !idle || connectionBusy;
  renderReader();
  renderResearchScreen();
  if (idle && !connectionBusy && connections) {
    $('codex-login').disabled = !connections.codex.available || connections.codex.signed_in || Boolean(connections.codex.pending);
    $('codex-key-save').disabled = !connections.codex.available || connections.codex.signed_in || Boolean(connections.codex.pending);
    $('codex-cancel').disabled = !connections.codex.pending;
    $('codex-check').disabled = !connections.codex.signed_in;
    $('codex-logout').disabled = !connections.codex.signed_in;
    $('jev-check').disabled = !connections.jev.configured;
    $('jev-disconnect').disabled = !connections.jev.configured;
    $('google-login').disabled = !connections.google.configured || connections.google.connected;
    $('google-disconnect').disabled = !connections.google.connected;
    $('google-select').disabled = !connections.google.connected;
    $('google-create').disabled = !connections.google.connected || workspace.mode !== 'live' || Boolean(workspace.google_sheet_id);
  }
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [status, leads, history, jobs, authState, discoveryState, reports] = await Promise.all(['status', 'records/leads', 'crm/history', 'records/jobs', 'connections', 'discovery/state','crm/report'].map(p => api(p)));
    connections = authState; researchState = discoveryState;
    workspace = status;
    latestReaderJob=jobs.filter(j=>j.kind==='reader').sort((a,b)=>b.created.localeCompare(a.created))[0] || null;
    $('mode').textContent = status.mode === 'demo' ? 'Demo · fictional data' : 'Live workspace';
    $('status').textContent = (status.busy ? 'A job is running. ' : 'Ready. ') + 'Daily action limit: ' + status.daily_limit + ' (UTC).';
    $('account-name').textContent = 'Account: see LinkedIn in the browser';
    $('account-note').textContent = 'Sign in here, then go straight to Research. No profile URL or separate verification needed.';
    $('restriction').hidden = !status.linkedin_restriction;
    $('restriction').textContent = status.linkedin_restriction ? 'LinkedIn reported a restriction. Actions are paused; review it in the browser.' : '';
    $('discover').textContent = status.mode === 'demo' ? 'Preview fictional leads' : 'Prepare research plan';
    $('discovery-state').textContent = status.mode === 'demo'
      ? 'Demo only: this previews a fixed set of fictional people. It does not interpret the prompt or search the web.'
      : status.discovery.reason || 'Ready: prepare a plan, review it, then start browser research. Candidates will be saved for review.';
    $('research-browser-help').hidden = status.mode !== 'live';
    if (status.mode === 'live' && status.discovery.plan_ready && !status.discovery.ready) $('discovery-state').textContent = 'You can prepare your plan now. ' + status.discovery.reason;
    const latestResearch = jobs.filter(job => job.kind === 'discovery').sort((a,b) => b.created.localeCompare(a.created))[0];
    researchLatestJob=latestResearch || null;
    if (!researchRestored || (latestResearch && latestResearch.id !== researchSeenJobId)) {
      researchJobId = latestResearch?.id || null;
      researchSeenJobId = researchJobId;
      researchRestored = true;
      if (latestResearch?.status === 'running') {
        $('research-activity').open = false;
        $('planning-conversation').open = false;
      }
    }
    if (researchJobId) {
      const launch = jobs.find(job => job.id === researchJobId);
      if (launch) $('research-launch-status').textContent = researchLaunchMessage(launch);
    }
    renderBrief(jobs);
    renderDecisions();
    renderConnections();
    $('research-plan').hidden = status.mode !== 'live' || !researchState.plan;
    if (researchState.plan) {
      $('plan-summary').textContent = researchState.plan.summary;
      $('plan-metrics').replaceChildren();
      for(const label of [researchState.plan.limit+' people',researchState.plan.max_minutes+' minutes',researchState.plan.max_profiles ? researchState.plan.max_profiles+' visits max' : 'No visit cap']) {const span=document.createElement('span');span.textContent=label;$('plan-metrics').append(span);}
    }
    if (researchState.plan) $('research-plan-text').textContent = 'Two web workers → one LinkedIn worker\n\n' + 'Recheck prior evidence failures: '+Boolean(researchState.plan.recheck_failed)+'\nSpecific profile: '+(researchState.plan.profile_url || 'None')+'\n\nYour brief: ' + researchState.plan.prompt + '\n\n' + researchState.plan.summary + '\n\nSearches:\n' + researchState.plan.queries.join('\n') + '\n\nTarget: ' + researchState.plan.limit + ' · Max profile visits: ' + (researchState.plan.max_profiles || 'Time limit only') + ' · Max minutes: ' + researchState.plan.max_minutes;
    $('research-progress').textContent = researchState.events.length ? researchState.events.slice(0,20).map(e => { const detail=JSON.parse(e.detail); return e.kind.replaceAll('_',' ') + ': ' + (detail.reason || detail.query || detail.url || (detail.staged !== undefined ? detail.staged + ' candidates saved for review' : 'Research started')); }).join('\n') : researchState.plan ? 'Your plan is prepared. Complete the step shown beside Start research.' : 'No research has started yet. Prepare a plan to begin.';
    $('sheets-state').textContent = status.sheets_configured ? 'Configured' : 'Optional';
    $('access-help').textContent = 'Workspace unlocked. Your password is held only in this tab’s memory.';
    crmReports=reports;crmRecords=leads;renderCrm(leads,status);
    renderHistory(history,jobs);renderRecipients();
    if(!$('batch-drafts').children.length && batchSelected.size)renderBatchDrafts();
    if(batchJobId && !batchBusy){
      const recovered=jobs.find(j=>j.id===batchJobId);
      if(recovered){
        batchBusy=true;batchControls();
        watchBatch(batchJobId).catch(e=>{$('batch-status').textContent=e.message;batchJobId=null;saveBatch();}).finally(()=>{batchBusy=false;batchControls();});
      }
    }

    const sending=leads.find(l=>l.outreach_status==='sending');
    if(sending){
      $('outreach-watch').hidden=false;$('outreach-watch-person').textContent='Invitation to '+sending.name;
      $('outreach-watch-note').textContent=sending.note;
      const stage=history.find(h=>h.lead_id===sending.id && h.kind==='invitation');
      $('outreach-watch-status').textContent=stage ? stage.after_state.replaceAll('_',' ') : 'Checking recipient…';
    }
    if(!composerRestored){
      composerRestored=true;
      let saved;try{saved=sessionStorage.getItem('workbench-recipient');}catch(_){}
      const previous=leads.find(l=>l.id===saved);
      if(previous && window.location.hash==='#compose' && !batchSelected.size)await openComposer(previous);
    }
    $('crm-total').textContent=leads.length;
    $('jobs').textContent = jobs.length ? jobs.slice().reverse().map(j => j.kind + ' · ' + j.status + ' · ' + j.created + '\n' + j.result).join('\n\n') : 'No jobs yet.';
    renderWorkspace();
    controls();
    if(composeState){const current=leads.find(l=>l.id===composeLead.id);if(current)composeLead=current;composerControls();}
  } finally { refreshing = false; }
}
async function checkBrowser() {
  if (browserChecking) return;
  browserChecking = true; controls(); $('browser-badge').textContent = 'Checking…';
  try {
    browserState = await api('browser/status');
    $('browser-badge').textContent = browserState.available ? 'Services reachable' : 'Browser offline';
    $('browser-message').textContent = browserState.message;
    if (browserState.available && workspace.mode === 'live') openViewer();
    $('browser-help').open = false;
    if (!browserState.available) { $('browser-frame').hidden = true; $('browser-frame').removeAttribute('src'); $('browser-empty').hidden = false; $('external-viewer').hidden = true; $('expand-browser').hidden = true; }
    if (workspace.mode === 'demo') $('login-progress').textContent = 'Demo mode: set WORKBENCH_MODE=live and start the browser to enable LinkedIn login. See setup below the viewer.';
  } catch (e) {
    browserState = null; $('browser-badge').textContent = 'Check failed'; $('browser-help').open = true; throw e;
  } finally { browserChecking = false; controls(); }
}
function openViewer() {
  if (!browserState?.available) throw Error('Check the browser connection first.');
  const url = new URL(window.location.href);
  url.port = String(browserState.viewer_port); url.pathname = '/vnc.html';
  url.search = '?autoconnect=1&resize=scale'; url.hash = '';
  // Credentials never go into the iframe URL; noVNC prompts for its own password.
  if ($('browser-frame').getAttribute('src') !== url.href) $('browser-frame').src = url.href;
  $('browser-frame').hidden = false; $('browser-empty').hidden = true;
  $('external-viewer').href = url.href; $('external-viewer').hidden = false; $('expand-browser').hidden = false;
}
async function browserJob(path, body, pending, success) {
  $('login-progress').textContent = pending;
  try {
    const result = await api(path, body);
    workspace.busy = true; controls();
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      const jobs = await api('records/jobs'); const job = jobs.find(j => j.id === result.job_id);
      if (job && job.status !== 'running') {
        const receipt = JSON.parse(job.result);
        if (job.status !== 'completed') throw Error(receipt.message || 'Browser action stopped. Review the browser and activity below.');
        $('login-progress').textContent = success;
        await refresh(); return;
      }
      await new Promise(resolve => setTimeout(resolve, 750));
    }
    throw Error('The browser is still working. Check Workspace activity before trying again.');
  } catch (e) { $('login-progress').textContent = e.message; throw e; }
  finally { await refresh(); }
}
$('access-form').onsubmit = event => { event.preventDefault(); run(async () => { token = $('token').value; $('token').value = ''; workspace = null; browserState = null; await refresh(); showView(window.location.hash.slice(1) || (workspace.mode === 'demo' || workspace.discovery.ready ? 'discovery' : 'connections')); await checkBrowser(); }); };
$('refresh').onclick = () => run(refresh);
$('expand-browser').onclick = () => run(async () => { await $('browser-stage').requestFullscreen(); });
$('check-browser').onclick = () => run(checkBrowser);
$('open-browser').onclick = () => run(async () => { await checkBrowser(); openViewer(); });
$('login').onclick = () => run(async () => { await checkBrowser(); openViewer(); await browserJob('linkedin/login', {}, 'Opening LinkedIn in your browser…', 'LinkedIn is open below. Sign in and complete any LinkedIn prompts, then return to Research.'); });
$('reset-browser').onclick = () => run(async () => { if (!confirm('Restart the browser container first. Reset its saved connection now? Cookies are preserved and invitations will not be retried.')) return; await browserJob('linkedin/reset', {}, 'Resetting the browser connection…', 'Connection reset. Open LinkedIn sign-in again.'); });
$('discover').onclick = () => run(async () => { const prompt = $('discovery-prompt').value.trim(); if (prompt.length < 2) throw Error('Describe the people you want to research first.'); const limit = Number($('discovery-limit').value); if (!Number.isInteger(limit) || limit < 1 || limit > 10) throw Error('Choose a target between 1 and 10.'); const max_profiles=Number($('discovery-visits').value); if (!Number.isInteger(max_profiles) || max_profiles < 0 || max_profiles > 500) throw Error('Choose a visit limit from 1 to 500, or 0 for time only.'); const max_minutes=Number($('discovery-minutes').value); if (!Number.isInteger(max_minutes) || max_minutes < 1 || max_minutes > 60) throw Error('Choose a time limit from 1 to 60 minutes.'); $('research-history').checked=false; await api(workspace.mode === 'demo' ? 'discover' : 'discovery/plan', { prompt, limit, max_minutes, max_profiles, web_first:true,recheck_failed:$('discovery-recheck').checked,profile_url:$('discovery-profile').value.trim() }); await refresh(); });

$('sync').onclick = () => run(async () => { await api('sheets/sync', {}); await refresh(); });
setInterval(() => { if (token && workspace) run(refresh); }, 1000);

function renderConnections() {
  const c = connections.codex, j = connections.jev, g = connections.google;
  $('google-message').textContent = g.connected ? 'Google connected. Paste a spreadsheet URL or choose a file below.' : g.message || 'Google is not connected.';
  $('google-open').hidden = !workspace.google_sheet_id;
  if (workspace.google_sheet_id) $('google-open').href = 'https://docs.google.com/spreadsheets/d/' + encodeURIComponent(workspace.google_sheet_id) + '/edit';
  $('codex-state').textContent = !c.available ? 'Unavailable' : c.signed_in ? 'Signed in' : c.pending ? 'Awaiting sign-in' : 'Not connected';
  $('codex-account').textContent = c.account ? (c.account.email || 'OpenAI API account') + (c.account.planType ? ' · ' + c.account.planType : '') : 'Sign in with your own ChatGPT account or connect an OpenAI API key.';
  $('codex-message').textContent = c.message || '';
  $('codex-device').hidden = !c.pending;
  if (c.pending) {
    const url = new URL(c.pending.verification_url);
    if (url.protocol !== 'https:' || url.hostname !== 'auth.openai.com' || url.username || url.password) throw Error('Unexpected Codex sign-in address.');
    $('codex-device-link').href = url.href;
    $('codex-device-code').textContent = c.pending.user_code;
  } else { $('codex-device-code').textContent = ''; $('codex-device-link').removeAttribute('href'); }
  $('jev-state').textContent = j.configured ? (j.checked_at ? 'Key checked' : 'Key configured · untested') : 'Not connected';
  if (j.checked_at) $('jev-message').textContent = 'Last successful check: ' + j.checked_at + (j.advisor_enabled ? '. Browser assistance enabled.' : '. Browser assistance is off.');
}
async function connectionAction(path, body, method) {
  connectionBusy = true; controls();
  try { const result = await api(path, body, method); await refresh(); return result; }
  finally { connectionBusy = false; controls(); }
}
$('jev-form').onsubmit = event => { event.preventDefault(); run(async () => {
  const key = $('jev-key').value.trim(); $('jev-key').value = '';
  $('jev-message').textContent = 'Testing authentication…';
  try { const result = await connectionAction('connections/jev', {key}); $('jev-message').textContent = result.message; }
  catch (e) { $('jev-message').textContent = e.message; throw e; }
}); };
$('jev-check').onclick = () => run(async () => { const result = await connectionAction('connections/jev/check', {}); $('jev-message').textContent = result.message; });
$('jev-disconnect').onclick = () => run(async () => { const result = await connectionAction('connections/jev', undefined, 'DELETE'); $('jev-message').textContent = result.message; });
$('codex-login').onclick = () => run(async () => { $('codex-message').textContent = 'Requesting a one-time sign-in code…'; try { await connectionAction('connections/codex/login', {}); } catch(e) { $('codex-message').textContent = e.message; throw e; } });
$('codex-check').onclick = () => run(() => connectionAction('connections/codex/check', {}));
$('codex-logout').onclick = () => run(() => connectionAction('connections/codex', undefined, 'DELETE'));
$('codex-cancel').onclick = () => run(() => connectionAction('connections/codex/cancel', {}));
$('codex-key-form').onsubmit = event => { event.preventDefault(); run(async () => { const key = $('codex-key').value.trim(); $('codex-key').value = ''; await connectionAction('connections/codex/key', {key}); }); };

$('research-history').onchange = controls;
$('discovery-prompt').oninput = controls;
$('discovery-limit').oninput = controls;
$('discovery-minutes').oninput = controls;
$('discovery-visits').oninput = controls;
$('research-adjust-time').onclick = () => { researchViewOverride='edit';renderResearchScreen(); $('research-brief').open=true; $('research-options').open=true; $('discovery-minutes').focus(); $('discovery-minutes').scrollIntoView({block:'center',behavior:'smooth'}); };
$('research-start').onclick = () => run(async () => {
  const plan=researchState?.plan;
  if (!plan) throw Error('Prepare a research plan first.');
  researchSubmitting=true; researchJobId=null; controls();
  $('research-launch-status').textContent='Sending the research request…';
  try {
    const response=await api('discover',{prompt:plan.prompt,limit:plan.limit,plan_id:plan.id,history_ack:$('research-history').checked});
    researchJobId=response.job_id;
    $('planning-conversation').open=false;
    $('research-launch-status').textContent='Research request accepted. Waiting for the browser…';
    await refresh();
  } catch (e) {
    $('research-launch-status').textContent='Research could not start: ' + e.message;
    throw e;
  } finally { researchSubmitting=false; controls(); }
});
$('research-stop').onclick = () => run(async () => { await api('discovery/stop',{}); await refresh(); });
$('google-login').onclick = () => run(async () => {
  const tab=window.open('about:blank','_blank');
  try {
    const result=await connectionAction('connections/google/login',{});
    const url=new URL(result.authorization_url);
    if(url.protocol!=='https:' || url.hostname!=='accounts.google.com')throw Error('Unexpected Google sign-in URL.');
    if(tab){tab.opener=null;tab.location=url.href;} else { error('Allow popups for this app, then click Connect Google again.'); }
  } catch(e){if(tab)tab.close();throw e;}
});
$('google-disconnect').onclick = () => run(()=>connectionAction('connections/google',undefined,'DELETE'));
$('google-create').onclick = () => run(async()=>{await api('sheets/create',{});await refresh();});

$('google-sheet-form').onsubmit = event => {event.preventDefault();run(async()=>{const result=await connectionAction('connections/google/sheet',{value:$('google-sheet').value.trim()});$('google-message').textContent=result.message;});};

$('research-use-plan').onclick = () => { if (!researchState?.plan) return; $('discovery-prompt').value=researchState.plan.prompt; $('discovery-limit').value=researchState.plan.limit; $('discovery-minutes').value=researchState.plan.max_minutes ?? 15; $('discovery-visits').value=researchState.plan.max_profiles ?? 0; $('discovery-recheck').checked=Boolean(researchState.plan.recheck_failed); $('discovery-profile').value=researchState.plan.profile_url || ''; $('research-history').checked=false; controls(); };

// Navigate between focused screens without recreating the browser or form state.
let composerRestored=false;
let composeLead=null,composeState=null,composeBusy=false,composeJob=null;
let activeMode='discovery',crmBrowserVisible=false,crmProfileBusy=false;
const workspaceViews=['discovery','compose','browser-section','connections','outreach','activity'];
$('research-workspace').append($('composer'));
$('connections').append($('browser-help'));
for(const id of ['connections','outreach','activity'])$('research-workspace').append($(id));
function showView(id) {
  const selected=workspaceViews.includes(id)?id:'discovery';
  if(selected==='discovery' || selected==='compose')activeMode=selected;
  if(selected!=='outreach')crmBrowserVisible=false;
  const panel=['connections','outreach','activity'].includes(selected)?selected:null;
  if(workspace && window.location.hash!=='#'+selected)history.replaceState(null,'','#'+selected);
  $('research-workspace').hidden=!workspace;
  $('research-workspace').classList.add('watching');
  $('browser-section').hidden=!workspace || (panel==='outreach' && !crmBrowserVisible);
  $('research-workspace').classList.toggle('crm-wide',panel==='outreach' && !crmBrowserVisible);
  $('crm-hide-browser').hidden=panel!=='outreach' || !crmBrowserVisible;
  $('discovery').hidden=!workspace || activeMode!=='discovery' || Boolean(panel);
  $('composer').hidden=!workspace || activeMode!=='compose' || !composeLead || Boolean(panel);
  $('outreach-start').hidden=!workspace || activeMode!=='compose' || Boolean(composeLead) || Boolean(panel);
  for(const view of ['connections','outreach','activity']) {
    $(view).hidden=!workspace || view!==panel;
    $(view).classList.add('utility-panel');
  }
  $('close-panel').hidden=!workspace || !panel;
  if(panel)$(panel).prepend($('close-panel'));
  document.querySelectorAll('.topbar nav a').forEach(link=>{
    if(link.hash==='#'+(panel || activeMode))link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  });
}
$('close-panel').onclick=()=>showView(activeMode);
$('crm-hide-browser').onclick=()=>{crmBrowserVisible=false;showView('outreach');};
async function openCrmProfile(lead){
  if(crmProfileBusy || workspace.busy)return;
  crmProfileBusy=true;crmBrowserVisible=true;showView('outreach');
  $('crm-profile-status').textContent='Opening '+lead.name+' in your private browser…';
  renderCrm(crmRecords,workspace);
  try {
    const result=await api('crm/'+encodeURIComponent(lead.id)+'/profile',{});
    if(result.job_id){
      workspace.busy=true;controls();
      await browserProfileResult(result.job_id);
      $('crm-profile-status').textContent=lead.name+' is open in the private browser.';
    } else $('crm-profile-status').textContent=result.message;
  } catch(e){$('crm-profile-status').textContent=e.message;throw e;}
  finally{crmProfileBusy=false;await refresh();}
}
async function browserProfileResult(id){
  const deadline=Date.now()+90000;
  while(Date.now()<deadline){
    const jobs=await api('records/jobs'),job=jobs.find(j=>j.id===id);
    if(job && job.status!=='running'){
      if(job.status!=='completed')throw Error(JSON.parse(job.result).message || 'Profile could not be opened.');
      return;
    }
    await new Promise(resolve=>setTimeout(resolve,750));
  }
  throw Error('The browser is still working. Check History before trying again.');
}

function renderWorkspace() {
  $('access').hidden = Boolean(workspace);
  $('workspace-bar').hidden = !workspace;
  if (!workspace) return;
  const demo = workspace.mode === 'demo';
  const ready = workspace.discovery.ready;
  $('connection-summary').textContent = demo ? 'Demo workspace · fictional candidates only' :
    'Research agent: ' + (connections?.codex.signed_in ? 'connected' : 'sign-in needed') +
    ' · LinkedIn: uses your browser session · CRM: saved locally';
  const link = $('next-action');
  if (workspace.busy) {
    $('next-step').textContent = 'Your workspace is working';
    link.textContent = 'View activity'; link.href = '#activity';
  } else if (!demo && workspace.linkedin_restriction) {
    $('next-step').textContent = 'LinkedIn actions are paused';
    link.textContent = 'Review browser'; link.href = '#browser-section';
  } else if (!demo && !connections?.codex.signed_in) {
    $('next-step').textContent = 'First, connect your research agent';
    link.textContent = 'Connect agent'; link.href = '#connections';
  } else {
    $('next-step').textContent = ready ? 'Ready to find your next conversation' : workspace.discovery.reason;
    link.textContent = 'Go to research'; link.href = '#discovery';
  }
  // Collapse the original brief once per new plan, without fighting user edits.
  const planId = researchState?.plan?.id;
  if (planId && $('research-brief').dataset.planId !== planId) {
    if (!$('research-brief').dataset.planId || !$('discovery-prompt').value.trim()) {
      $('discovery-prompt').value = researchState.plan.prompt; $('discovery-recheck').checked=Boolean(researchState.plan.recheck_failed); $('discovery-profile').value=researchState.plan.profile_url || '';
      $('discovery-limit').value = researchState.plan.limit; $('discovery-minutes').value = researchState.plan.max_minutes ?? 15; $('discovery-visits').value = researchState.plan.max_profiles ?? 0;
    }
    $('research-brief').open = false;
    $('research-brief').dataset.planId = planId;
  }
  showView(window.location.hash.slice(1));
}
window.addEventListener('hashchange', () => showView(window.location.hash.slice(1)));
showView(window.location.hash.slice(1));


// One current task surface; polling changes screens only when the plan/run changes.
function renderResearchScreen(){
  if(!workspace)return;
  const plan=researchState?.plan;
  const job=researchLatestJob && (!plan || researchLatestJob.created>=plan.created) ? researchLatestJob : null;
  const running=Boolean(researchState?.active || job?.status==='running' || researchSubmitting);
  const key=(plan?.id || 'none')+':'+(job?.id || '')+':'+(job?.status || '')+':'+running;
  if(key!==researchViewKey){researchViewOverride=null;researchViewKey=key;}
  const phase=running?'running':researchViewOverride || (job?'results':plan?'review':'edit');
  $('discovery').dataset.phase=phase;
  const titles={edit:['Define audience','Who do you want to meet?','Describe your ideal contact, or refine the brief with the agent.'],review:['Review plan','Ready to search','Review the criteria and limits, then start your search.'],running:['Research in progress','Finding your next conversations','Watch the decisions below and LinkedIn in the private browser.'],results:['Run complete','Review your research results','Saved candidates are in your CRM. Review the outcome or adjust your next run.']};
  if(phase==='results' && job?.status!=='completed')titles.results=['Run stopped','Research needs attention','Review the reason below. Saved contacts remain in your CRM.'];
  if(phase==='results' && job?.status==='completed'){
    const result=JSON.parse(job.result || '{}');
    if(result.reason && !['target_reached','search_exhausted','visit_limit'].includes(result.reason))titles.results[0]='Run stopped';
  }
  const [label,title,intro]=titles[phase];
  $('research-phase').textContent=label;$('research-title').textContent=title;$('research-intro').textContent=intro;
  for(const id of ['research-brief','planning-conversation']){$(id).hidden=phase!=='edit';$(id).open=true;}
  $('research-plan').hidden=phase!=='review' || workspace.mode!=='live';
  $('research-edit').hidden=phase==='edit' || running;$('research-edit').disabled=workspace.busy;
  $('research-review-again').hidden=phase!=='results' || !plan;
  $('research-review-again').disabled=workspace.busy;
  $('research-run-summary').hidden=!['running','results'].includes(phase);
  $('research-run-summary').textContent=job?researchLaunchMessage(job):running?'Starting research…':'';
  $('research-decisions').hidden=!['running','results'].includes(phase) || !researchState?.events?.length;
  $('research-decisions').open=true;
  $('research-stop').hidden=!running;
  $('research-adjust-time').hidden=phase!=='review';
  $('discover').hidden=phase!=='edit';
  $('discovery-state').hidden=phase!=='edit';
  $('research-launch-status').hidden=Boolean(researchLatestJob) && !researchSubmitting && !$('research-launch-status').textContent.startsWith('Research could not start:');
}
$('research-edit').onclick=()=>{researchViewOverride='edit';renderResearchScreen();$('discovery-prompt').focus();};
$('research-review-again').onclick=()=>{researchViewOverride='review';$('research-history').checked=false;controls();};

function researchLaunchMessage(job) {
  const result = JSON.parse(job.result || '{}');
  if (job.status === 'running') return 'Research is running. Decisions appear below; LinkedIn activity is visible beside this panel.';
  if (job.status !== 'completed') return 'Research stopped: ' + (result.message || job.status);
  const normal = ['target_reached', 'search_exhausted', 'visit_limit'];
  const stopped = result.reason && !normal.includes(result.reason);
  return (stopped ? 'Research stopped: ' : 'Research finished: ') +
    (result.staged ?? result.added ?? 0) + ' candidates saved. ' + (result.reason || '').replaceAll('_', ' ');
}

function renderBrief(jobs) {
  const conversation=researchState?.conversation;
  if (conversation && conversation.revision !== briefRevision) {
    briefRevision=conversation.revision;
    const log=$('brief-chat');log.replaceChildren();
    if (!conversation.messages.length) {
      const welcome=document.createElement('p');welcome.className='chat-welcome';
      welcome.textContent='Tell me who you’re looking for. We can narrow the roles, companies, location and exclusions together.';log.append(welcome);
    }
    for (const message of conversation.messages) {
      const bubble=document.createElement('div');bubble.className='chat-message '+(message.role==='user'?'from-user':'from-agent');
      const name=document.createElement('strong');name.textContent=message.role==='user'?'You':'Research agent';
      const text=document.createElement('p');text.textContent=message.content;bubble.append(name,text);log.append(bubble);
    }
    if (conversation.brief || conversation.messages.length) $('discovery-prompt').value=conversation.brief;
    requestAnimationFrame(()=>{log.scrollTop=log.scrollHeight;});
    if (conversation.messages.length) $('research-brief').open=false;
  }
  const job=briefJobId ? jobs.find(j=>j.id===briefJobId) : !conversation?.messages.length ? null : jobs.filter(j=>j.kind==='discovery-brief').sort((a,b)=>b.created.localeCompare(a.created))[0];
  if (job) {
    const result=JSON.parse(job.result || '{}');
    $('brief-status').textContent=job.status==='running'?'Thinking about your audience…':job.status==='completed'?'Working brief updated. Keep refining or prepare your plan.':'Could not refine: '+(result.message || job.status);
  } else if (workspace.mode==='demo') $('brief-status').textContent='Conversation requires live mode and your research-agent connection. Demo can preview fictional leads below.';
}
$('brief-form').onsubmit=event=>{event.preventDefault();run(async()=>{
  const message=$('brief-message').value.trim();
  if(message.length<2)throw Error('Tell the agent what you want to refine.');
  briefSubmitting=true;controls();$('brief-status').textContent='Sending your message…';
  try {
    const result=await api('discovery/brief',{message,brief:$('discovery-prompt').value.trim()});
    briefJobId=result.job_id;$('brief-message').value='';$('research-history').checked=false;
    $('research-launch-status').textContent='';researchJobId=null;
    await refresh();
  } catch(e){$('brief-status').textContent=e.message;throw e;}
  finally{briefSubmitting=false;controls();}
});};
$('brief-reset').onclick=()=>run(async()=>{
  await api('discovery/brief/reset',{});briefJobId=null;briefRevision=null;
  $('brief-message').value='';$('discovery-prompt').value='';$('research-history').checked=false;
  $('brief-status').textContent='New brief. Your existing CRM contacts are unchanged.';
  $('research-brief').open=true;$('planning-conversation').open=true;await refresh();
});

function decisionSummary(event) {
  const d=JSON.parse(event.detail || '{}');
  const names={reassessing_cached:'Checking saved evidence for this audience',web_worker_started:'Web worker started',web_worker_finished:'Web worker finished',web_worker_canceled:'Web worker stopped',filtered_seen:'Filtering previously seen profiles',adapting_search:'Trying new search queries',expanding_web:'Finding new companies on the web',web_fallback:'Checking missing evidence on the web',rechecking:'Rechecking prior evidence failure',web_search:'Searching the web',web_source:'Reading primary source',web_shortlist:'Web shortlist ready',web_excluded:'Excluded before LinkedIn',started:'Run started',checking_browser:'Checking browser',searching:'Searching LinkedIn',search:'Search results',ranking:'Prioritizing with Jev',prioritized:'First profile in research order',visiting:'Opening profile',selecting_employer:'Finding the current employer',employer_selected:'Checking company',qualifying:'Evaluating fit with Codex',staged_for_review:'Saved for your review',insufficient_evidence:'Skipped: evidence did not qualify',current_employer_unclear:'Skipped: employer unclear',company_replied_or_held:'Skipped: company excluded',previously_visited_or_reserved:'Skipped: previously visited',known_contact:'Skipped: already in CRM',own_profile:'Skipped: your own profile',duplicate:'Skipped: duplicate',stopped:'Research stopped',finished:'Run finished'};
  let text=d.reason || '';
  if(event.kind==='started')text='Target: '+d.plan.limit+' candidates. '+d.plan.summary;
  if(event.kind==='search')text=d.observed_profiles+' profile links observed for '+d.query;
  if(event.kind==='finished' && d.reason==='discovery_budget_exhausted')d.reason='Search budget reached before the target. The bounded web discovery rounds were exhausted.';
  if(event.kind==='finished')text=d.staged+' saved · '+d.visited+' profiles visited · '+d.seconds+' seconds. '+(d.reason || '').replaceAll('_',' ');
  if(event.kind==='previously_visited_or_reserved')text='Already inspected or reserved by a prior run; not revisited automatically.';
  if(event.kind==='known_contact')text='This profile is already in your local CRM.';
  return {title:(d.worker ? 'Web '+d.worker+' · ' : '')+(names[event.kind] || event.kind).replaceAll('_',' '),text,query:d.query,url:d.url,quote:d.role_quote};
}
function renderDecisions() {
  const events=researchState?.events || [];
  const activity=$('research-decisions');
  if(activity.dataset.active!==String(Boolean(researchState?.active))){activity.open=Boolean(researchState?.active);activity.dataset.active=String(Boolean(researchState?.active));}
  $('research-decisions').hidden=!events.length;
  if(!events.length)return;
  const revision=events[0].id+':'+Boolean(researchState.active);
  if(revision===decisionRevision)return;
  decisionRevision=revision;
  const run=events[0].run_id;
  const current=events.filter(e=>e.run_id===run).slice(0,16);
  $('research-live-step').textContent=(researchState.active?'Now: ':'Latest run: ')+decisionSummary(current[0]).title;
  const log=$('decision-log');log.dataset.runId=run;log.replaceChildren();
  for(const event of current) {
    const detail=decisionSummary(event),card=document.createElement('article');card.className='decision-card';
    const title=document.createElement('strong');title.textContent=detail.title;
    const text=document.createElement('p');text.textContent=detail.text;card.append(title,text);
    if(detail.query && event.kind!=='search') {const query=document.createElement('p');query.className='decision-query';query.textContent=detail.query;card.append(query);}
    if(detail.quote){const quote=document.createElement('blockquote');quote.textContent=detail.quote;card.append(quote);}
    if(detail.url) {
      try {const url=new URL(detail.url);if(url.protocol==='https:' && !url.username && !url.password) {
        const link=document.createElement('a');link.href=url.href;link.textContent='View source ↗';link.target='_blank';link.rel='noopener noreferrer';card.append(link);
      }}catch(_){/* Untrusted source URLs remain unlinked. */}
    }
    log.append(card);
  }
}



$('discovery-recheck').onchange=controls;
$('discovery-profile').oninput=controls;

$('clear-search-history').onclick=()=>run(async()=>{
  if(!confirm('Clear temporary discovery logs? CRM profiles, campaign assessments, source evidence and audit history will remain, so duplicates will still be skipped. Use Recheck to deliberately revisit profiles. Contacts, replies, outreach history, connections and your current plan will be kept.'))return;
  $('clear-search-history').disabled=true;
  try {
    const result=await api('discovery/history/clear',{confirm:true});
    researchJobId=null;researchSeenJobId=null;decisionRevision=null;
    $('research-launch-status').textContent='';$('research-history').checked=false;
    $('decision-log').replaceChildren();$('decision-log').dataset.runId='';
    await refresh();
    $('clear-history-status').textContent=result.message;
  } finally {controls();}
});

let crmRecords=[],crmReports=[],crmSort={key:"name",direction:1};
const crmFilterLabels={all:'All profiles',qualified:'Qualified',not_applicable:'Visited · not applicable',missing_evidence:'Missing evidence',other:'Other / interrupted',available:'Available for outreach',sent:'Sent',replied:'Replied',blocked:'Blocked',uncertain:'Uncertain'};
function crmCategory(lead) {
  if(lead.qualification) return ({qualified:'qualified',not_applicable:'not_applicable',missing_evidence:'missing_evidence'})[lead.qualification] || 'other';
  if(lead.status==='not_applicable')return 'not_applicable';
  if(lead.status==='missing_evidence')return 'missing_evidence';
  if(['review','approved','confirmed','simulated','replied','skipped','blocked','uncertain'].includes(lead.status))return 'qualified';
  return 'other';
}
function renderCrm(leads,status) {
  const selection=$('crm-filter').value;
  const campaignSelect=$('crm-campaign'),selectedCampaign=campaignSelect.value;
  const campaigns=new Map();for(const lead of leads)for(const a of lead.assessments || [])if(a.campaign_id)campaigns.set(a.campaign_id,a.campaign_name);
  campaignSelect.replaceChildren(new Option('All campaigns',''));
  for(const [id,name] of campaigns)campaignSelect.add(new Option(name,id));
  campaignSelect.value=campaigns.has(selectedCampaign)?selectedCampaign:'';
  if(campaignSelect.value)leads=leads.filter(l=>(l.assessments || []).some(a=>a.campaign_id===campaignSelect.value)).map(l=>{const a=l.assessments.find(a=>a.campaign_id===campaignSelect.value);return {...l,qualification:a.qualification,campaign_id:a.campaign_id,campaign:a.campaign_name,reason:a.explanation};});
  const counts={all:leads.length,qualified:0,not_applicable:0,missing_evidence:0,other:0};
  for(const lead of leads)counts[crmCategory(lead)]++;
  for(const k of ['available','sent','replied','blocked','uncertain'])counts[k]=leads.filter(l=>crmMatches(l,k)).length;
  for(const option of $('crm-filter').options)option.textContent=crmFilterLabels[option.value]+' ('+counts[option.value]+')';
  const query=$('crm-search').value.trim().toLocaleLowerCase();
  const visible=(selection==='all'?leads:leads.filter(lead=>crmMatches(lead,selection)))
    .filter(l=>!query || [l.name,l.company,l.role,l.country,l.campaign].some(v=>String(v || '').toLocaleLowerCase().includes(query)))
    .sort((a,b)=>String(a[crmSort.key] || '').localeCompare(String(b[crmSort.key] || ''),undefined,{numeric:true,sensitivity:'base'})*crmSort.direction);
  $('crm-grid').dataset.density=$('crm-density').value;
  for(const th of document.querySelectorAll('#crm-grid th[data-sort]')){
    const active=th.dataset.sort===crmSort.key;
    th.setAttribute('aria-sort',active?(crmSort.direction===1?'ascending':'descending'):'none');
    th.querySelector('.sort-icon').textContent=active?(crmSort.direction===1?'↑':'↓'):'↕';
  }
  const overview=$('crm-overview');overview.replaceChildren();
  for(const [key,label,tone] of [['all','Contacts','neutral'],['qualified','Qualified','success'],['available','Ready to contact','info'],['missing_evidence','Needs evidence','warning']]){
    const metric=document.createElement('button');metric.className='crm-metric '+tone;
    metric.setAttribute('aria-pressed',String(selection===key));
    const number=document.createElement('strong');number.textContent=counts[key];
    const text=document.createElement('span');text.textContent=label;metric.append(number,text);
    metric.onclick=()=>{$('crm-filter').value=key;$('crm-filter').dispatchEvent(new Event('change'));};overview.append(metric);
  }
  $('crm-report').replaceChildren();
  const table=document.createElement('table'),head=table.createTHead().insertRow();
  for(const name of ['Campaign','Researched','Qualified','Attempted','Sent']) {const cell=document.createElement('th');cell.textContent=name;head.append(cell);}
  const body=table.createTBody();
  for(const r of crmReports || []) {if(campaignSelect.value && r.id!==campaignSelect.value)continue;const row=body.insertRow();for(const value of [r.name,r.researched,r.qualified,r.attempted,r.sent])row.insertCell().textContent=value;}
  $('crm-report').append(table);
  $('crm-filter-count').textContent='Showing '+visible.length+' of '+leads.length+' profiles';
    $('leads').replaceChildren();
    if (!visible.length) { const row = $('leads').insertRow(); const cell = row.insertCell(); cell.colSpan = 9; cell.className = 'empty'; cell.textContent = leads.length ? 'No contacts match this view. Clear your search or reset filters.' : 'No candidates yet. Start with Find leads.'; }
    for (const [index,lead] of visible.entries()) {
      const tr=document.createElement('tr');tr.dataset.id=lead.id;
      const cell=(value,cls='')=>{const td=document.createElement('td');td.className=cls;td.textContent=value || '—';td.title=value || '';tr.append(td);return td;};
      cell(String(index+1),'row-number');
      const person=cell('','person-cell');person.replaceChildren();
      const name=document.createElement('button');name.className='contact-name';name.textContent=lead.name || 'Unnamed contact';person.append(name);
      const company=cell(lead.company || 'Not confirmed','company-cell');
      const role=document.createElement('span');role.className='crm-secondary';role.textContent=lead.role || 'Role not confirmed';role.title=role.textContent;company.append(role);
      cell(lead.country,'country-cell');
      const fit=cell('');fit.replaceChildren(crmBadge(lead.qualification || 'unassessed'));
      const campaign=cell(lead.campaign || 'Unassigned','campaign-cell');campaign.title=lead.campaign || 'Unassigned';
      const outreach=cell('');outreach.replaceChildren(crmBadge(lead.outreach_status || 'not_contacted'));
      const availability=document.createElement('span');availability.className='crm-secondary';availability.textContent=lead.outreach_available?'Ready to contact':lead.availability_reason || lead.approval || 'Review';availability.title=availability.textContent;outreach.append(availability);
      const verified=cell(lead.last_verified_at?.slice(0,10) || 'Not verified','date-cell');
      if(lead.last_contact_at){const contacted=document.createElement('span');contacted.className='crm-secondary';contacted.textContent='Contacted '+lead.last_contact_at.slice(0,10);verified.append(contacted);}
      const details=document.createElement('div');details.className='crm-detail';
      name.onclick=()=>{ $('crm-detail-title').textContent=lead.name;$('crm-detail-content').replaceChildren(details);$('crm-detail-dialog').showModal(); };
      if(lead.visited_at || lead.assessments?.length) {
        const summary=document.createElement('h3');summary.textContent='Research & evidence';details.append(summary);
        const text=document.createElement('p');text.style.whiteSpace='pre-line';text.textContent='Last visited: '+(lead.visited_at || 'Not recorded')+'\nAudience: '+(lead.audience || lead.campaign || 'Unassigned')+'\nDecision: '+(lead.reason || lead.availability_reason || 'Review the assessments below.');details.append(text);
        for(const entry of (lead.research_history || []).slice(0,-1)){const p=document.createElement('p');p.textContent=entry.visited_at+' · '+entry.status+' · '+entry.audience+' · '+entry.reason;details.append(p);}
        for(const a of lead.assessments || []){const p=document.createElement('p');p.textContent=(a.campaign_name || 'Unassigned')+' · '+a.qualification+' · '+a.explanation;details.append(p);}
        for(const source of lead.sources || []){const p=document.createElement('p');p.textContent=source.fact_type+': “'+source.quotation+'” · '+source.captured_at;details.append(p);try{const u=new URL(source.source_url);if(u.protocol==='https:' && !u.username && !u.password){const a=document.createElement('a');a.href=u.href;a.textContent='Source ↗';a.target='_blank';a.rel='noopener noreferrer';details.append(a);}}catch(_){}}
        for(const m of lead.messages || []){const p=document.createElement('p');p.textContent=m.direction+' · '+m.occurred_at+' · '+m.body;details.append(p);}

      }
      if(!details.children.length)details.textContent='No research evidence has been recorded for this contact yet.';
      const td = document.createElement('td'), button = document.createElement('button');td.className='crm-actions-cell';button.className='secondary';
      button.textContent = ['review','approved'].includes(lead.status) ? 'Compose message' : 'View outreach';
      button.disabled = !lead.person_id && String(lead.id).startsWith('visited:');
      if(String(lead.id).startsWith('visited:'))button.disabled=true;
      button.onclick = () => run(()=>openComposer(lead));
      const a=document.createElement('button');a.className='secondary crm-profile';a.textContent='Open profile';
      a.disabled=Boolean(workspace.busy || crmProfileBusy);a.onclick=()=>run(()=>openCrmProfile(lead));
      td.append(button,a);tr.append(td);$('leads').append(tr);
    }

}
function crmBadge(value){
  const label={qualified:'Qualified',not_applicable:'Not applicable',missing_evidence:'Missing evidence',unassessed:'Unassessed',interrupted:'Interrupted',excluded:'Excluded',not_contacted:'Not contacted',confirmed:'Sent',simulated:'Simulated',uncertain:'Uncertain',blocked:'Blocked',sending:'Sending',skipped:'Skipped',replied:'Replied'};
  const tone=['qualified','confirmed','replied'].includes(value)?'success':['missing_evidence','uncertain','interrupted'].includes(value)?'warning':['excluded','blocked'].includes(value)?'danger':value==='sending'?'info':'neutral';
  const span=document.createElement('span');span.className='status-pill '+tone;span.textContent=label[value] || String(value).replaceAll('_',' ');return span;
}
$('crm-detail-close').onclick=()=>$('crm-detail-dialog').close();
$('crm-detail-dialog').onclick=e=>{if(e.target===$('crm-detail-dialog')){const rect=e.target.getBoundingClientRect();if(e.clientX<rect.left || e.clientX>rect.right || e.clientY<rect.top || e.clientY>rect.bottom)e.target.close();}};
function saveCrmView(){try{sessionStorage.setItem('workbench-crm-view',JSON.stringify({search:$('crm-search').value,density:$('crm-density').value,sort:crmSort}));}catch(_){} }
try{const saved=JSON.parse(sessionStorage.getItem('workbench-crm-view') || '{}');$('crm-search').value=saved.search || '';if(['compact','comfortable'].includes(saved.density))$('crm-density').value=saved.density;if(['name','company','country','qualification','campaign','outreach_status','last_verified_at'].includes(saved.sort?.key) && [1,-1].includes(saved.sort?.direction))crmSort=saved.sort;}catch(_){}
$('crm-search').oninput=()=>{saveCrmView();if(workspace)renderCrm(crmRecords,workspace);};
$('crm-density').onchange=()=>{saveCrmView();if(workspace)renderCrm(crmRecords,workspace);};
for(const th of document.querySelectorAll('#crm-grid th[data-sort]'))th.querySelector('button').onclick=()=>{crmSort={key:th.dataset.sort,direction:crmSort.key===th.dataset.sort?-crmSort.direction:1};saveCrmView();if(workspace)renderCrm(crmRecords,workspace);};
$('crm-reset').onclick=()=>{$('crm-search').value='';$('crm-campaign').value='';$('crm-filter').value='all';$('crm-density').value='compact';crmSort={key:'name',direction:1};saveCrmView();$('crm-filter').dispatchEvent(new Event('change'));};
try {
  const saved=sessionStorage.getItem('workbench-crm-filter');
  if(Object.hasOwn(crmFilterLabels,saved))$('crm-filter').value=saved;
}catch(_){/* Filtering works when browser storage is unavailable. */}
$('crm-filter').onchange=()=>{
  try{sessionStorage.setItem('workbench-crm-filter',$('crm-filter').value);}catch(_){}
  if(workspace)renderCrm(crmRecords,workspace);
};

$('crm-campaign').onchange=()=>{if(workspace)renderCrm(crmRecords,workspace);};

function composerControls(){
  const lead=composeState?.lead,note=$('compose-note').value,receipt=composeState?.receipt;
  const valid=note.trim().length>0 && note.length<=200;
  $('compose-person').disabled=composeBusy || Boolean(workspace?.busy);
  $('compose-count').textContent=note.length+' / 200 characters'+(note.length>200?' · Shorten this note':'');
  const locked=!lead || (composeLead && !composeLead.outreach_available) || composeBusy || Boolean(workspace?.busy) || Boolean(receipt);
  for(const button of $('compose-suggestions').querySelectorAll('button'))button.disabled=locked;
  for(const id of ['compose-generate','compose-preview','compose-save','compose-approve'])$(id).disabled=locked;
  $('compose-generate').disabled=locked || !$('compose-instructions').value.trim();
  $('compose-save').disabled=locked || !valid;
  $('compose-approve').disabled=locked || !valid || (composeLead?.qualification && composeLead.qualification!=='qualified');
  $('compose-note').disabled=locked;$('compose-instructions').disabled=locked;
  $('compose-send').disabled=locked || !valid || lead?.status!=='approved' || lead.note!==note || !$('compose-confirm').checked;
  $('compose-send').textContent=workspace?.mode==='demo'?'Simulate invitation':'Send invitation';
  $('compose-confirm-label').textContent=(workspace?.mode==='demo'?'Simulate sending':'Send')+' this exact invitation to '+(lead?.name || 'this person')+'.';
}
async function openComposer(lead){
  if(composeBusy)return;
  composeLead=lead;composeState=await api('leads/'+lead.id+'/composer');
  const select=$('compose-person');select.replaceChildren();
  for(const p of crmRecords.filter(p=>!String(p.id).startsWith('visited:')))select.add(new Option(p.name+' · '+(p.outreach_available?'Available':p.outreach_status || p.qualification),p.id));
  select.value=lead.id;select.disabled=composeBusy || Boolean(workspace?.busy);
  $('compose-context').textContent=(lead.availability_reason ? lead.availability_reason+' · ' : '')+lead.role+' at '+lead.company+' · '+(lead.campaign || 'Unassigned campaign');
  $('compose-profile').href=lead.url;
  $('compose-evidence-text').textContent=(lead.reason || '')+'\n'+(lead.sources || []).map(s=>s.fact_type+': '+s.quotation).join('\n');
  $('compose-title').textContent='Message '+lead.name;
  const draft=composeState.draft;
  $('compose-instructions').value=draft?.instructions || '';
  $('compose-note').value=draft?.note || composeState.lead.note || '';
  $('compose-confirm').checked=false;
  try{sessionStorage.setItem('workbench-recipient',lead.id);}catch(_){}
  $('compose-status').textContent=composeState.lead.status==='approved'?'Approved note loaded. Confirm the exact text before sending.':(draft?.result?.reason || 'Write instructions to generate a note, or draft one yourself.');
  $('compose-suggestions-wrap').open=!composeState.receipt;
  $('compose-suggestions-wrap').hidden=!(draft?.result?.suggestions?.length);
  $('compose-suggestions').replaceChildren();
  for(const suggestion of draft?.result?.suggestions || []){
    const card=document.createElement('article');card.className='suggestion';
    const text=document.createElement('p');text.textContent=suggestion.note;
    const evidence=document.createElement('small');evidence.textContent='Based on: “'+suggestion.evidence_quote+'” · '+suggestion.rationale;
    const button=document.createElement('button');button.className='secondary';button.textContent='Use this note';
    button.onclick=()=>{$('compose-suggestions-wrap').open=false;$('compose-note').value=suggestion.note;$('compose-confirm').checked=false;composerControls();};
    card.append(text,evidence,button);$('compose-suggestions').append(card);
  }
  $('compose-receipt').hidden=!composeState.receipt;
  $('compose-receipt').textContent=composeState.receipt?'Outreach result: '+composeState.receipt.status+' · '+composeState.receipt.evidence:'';
  for(const previous of composeState.previous_attempts || []){
    const item=document.createElement('p');item.textContent='Previous attempt: '+previous.status+' · '+previous.evidence;
    $('compose-receipt').append(item);
  }
  const audit=composeState.network_receipt;
  if(audit){const detail=document.createElement('p');const net=audit.network;detail.textContent='Attempt stage: '+audit.phase+' · Send click: '+(audit.click_attempted?'attempted once':'not attempted')+' · Matching invitation POST 200: '+(net.accepted?'confirmed':'not observed');$('compose-receipt').append(detail);}
  showView('compose');
  composerControls();
}
async function composerAction(action){
  if(composeBusy)return;composeBusy=true;composerControls();
  try{await action();}catch(error){$('compose-status').textContent=error.message;}finally{composeBusy=false;composerControls();}
}
async function waitComposerJob(id){
  for(;;){
    const jobs=await api('records/jobs'),job=jobs.find(j=>j.id===id);
    if(job && job.status!=='running'){
      if(job.status!=='completed')throw Error(job.result || 'The operation did not complete.');
      return job;
    }
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
}
$('compose-close').onclick=()=>{try{sessionStorage.removeItem('workbench-recipient');}catch(_){}composeLead=null;composeState=null;showView('compose');renderRecipients();};
$('compose-person').onchange=()=>run(()=>openComposer(crmRecords.find(p=>p.id===$('compose-person').value)));
$('compose-note').oninput=()=>{$('compose-confirm').checked=false;composerControls();};
$('compose-instructions').oninput=composerControls;
$('compose-confirm').onchange=composerControls;
$('compose-generate').onclick=()=>composerAction(async()=>{
  $('compose-status').textContent='Drafting from profile evidence…';
  const job=await api('leads/'+composeLead.id+'/draft',{instructions:$('compose-instructions').value,campaign_id:composeLead.campaign_id});
  await waitComposerJob(job.job_id);composeBusy=false;await refresh();await openComposer(composeLead);
});
$('compose-save').onclick=()=>composerAction(async()=>{
  await api('leads/'+composeLead.id+'/draft/save',{note:$('compose-note').value,instructions:$('compose-instructions').value,campaign_id:composeLead.campaign_id});
  composeState=await api('leads/'+composeLead.id+'/composer');$('compose-status').textContent='Draft saved. Approve it when ready.';await refresh();
});
$('compose-approve').onclick=()=>composerAction(async()=>{
  const note=$('compose-note').value.trim();$('compose-note').value=note;
  await api('leads/'+composeLead.id+'/draft/save',{note,instructions:$('compose-instructions').value,campaign_id:composeLead.campaign_id});
  await api('leads/'+composeLead.id+'/approve',{note,campaign_id:composeLead.campaign_id});
  composeState=await api('leads/'+composeLead.id+'/composer');$('compose-status').textContent='Approved. Confirm below to send this exact note.';await refresh();
});
$('compose-send').onclick=()=>composerAction(async()=>{
  const note=$('compose-note').value,id=composeLead.id;
  if(! $('compose-confirm').checked || composeState.lead.note!==note)throw Error('Approve and confirm this exact note first.');
  $('compose-status').textContent=workspace.mode==='demo'?'Simulating invitation…':'Sending one reviewed invitation. Watch the browser for the result.';
  const job=await api('outreach',{lead_ids:[id],confirm:true,expected_notes:{[id]:note}});
  showView('compose');
  $('outreach-watch').hidden=false;
  $('outreach-watch-person').textContent='Invitation to '+composeState.lead.name;
  $('outreach-watch-note').textContent=note;
  $('outreach-watch-status').textContent='Opening the profile and sending your reviewed invitation…';
  try {
    await waitComposerJob(job.job_id);
    composeState=await api('leads/'+id+'/composer');
    $('outreach-watch-status').textContent=composeState.receipt.status+' · '+composeState.receipt.evidence;
  } catch(error) {
    $('outreach-watch-status').textContent=error.message+' Review the receipt before taking another action.';
    throw error;
  } finally { await refresh(); }
});
$('compose-preview').onclick=()=>composerAction(async()=>{
  const job=await api('leads/'+composeLead.id+'/preview',{});
  if(job.job_id){showView('compose');await waitComposerJob(job.job_id);}
  $('compose-status').textContent='Profile preview ready. Return to this draft when you finish reviewing.';
});
$('return-composer').onclick=()=>run(()=>openComposer(composeLead));

function crmMatches(lead,filter){
  if(filter==='available')return Boolean(lead.outreach_available);
  if(filter==='sent')return lead.status==='confirmed';
  if(filter==='replied')return Boolean(lead.last_reply_at) || lead.status==='replied';
  if(['blocked','uncertain'].includes(filter))return lead.status===filter;
  return crmCategory(lead)===filter;
}
const batchSelected=new Set(),batchNotes=new Map();
let batchBusy=false,recipientRevision='',batchJobId=null;
try{
  const saved=JSON.parse(sessionStorage.getItem('workbench-batch') || '{}');
  for(const id of saved.selected || [])batchSelected.add(id);
  for(const [id,note] of Object.entries(saved.notes || {}))batchNotes.set(id,note);
  batchJobId=saved.job_id || null;
}catch(_){}
function saveBatch(){
  try{sessionStorage.setItem('workbench-batch',JSON.stringify({selected:[...batchSelected],notes:Object.fromEntries(batchNotes),job_id:batchJobId}));}catch(_){}
}
function selectedContacts(){return crmRecords.filter(l=>batchSelected.has(l.id) && l.outreach_available);}
const recipientFilterIds=['recipient-search','recipient-status','recipient-fit','recipient-campaign','recipient-company','recipient-country','recipient-selected'];
let restoredRecipientFilters=null;
try{restoredRecipientFilters=JSON.parse(sessionStorage.getItem('workbench-recipient-filters') || 'null');}catch(_){}
function recipientFilterValues(){
  return Object.fromEntries(recipientFilterIds.map(id=>[id,$(id).type==='checkbox'?$(id).checked:$(id).value]));
}
function recipientMatches(lead,filters,selected){
  const query=(filters['recipient-search'] || '').trim().normalize('NFD').replace(/[̀-ͯ]/g,'').toLocaleLowerCase();
  const text=[lead.name,lead.company,lead.role,lead.country].join(' ').normalize('NFD').replace(/[̀-ͯ]/g,'').toLocaleLowerCase();
  const status=filters['recipient-status'] || 'available';
  return text.includes(query) &&
    (status==='all' || (status==='available'?Boolean(lead.outreach_available):(lead.outreach_status || lead.status)===status)) &&
    (!filters['recipient-fit'] || lead.qualification===filters['recipient-fit']) &&
    (!filters['recipient-campaign'] || lead.campaign_id===filters['recipient-campaign']) &&
    (!filters['recipient-company'] || (lead.company || '').trim()===filters['recipient-company']) &&
    (!filters['recipient-country'] || (lead.country || '').trim()===filters['recipient-country']) &&
    (!filters['recipient-selected'] || selected.has(lead.id));
}
function matchingRecipients(){return crmRecords.filter(l=>recipientMatches(l,recipientFilterValues(),batchSelected));}
function updateRecipientFacets(){
  for(const [id,key,label] of [['recipient-campaign','campaign_id','All campaigns'],['recipient-company','company','All companies'],['recipient-country','country','All countries']]){
    const options=new Map();
    for(const lead of crmRecords){const value=(lead[key] || '').trim();if(value)options.set(value,key==='campaign_id'?lead.campaign:value);}
    const entries=[...options].sort((a,b)=>a[1].localeCompare(b[1]));
    const node=$(id),revision=JSON.stringify(entries);
    if(node.dataset.revision!==revision){
      const selected=restoredRecipientFilters?.[id] ?? node.value;
      node.replaceChildren(new Option(label,''),...entries.map(([value,text])=>new Option(text,value)));
      node.value=options.has(selected)?selected:'';node.dataset.revision=revision;
    }
  }
  if(restoredRecipientFilters){
    for(const id of recipientFilterIds.filter(id=>!['recipient-campaign','recipient-company','recipient-country'].includes(id))){
      if(restoredRecipientFilters[id]!==undefined){
        if($(id).type==='checkbox')$(id).checked=Boolean(restoredRecipientFilters[id]);
        else $(id).value=restoredRecipientFilters[id];
      }
    }
    restoredRecipientFilters=null;
  }
}
function changeRecipientFilters(){
  $('batch-confirm').checked=false;
  try{sessionStorage.setItem('workbench-recipient-filters',JSON.stringify(recipientFilterValues()));}catch(_){}
  renderRecipients();
}
function batchControls(){
  const selected=selectedContacts(),visible=matchingRecipients().filter(l=>l.outreach_available),locked=batchBusy || Boolean(workspace?.busy);
  const ready=selected.length>0 && selected.every(l=>{const note=batchNotes.get(l.id)?.trim();return note && note.length<=200;});
  $('batch-count').textContent=selected.length+' selected';
  $('batch-generate').disabled=locked || !selected.length || !$('outreach-prompt').value.trim();
  $('batch-generate').textContent='Generate '+(selected.length || '')+' messages';
  $('batch-send').disabled=locked || !ready || !$('batch-confirm').checked;
  $('batch-send').textContent=(workspace?.mode==='demo'?'Simulate ':'Send ')+selected.length+' invitations';
  $('batch-clear').disabled=locked || !batchSelected.size;
  $('recipient-all').disabled=locked || !visible.length;
  $('recipient-all').checked=visible.length>0 && visible.every(l=>batchSelected.has(l.id));
  $('recipient-all').indeterminate=visible.some(l=>batchSelected.has(l.id)) && !$('recipient-all').checked;
  $('batch-confirm').disabled=locked || !ready;
  $('outreach-prompt').disabled=locked;
  for(const input of $('recipient-list').querySelectorAll('input'))input.disabled=locked || input.dataset.available!=='true';
  for(const input of $('batch-drafts').querySelectorAll('textarea'))input.disabled=locked;
}
function renderRecipients(){
  updateRecipientFacets();
  const available=matchingRecipients();
  const revision=JSON.stringify(available.map(l=>[l.id,l.name,l.company,l.role,l.country,l.outreach_available,l.availability_reason,l.outreach_status,l.qualification]))+JSON.stringify([...batchSelected]);
  if(revision!==recipientRevision){
    recipientRevision=revision;const root=$('recipient-list');root.replaceChildren();
    for(const lead of available){
      const row=document.createElement('label');row.className='recipient-row';
      const check=document.createElement('input');check.type='checkbox';check.checked=batchSelected.has(lead.id);check.dataset.leadId=lead.id;check.dataset.available=String(Boolean(lead.outreach_available));
      check.onchange=()=>{if(!lead.outreach_available){check.checked=false;return;}if(check.checked && batchSelected.size>=100){check.checked=false;$('batch-status').textContent='Choose up to 100 recipients per batch.';return;}
        check.checked?batchSelected.add(lead.id):batchSelected.delete(lead.id);$('batch-confirm').checked=false;saveBatch();renderRecipients();renderBatchDrafts();};
      const info=document.createElement('span'),name=document.createElement('strong'),meta=document.createElement('small');
      name.textContent=lead.name;meta.textContent=[lead.role,lead.company,lead.country].filter(Boolean).join(' · ');info.append(name,meta);
      if(!lead.outreach_available){const reason=document.createElement('small');reason.className='recipient-unavailable';reason.textContent=lead.availability_reason || (lead.qualification || lead.outreach_status || 'Unavailable').replaceAll('_',' ');info.append(reason);}row.append(check,info);root.append(row);
    }
    if(!available.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='No contacts match these filters. Reset filters or research more people.';root.append(empty);}
  }
  const eligible=available.filter(l=>l.outreach_available).length;
  const visibleIds=new Set(available.map(l=>l.id)),hidden=selectedContacts().filter(l=>!visibleIds.has(l.id)).length;
  $('recipient-selection-summary').textContent=hidden?hidden+' selected contacts hidden by filters — still included in your batch.':'Filters do not clear your selection.';
  $('outreach-availability').textContent=available.length+' of '+crmRecords.length+' contacts shown · '+eligible+' available to select · up to 100 per batch.';
  batchControls();
}
function renderBatchDrafts(){
  const root=$('batch-drafts');root.replaceChildren();
  const selected=selectedContacts();$('batch-review').hidden=!selected.some(l=>batchNotes.has(l.id));
  for(const lead of selected){
    const card=document.createElement('article');card.className='batch-draft';
    const label=document.createElement('label');label.textContent=lead.name+' · '+lead.company;
    const field=document.createElement('textarea');field.rows=3;field.value=batchNotes.get(lead.id) || '';field.id='batch-note-'+lead.id;label.htmlFor=field.id;
    const count=document.createElement('small');count.textContent=field.value.length+' / 200';
    field.oninput=()=>{batchNotes.set(lead.id,field.value);count.textContent=field.value.length+' / 200';$('batch-confirm').checked=false;saveBatch();batchControls();};
    card.append(label,field,count);root.append(card);
  }
  batchControls();
}
$('recipient-search').oninput=changeRecipientFilters;
for(const id of recipientFilterIds.filter(id=>id!=='recipient-search'))$(id).onchange=changeRecipientFilters;
$('recipient-reset').onclick=()=>{
  for(const id of recipientFilterIds){if($(id).type==='checkbox')$(id).checked=false;else $(id).value=id==='recipient-status'?'available':'';}
  changeRecipientFilters();
};
$('outreach-prompt').addEventListener('input',()=>{$('batch-confirm').checked=false;batchControls();});
$('recipient-all').onchange=()=>{
  const checked=$('recipient-all').checked;
  for(const l of matchingRecipients().filter(l=>l.outreach_available)){if(checked && batchSelected.size<100)batchSelected.add(l.id);else if(!checked)batchSelected.delete(l.id);}
  $('batch-confirm').checked=false;saveBatch();renderRecipients();renderBatchDrafts();
};
$('batch-clear').onclick=()=>{batchSelected.clear();$('batch-confirm').checked=false;saveBatch();renderRecipients();renderBatchDrafts();};
$('batch-confirm').onchange=batchControls;
async function batchAction(fn){
  if(batchBusy || workspace?.busy)return;
  batchBusy=true;batchControls();
  try{await fn();}catch(e){$('batch-status').textContent=e.message;}finally{batchBusy=false;await refresh();batchControls();}
}
$('batch-generate').onclick=()=>batchAction(async()=>{
  const selected=selectedContacts(),instructions=$('outreach-prompt').value.trim();
  $('batch-confirm').checked=false;
  for(const [index,lead] of selected.entries()){
    $('batch-status').textContent='Drafting '+(index+1)+' of '+selected.length+' · '+lead.name;
    const job=await api('leads/'+lead.id+'/draft',{instructions,campaign_id:lead.campaign_id});
    await waitComposerJob(job.job_id);
    const state=await api('leads/'+lead.id+'/composer');
    batchNotes.set(lead.id,state.draft.note || state.draft.result.suggestions[0].note);saveBatch();renderBatchDrafts();
  }
  $('batch-status').textContent='Messages ready. Review or edit each note, then confirm the batch.';
});
async function watchBatch(id){
  const job=await waitComposerJob(id),result=JSON.parse(job.result || '{}');
  const root=$('batch-results');root.replaceChildren();
  for(const receipt of result.results || []){
    const lead=crmRecords.find(l=>l.id===receipt.lead_id),row=document.createElement('p');
    row.textContent=(lead?.name || receipt.lead_id)+' · '+receipt.status+' · '+receipt.evidence;root.append(row);
    batchSelected.delete(receipt.lead_id);
  }
  $('batch-status').textContent=(result.results?.length || 0)+' processed.'+(result.reason?' '+result.reason+'.':'')+(batchSelected.size?' Remaining contacts were not sent. Review any blocker before starting another batch.':' Batch finished.');
  $('outreach-watch').hidden=false;
  $('outreach-watch-person').textContent='Batch complete';
  $('outreach-watch-note').textContent='';
  $('outreach-watch-status').textContent=$('batch-status').textContent;
  batchJobId=null;saveBatch();$('batch-confirm').checked=false;renderBatchDrafts();
}
$('batch-send').onclick=()=>batchAction(async()=>{
  if(!$('batch-confirm').checked)throw Error('Review and confirm the exact messages first.');
  const selected=selectedContacts();
  if(!selected.length || selected.length>100)throw Error('Choose 1–100 available contacts.');
  const notes=Object.fromEntries(selected.map(l=>[l.id,batchNotes.get(l.id)?.trim()]));
  if(selected.some(l=>!notes[l.id] || notes[l.id].length>200))throw Error('Every selected contact needs a note of 1–200 characters.');
  for(const lead of selected){
    await api('leads/'+lead.id+'/draft/save',{note:notes[lead.id],instructions:$('outreach-prompt').value,campaign_id:lead.campaign_id});
    await api('leads/'+lead.id+'/approve',{note:notes[lead.id],campaign_id:lead.campaign_id});
  }
  const job=await api('outreach',{lead_ids:selected.map(l=>l.id),confirm:true,expected_notes:notes});
  batchJobId=job.job_id;saveBatch();$('batch-status').textContent='Sending reviewed invitations. Watch the live browser.';
  await watchBatch(job.job_id);
});
function renderHistory(changes,jobs){
  const entries=changes.map(c=>({created:c.created,text:c.name+' · '+c.kind.replaceAll('_',' ')+' · '+(c.before_state || 'new')+' → '+c.after_state,detail:c.detail}));
  for(const e of researchState?.events || []){
    const summary=decisionSummary(e);entries.push({created:e.created,text:summary.title,detail:summary.text});
  }
  for(const j of jobs)entries.push({created:j.created,text:j.kind+' · '+j.status,detail:j.status==='failed'?j.result:''});
  entries.sort((a,b)=>b.created.localeCompare(a.created));
  const root=$('history-feed');root.replaceChildren();
  for(const e of entries.slice(0,150)){
    const card=document.createElement('article');card.className='decision-card';
    const time=document.createElement('small');time.textContent=new Date(e.created).toLocaleString();
    const title=document.createElement('p');title.textContent=e.text;
    const detail=document.createElement('p');detail.textContent=e.detail || '';
    card.append(time,title,detail);root.append(card);
  }
}

for(const id of ['discovery-prompt','discovery-limit','discovery-minutes','discovery-visits','discovery-profile','outreach-prompt']){
  try{const saved=sessionStorage.getItem('workbench-form-'+id);if(saved!==null)$(id).value=saved;}catch(_){}
  $(id).addEventListener('input',()=>{try{sessionStorage.setItem('workbench-form-'+id,$(id).value);}catch(_){}});
}

function renderReader(){
  const report=workspace?.reader_report,running=latestReaderJob?.status==='running';
  $('reader-start').disabled=!workspace || workspace.busy || readerSubmitting;
  $('reader-limit').disabled=!workspace || workspace.busy || readerSubmitting;
  $('reader-stop').disabled=!running;
  $('reader-badge').textContent=running?'Reading…':latestReaderJob?.status==='failed'?'Needs attention':latestReaderJob?.status==='interrupted'?'Interrupted':report?.reason==='stopped_by_user'?'Stopped':report?.reason==='time_limit'?'Time limit reached':report?.phase==='completed'?'Scan complete':'Not run yet';
  if(!report){if(!readerSubmitting)$('reader-status').textContent='No scan yet. Start a manual scan or use the scheduled runner.';return;}
  $('reader-status').textContent=(report.unique_conversations_checked || 0)+' conversations checked · '+(report.matched_contacts || 0)+' matched · '+(report.added || 0)+' new replies · '+(report.duplicates || 0)+' already saved · '+(report.unmatched_conversations || 0)+' outside CRM.'+(report.reason?' '+report.reason.replaceAll('_',' ')+'.':'')+(report.ended_at?' Last finished: '+new Date(report.ended_at).toLocaleString()+'.':'');
  $('reader-cases').replaceChildren();
  if(report.review_cases?.length){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=report.review_cases.length+' conversations need review';details.append(summary);for(const item of report.review_cases){const p=document.createElement('p');p.textContent=item.reason;details.append(p);}$('reader-cases').append(details);}
}
$('reader-start').onclick=()=>run(async()=>{
  const limit=Number($('reader-limit').value);if(!Number.isInteger(limit) || limit<1 || limit>100)throw Error('Choose 1 to 100 conversations.');
  readerSubmitting=true;crmBrowserVisible=true;showView('outreach');controls();
  $('reader-status').textContent='Starting the replies reader…';
  try{await api('replies/read',{limit});await refresh();}finally{readerSubmitting=false;controls();}
});
$('reader-stop').onclick=()=>run(async()=>{const result=await api('replies/stop',{});$('reader-status').textContent=result.message;});
