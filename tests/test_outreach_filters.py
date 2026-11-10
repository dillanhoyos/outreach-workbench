import shutil
import subprocess
from pathlib import Path
import pytest


@pytest.mark.skipif(not shutil.which('node'),reason='Node required')
def test_filters_combine_without_changing_send_eligibility():
    source=Path('src/workbench/static/workbench.js').read_text()
    fn=source[source.index('function recipientMatches('):source.index('function matchingRecipients(')]
    code="""const assert=require('node:assert/strict');
""" + fn + """
const lead={id:'one',name:'José',role:'Accounting Director',company:'Roads',country:'Colombia',campaign_id:'c1',qualification:'qualified',outreach_available:true,status:'review',outreach_status:'not_contacted'};
const selected=new Set(['one']);
assert(recipientMatches(lead,{},selected));
assert(recipientMatches(lead,{'recipient-search':'jose','recipient-country':'Colombia','recipient-company':'Roads','recipient-campaign':'c1','recipient-fit':'qualified','recipient-selected':true},selected));
for(const [key,value] of [['recipient-country','Mexico'],['recipient-company','Other'],['recipient-campaign','c2'],['recipient-fit','missing_evidence'],['recipient-search','CEO']]){
 assert(!recipientMatches(lead,{[key]:value},selected),key);
}
assert(!recipientMatches(lead,{'recipient-selected':true},new Set()));
const blocked={...lead,outreach_available:false,status:'blocked',outreach_status:'blocked'};
assert(!recipientMatches(blocked,{},selected));
assert(recipientMatches(blocked,{'recipient-status':'blocked'},selected));
assert(recipientMatches(blocked,{'recipient-status':'all'},selected));
assert(!recipientMatches(blocked,{'recipient-status':'confirmed'},selected));
assert.equal(blocked.outreach_available,false);
const archived={...lead,id:'visited:two',outreach_available:false,qualification:'missing_evidence'};
assert(recipientMatches(archived,{'recipient-status':'all','recipient-fit':'missing_evidence'},selected));
assert(!recipientMatches(archived,{'recipient-fit':'missing_evidence'},selected));
"""
    subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
