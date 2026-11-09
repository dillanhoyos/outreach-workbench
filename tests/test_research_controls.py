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
let workspace={mode:'live',busy:false,account:null,discovery:{ready:false,reason:'Verify your LinkedIn account.'}};
let researchState={plan:{prompt:'Find founders',limit:3}};
let browserState=null,browserChecking=false,connectionBusy=false,connections=null;
$('discovery-prompt').value='Find founders';$('discovery-limit').value='3';$('research-history').checked=true;
'''+controls+'''
controls();assert.equal($('research-start').disabled,true);
assert.match($('research-start-help').textContent,/Verify your LinkedIn/);
assert.equal($('research-start-browser').hidden,false);
workspace.account={name:'Fixture'};workspace.discovery.ready=true;
$('discovery-prompt').value='';controls();
assert.equal($('research-start').disabled,true);assert.match($('research-start-help').textContent,/differs/);
assert.equal($('research-use-plan').hidden,false);
$('discovery-prompt').value='Find founders';$('research-history').checked=false;controls();
assert.match($('research-start-help').textContent,/checkbox/);
$('research-history').checked=true;controls();assert.equal($('research-start').disabled,false);
workspace.busy=true;controls();assert.match($('research-start-help').textContent,/current job/);
workspace=null;controls();assert.match($('research-start-help').textContent,/Connect your workspace/);
'''
    subprocess.run(['node','-e',code],check=True,capture_output=True,text=True)
