'use strict';
let token = '', workspace = null, browserState = null, refreshing = false, browserChecking = false, connectionBusy = false, connections = null, researchState = null, researchJobId = null, researchSubmitting = false, researchRestored = false, researchSeenJobId = null, briefSubmitting = false, briefRevision = null, briefJobId = null, decisionRevision = null;
const $ = id => document.getElementById(id);
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
  const connected = Boolean(workspace), idle = connected && !workspace.busy;
  for (const id of ['discover', 'read', 'refresh']) $(id).disabled = !idle;
  $('brief-send').disabled = !idle || briefSubmitting || workspace.mode !== 'live' || !(workspace.discovery.plan_ready ?? workspace.discovery.ready);
  $('brief-reset').disabled = !idle || briefSubmitting;
  $('discovery-prompt').disabled = !idle || briefSubmitting;
  $('discover').disabled = !idle || !(workspace.discovery.plan_ready ?? workspace.discovery.ready);
  const plan = researchState?.plan;
  const changed = Boolean(plan) && (plan.prompt !== $('discovery-prompt').value.trim() || plan.limit !== Number($('discovery-limit').value) || Boolean(plan.web_first) !== $('discovery-web-first').checked || Boolean(plan.recheck_failed) !== $('discovery-recheck').checked || (plan.profile_url || '') !== $('discovery-profile').value.trim());
  const blocked = !connected ? 'Connect your workspace first.'
    : researchSubmitting ? 'Starting research…'
    : workspace.busy ? 'Wait for the current job to finish.'
    : !plan ? 'Prepare a research plan first.'
    : !workspace.discovery.ready ? workspace.discovery.reason || 'Complete the research connections first.'
    : changed ? 'This button runs the reviewed plan shown above. Your edited form is different; prepare a new plan to use those edits.'
    : !$('research-history').checked ? 'Confirm the CRM history checkbox above to continue.' : '';
  // Only local prerequisites disable submission. Server checks current auth,
  // account, restrictions and job ownership and returns the precise failure.
  $('research-start').disabled = !connected || researchSubmitting || !plan || !$('research-history').checked;
  $('research-start').textContent = plan ? 'Start reviewed plan (' + plan.limit + ')' : 'Start research';
  $('research-start-help').textContent = blocked || 'Ready. Start research will browse profiles and save candidates to your local CRM.';
  $('research-start-browser').hidden = !connected || workspace.mode !== 'live';
  $('research-use-plan').hidden = !changed;
  $('research-use-plan').disabled = !idle;
  $('research-stop').disabled = !connected || !workspace.busy;
  $('sync').disabled = !idle || workspace.mode !== 'live' || !workspace.sheets_configured;
  $('check-browser').disabled = !connected || browserChecking;
  $('open-browser').disabled = !browserState?.available;
  $('login').disabled = !idle || workspace.mode !== 'live' || !browserState?.available || Boolean(workspace.linkedin_restriction);
  $('reset-browser').disabled = !idle || workspace.mode !== 'live';
  for (const id of ['codex-login', 'codex-key-save', 'codex-check', 'codex-logout', 'codex-cancel', 'jev-save', 'jev-check', 'jev-disconnect', 'google-login', 'google-disconnect', 'google-create', 'google-select']) $(id).disabled = !idle || connectionBusy;
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
    const [status, leads, replies, jobs, authState, discoveryState] = await Promise.all(['status', 'records/leads', 'records/replies', 'records/jobs', 'connections', 'discovery/state'].map(p => api(p)));
    connections = authState; researchState = discoveryState;
    workspace = status;
    $('mode').textContent = status.mode === 'demo' ? 'Demo · fictional data' : 'Live workspace';
    $('status').textContent = (status.busy ? 'A job is running. ' : 'Ready. ') + 'Daily action limit: ' + status.daily_limit + ' (UTC).';
    $('account-name').textContent = 'Your signed-in browser';
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
    if (researchState.plan) $('plan-summary').textContent = researchState.plan.summary;
    if (researchState.plan) $('research-plan-text').textContent = (researchState.plan.web_first ? 'Web first → LinkedIn confirmation\n\n' : 'LinkedIn discovery\n\n') + 'Recheck prior evidence failures: '+Boolean(researchState.plan.recheck_failed)+'\nSpecific profile: '+(researchState.plan.profile_url || 'None')+'\n\nYour brief: ' + researchState.plan.prompt + '\n\n' + researchState.plan.summary + '\n\nSearches:\n' + researchState.plan.queries.join('\n') + '\n\nTarget: ' + researchState.plan.limit + ' · Max profile visits: ' + researchState.plan.max_profiles + ' · Max minutes: ' + researchState.plan.max_minutes;
    $('research-progress').textContent = researchState.events.length ? researchState.events.slice(0,20).map(e => { const detail=JSON.parse(e.detail); return e.kind.replaceAll('_',' ') + ': ' + (detail.reason || detail.query || detail.url || (detail.staged !== undefined ? detail.staged + ' candidates saved for review' : 'Research started')); }).join('\n') : researchState.plan ? 'Your plan is prepared. Complete the step shown beside Start research.' : 'No research has started yet. Prepare a plan to begin.';
    $('sheets-state').textContent = status.sheets_configured ? 'Configured' : 'Optional';
    $('access-help').textContent = 'Workspace unlocked. Your password is held only in this tab’s memory.';
    $('leads').replaceChildren();
    if (!leads.length) { const row = $('leads').insertRow(); const cell = row.insertCell(); cell.colSpan = 4; cell.className = 'empty'; cell.textContent = 'No candidates yet. Start with Find leads.'; }
    for (const lead of leads) {
      const tr = document.createElement('tr');
      for (const value of [lead.name, lead.company + ' / ' + lead.role, lead.status]) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
      const td = document.createElement('td'), button = document.createElement('button');
      button.textContent = lead.status === 'approved' ? 'Send approved note' : 'Review';
      button.disabled = status.busy || !['review', 'approved'].includes(lead.status);
      button.onclick = () => run(async () => {
        if (lead.status === 'approved') {
          if (confirm('Send this reviewed invitation to ' + lead.name + '?\n\n' + lead.note + '\n\n' + (workspace.mode === 'demo' ? 'Demo: simulated only.' : 'This sends a real invitation.'))) await api('outreach', { lead_ids: [lead.id], confirm: true });
        } else { const note = prompt('Source evidence: ' + lead.evidence + '\n\nReview the profile and enter a note (max 200 characters).'); if (note) await api('leads/' + lead.id + '/approve', { note }); }
        await refresh();
      });
      const a = document.createElement('a'); a.href = lead.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = 'Profile ↗'; td.append(button, a); tr.append(td); $('leads').append(tr);
    }
    $('replies').textContent = replies.length ? replies.map(r => (leads.find(l => l.id === r.lead_id)?.name || r.lead_id) + ' · ' + r.received + '\n' + r.body).join('\n\n') : 'No replies recorded yet.';
    $('jobs').textContent = jobs.length ? jobs.slice().reverse().map(j => j.kind + ' · ' + j.status + ' · ' + j.created + '\n' + j.result).join('\n\n') : 'No jobs yet.';
    renderWorkspace();
    controls();
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
    $('browser-help').open = !browserState.available || workspace.mode === 'demo';
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
$('access-form').onsubmit = event => { event.preventDefault(); run(async () => { token = $('token').value; $('token').value = ''; workspace = null; browserState = null; await refresh(); showView(workspace.mode === 'demo' || workspace.discovery.ready ? 'discovery' : !connections.codex.signed_in ? 'connections' : 'browser-section'); await checkBrowser(); }); };
$('refresh').onclick = () => run(refresh);
$('expand-browser').onclick = () => run(async () => { await $('browser-stage').requestFullscreen(); });
$('check-browser').onclick = () => run(checkBrowser);
$('open-browser').onclick = () => run(async () => { await checkBrowser(); openViewer(); });
$('login').onclick = () => run(async () => { await checkBrowser(); openViewer(); await browserJob('linkedin/login', {}, 'Opening LinkedIn in your browser…', 'LinkedIn is open below. Sign in and complete any LinkedIn prompts, then return to Research.'); });
$('reset-browser').onclick = () => run(async () => { if (!confirm('Restart the browser container first. Reset its saved connection now? Cookies are preserved and invitations will not be retried.')) return; await browserJob('linkedin/reset', {}, 'Resetting the browser connection…', 'Connection reset. Open LinkedIn sign-in again.'); });
$('discover').onclick = () => run(async () => { const prompt = $('discovery-prompt').value.trim(); if (prompt.length < 2) throw Error('Describe the people you want to research first.'); const limit = Number($('discovery-limit').value); if (!Number.isInteger(limit) || limit < 1 || limit > 10) throw Error('Choose a target between 1 and 10.'); $('research-history').checked=false; await api(workspace.mode === 'demo' ? 'discover' : 'discovery/plan', { prompt, limit, web_first:$('discovery-web-first').checked,recheck_failed:$('discovery-recheck').checked,profile_url:$('discovery-profile').value.trim() }); await refresh(); });
$('read').onclick = () => run(async () => { await api('replies/read', { limit: 100 }); await refresh(); });
$('sync').onclick = () => run(async () => { await api('sheets/sync', {}); await refresh(); });
setInterval(() => { if (token && workspace) run(refresh); }, 5000);

function renderConnections() {
  const c = connections.codex, j = connections.jev, g = connections.google;
  $('google-message').textContent = g.connected ? 'Google connected. Create or sync your CRM spreadsheet below.' : g.message || 'Google is not connected.';
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

$('research-use-plan').onclick = () => { if (!researchState?.plan) return; $('discovery-prompt').value=researchState.plan.prompt; $('discovery-limit').value=researchState.plan.limit; $('discovery-web-first').checked=Boolean(researchState.plan.web_first); $('discovery-recheck').checked=Boolean(researchState.plan.recheck_failed); $('discovery-profile').value=researchState.plan.profile_url || ''; $('research-history').checked=false; controls(); };

// Navigate between focused screens without recreating the browser or form state.
const workspaceViews = ['discovery', 'browser-section', 'connections', 'outreach', 'inbox', 'activity'];
function showView(id) {
  const selected = workspaceViews.includes(id) ? id : 'discovery';
  if (workspace && window.location.hash !== '#' + selected) history.replaceState(null, '', '#' + selected);
  const watching = Boolean(workspace) && workspace.mode === 'live' && selected === 'discovery';
  $('research-workspace').classList.toggle('watching', watching);
  for (const view of workspaceViews) $(view).hidden = !workspace || (view !== selected && !(watching && view === 'browser-section'));
  document.querySelectorAll('.sidebar nav a').forEach(link => {
    if (link.hash === '#' + selected) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
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
    if (!$('discovery-prompt').value.trim()) {
      $('discovery-prompt').value = researchState.plan.prompt; $('discovery-web-first').checked=Boolean(researchState.plan.web_first); $('discovery-recheck').checked=Boolean(researchState.plan.recheck_failed); $('discovery-profile').value=researchState.plan.profile_url || '';
      $('discovery-limit').value = researchState.plan.limit;
    }
    $('research-brief').open = false;
    $('research-brief').dataset.planId = planId;
  }
  showView(window.location.hash.slice(1));
}
window.addEventListener('hashchange', () => showView(window.location.hash.slice(1)));
showView(window.location.hash.slice(1));

function researchLaunchMessage(job) {
  const result = JSON.parse(job.result || '{}');
  if (job.status === 'running') return 'Research is running. Open Research activity for progress or Browser to watch.';
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
  const names={web_fallback:'Checking missing evidence on the web',rechecking:'Rechecking prior evidence failure',web_search:'Searching the web',web_source:'Reading primary source',web_shortlist:'Web shortlist ready',web_excluded:'Excluded before LinkedIn',started:'Run started',checking_browser:'Checking browser',searching:'Searching LinkedIn',search:'Search results',ranking:'Prioritizing with Jev',prioritized:'First profile in research order',visiting:'Opening profile',selecting_employer:'Finding the current employer',employer_selected:'Checking company',qualifying:'Evaluating fit with Codex',staged_for_review:'Saved for your review',insufficient_evidence:'Skipped: evidence did not qualify',current_employer_unclear:'Skipped: employer unclear',company_replied_or_held:'Skipped: company excluded',previously_visited_or_reserved:'Skipped: previously visited',known_contact:'Skipped: already in CRM',own_profile:'Skipped: your own profile',duplicate:'Skipped: duplicate',stopped:'Research stopped',finished:'Run finished'};
  let text=d.reason || '';
  if(event.kind==='started')text='Target: '+d.plan.limit+' candidates. '+d.plan.summary;
  if(event.kind==='search')text=d.observed_profiles+' profile links observed for '+d.query;
  if(event.kind==='finished')text=d.staged+' saved · '+d.visited+' profiles visited · '+d.seconds+' seconds. '+(d.reason || '').replaceAll('_',' ');
  if(event.kind==='previously_visited_or_reserved')text='Already inspected or reserved by a prior run; not revisited automatically.';
  if(event.kind==='known_contact')text='This profile is already in your local CRM.';
  return {title:names[event.kind] || event.kind.replaceAll('_',' '),text,query:d.query,url:d.url,quote:d.role_quote};
}
function renderDecisions() {
  const events=researchState?.events || [];
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

$('discovery-web-first').onchange = controls;

$('discovery-recheck').onchange=controls;
$('discovery-profile').oninput=controls;
