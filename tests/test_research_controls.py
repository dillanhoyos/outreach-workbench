"""Exercise the actual button logic without contacting any provider."""
import shutil
import subprocess
from pathlib import Path
import pytest

@pytest.mark.skipif(not shutil.which('node'),reason='Node is required for UI logic checks')
def test_start_research_explains_each_gate():
    script=Path('src/workbench/static/workbench.js').read_text()
    controls=script[script.index('function controls()'):script.index('async function refresh()')]
    code='''const assert=require('node:assert/strict');
const nodes={}; const $=id=>nodes[id]??=( {value:'',checked:false,hidden:false,disabled:false,textContent:''} );
let workspace={mode:'live',busy:false,account:null,discovery:{ready:false,reason:'Sign in to Codex.'}};
let researchState={plan:{prompt:'Find founders',limit:3}};
let browserState=null,browserChecking=false,connectionBusy=false,connections=null,researchSubmitting=false,briefSubmitting=false;
$('discovery-prompt').value='Find founders';$('discovery-limit').value='3';$('discovery-minutes').value='15';$('research-history').checked=true;
'''+controls+'''
controls();assert.equal($('research-start').disabled,false);
assert.match($('research-start-help').textContent,/Sign in to Codex/);
assert.equal($('research-start-browser').hidden,false);
workspace.account={name:'Fixture'};workspace.discovery.ready=true;
$('discovery-prompt').value='';controls();
assert.equal($('research-start').disabled,false);assert.match($('research-start-help').textContent,/edited form/);
assert.equal($('research-use-plan').hidden,false);
$('discovery-prompt').value='Find founders';$('research-history').checked=false;controls();
assert.match($('research-start-help').textContent,/checkbox/);
$('research-history').checked=true;controls();assert.equal($('research-start').disabled,false);
$('discovery-minutes').value='30';controls();assert.match($('research-start-help').textContent,/edited form/);assert.match($('research-adjust-time').textContent,/30 min/);
$('discovery-minutes').value='15';
workspace.busy=true;controls();assert.equal($('research-adjust-time').disabled,true);assert.match($('research-start-help').textContent,/current job/);assert.equal($('research-start').disabled,false);
researchSubmitting=true;controls();assert.equal($('research-start').disabled,true);researchSubmitting=false;
workspace=null;controls();assert.match($('research-start-help').textContent,/Connect your workspace/);
'''
    subprocess.run(['node','-e',code],check=True,capture_output=True,text=True)

@pytest.mark.skipif(not shutil.which('node'), reason='Node is required for UI logic checks')
def test_modes_keep_browser_mounted_and_sidebar_preserves_work():
    script=Path('src/workbench/static/workbench.js').read_text()
    navigation=script[script.index("let composerRestored="):script.index('function renderWorkspace()')]
    code="""const assert=require('node:assert/strict');
const nodes={};const $=id=>nodes[id]??={hidden:false,value:'saved draft',append(){},classList:{add(){}}};
let workspace=null;
const window={location:{hash:''}};
const history={replaceState:(_,__,hash)=>window.location.hash=hash};
const links=['discovery','compose','connections'].map(id=>({hash:'#'+id,setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]}}));
const document={querySelectorAll:()=>links};
""" + navigation + """
showView('discovery');assert.equal($('research-workspace').hidden,true);
workspace={mode:'live'};showView('discovery');
assert.equal($('browser-section').hidden,false);assert.equal($('discovery').hidden,false);
showView('connections');
assert.equal($('connections').hidden,false);assert.equal($('discovery').hidden,false);assert.equal($('browser-section').hidden,false);
showView('compose');assert.equal($('outreach-start').hidden,false);assert.equal($('discovery').hidden,true);
composeLead={id:'fixture'};showView('compose');assert.equal($('composer').hidden,false);
showView('activity');assert.equal($('composer').hidden,false);assert.equal($('browser-section').hidden,false);
showView('discovery');assert.equal($('discovery').value,'saved draft');
assert.equal($('composer').hidden,true);
"""
    subprocess.run(['node','-e',code],check=True,capture_output=True,text=True)

@pytest.mark.skipif(not shutil.which('node'), reason='Node is required for UI logic checks')
def test_research_result_distinguishes_stopped_worker_from_success():
    script = Path('src/workbench/static/workbench.js').read_text()
    code = "const assert=require('node:assert/strict');\n" + script[script.index('function researchLaunchMessage('):script.index('function renderBrief(')] + '''
assert.match(researchLaunchMessage({status:'completed',result:JSON.stringify({staged:0,reason:'LinkedIn sign-in or verification required.'})}), /^Research stopped: 0 candidates saved. LinkedIn sign-in/);
assert.match(researchLaunchMessage({status:'completed',result:JSON.stringify({staged:3,reason:'target_reached'})}), /^Research finished: 3 candidates saved/);
assert.match(researchLaunchMessage({status:'interrupted',result:'{}'}), /Research stopped: interrupted/);
assert.match(researchLaunchMessage({status:'running',result:'{}'}), /Research is running/);
'''
    subprocess.run(['node', '-e', code], check=True, capture_output=True, text=True)
