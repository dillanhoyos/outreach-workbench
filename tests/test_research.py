import copy
import json
from types import SimpleNamespace
import pytest
from workbench.research import Discovery
from workbench.research_browser import research_url
from workbench.store import Store
from workbench.errors import ProviderError

PROFILE='https://www.linkedin.com/in/fictional-finance/'
COMPANY='https://www.linkedin.com/company/fictional-roads/about/'
PERSON={'name':'Fictional Person','company':'Fictional Roads','role':'Accounting Director','country':'Colombia',
        'qualified':True,'current_role_quote':'Accounting Director Fictional Roads 2024 – Present',
        'location_quote':'Bogotá Colombia','sector_quote':'Fictional Roads operates road concessions',
        'reason':'Current accounting role at a road concession operator in Colombia.'}

class Browser:
    def __init__(self):self.visits=0;self.fail=False
    def ensure_ready(self):return {'name':'Test operator'}
    def search(self,query):return {'url':'https://www.linkedin.com/search/results/people/'},[{'url':PROFILE,'label':'Accounting Director'}]
    def profile(self,url):
        self.visits+=1
        if self.fail:raise ProviderError('LinkedIn returned HTTP 429. Work stopped without retry.')
        return {'url':PROFILE,'title':'Fictional Person','text':PERSON['current_role_quote']+' '+PERSON['location_quote'],
                'companies':[{'url':COMPANY,'label':'Fictional Roads'}]}
    def company(self,url):return {'url':COMPANY,'title':'Fictional Roads','text':PERSON['sector_quote']}

def model(auth,task,data,schema,stop):
    return {'Plan':{'summary':'Find current accounting professionals','queries':['accounting road concessions Colombia']},
            'Employer':{'company_url':COMPANY,'reason':'Current employer'},'Candidate':dict(PERSON)}[schema['title']]

def setup(tmp_path,reasoner=model):
    store=Store(tmp_path);browser=Browser();engine=Discovery(store,None,browser,model=reasoner)
    plan=engine.prepare('Find accounting professionals at Colombian road concessions',3)
    return store,browser,engine,plan

def test_discovery_stages_evidence_and_never_sends(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    result=engine.run(plan['id'],True)
    assert result['staged']==1 and result['visited']==1
    lead=store.list('leads')[0]
    assert lead['status']=='review' and lead['role']=='Accounting Director'
    assert json.loads(lead['evidence'])['company_url']==COMPANY
    assert store.list('deliveries')==[]
    again=engine.run(plan['id'],True)
    assert again['staged']==0 and browser.visits==1

def test_fresh_company_reply_blocks_staging(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    store.add_lead({'name':'Prior Person','role':'CFO','company':'Fictional Roads','country':'Colombia',
                    'url':'https://www.linkedin.com/in/fictional-prior/','evidence':'fixture'})
    def reply_during_assessment(auth,task,data,schema,stop):
        if schema['title']=='Candidate':
            store.reply('fixture-reply',store.list('leads')[0]['id'],'Hello','2026-01-01','fixture')
        return model(auth,task,data,schema,stop)
    engine.model=reply_during_assessment
    result=engine.run(plan['id'],True)
    assert result['staged']==0 and len(store.list('leads'))==1
    assert any(e['kind']=='company_replied_or_held' for e in engine.state()['events'])

def test_interrupted_profile_stays_reserved_and_no_retry(tmp_path):
    store,browser,engine,plan=setup(tmp_path);browser.fail=True
    assert '429' in engine.run(plan['id'],True)['reason']
    browser.fail=False
    assert engine.run(plan['id'],True)['staged']==0
    assert browser.visits==1
    with store.db() as db:assert db.execute('SELECT state FROM research_visits').fetchone()[0]=='reserved'

def test_missing_history_and_stop_prevent_browsing(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    with pytest.raises(ProviderError,match='CRM'):engine.run(plan['id'],False)
    engine.stop.set()
    assert 'stopped by you' in engine.run(plan['id'],True)['reason']
    assert browser.visits==0

@pytest.mark.parametrize('field,value', [('current_role_quote','Invented current role'),('name','Wrong person'),
    ('sector_quote','Invented sector'),('current_role_quote','Accounting Director Fictional Roads 2018 – 2020')])
def test_fabricated_or_past_evidence_rejected(tmp_path,field,value):
    def bad_model(*args):
        answer=model(*args)
        if args[3]['title']=='Candidate':answer[field]=value
        return answer
    store,browser,engine,plan=setup(tmp_path,bad_model)
    assert engine.run(plan['id'],True)['staged']==0
    assert not store.list('leads')

@pytest.mark.parametrize('url', ['http://www.linkedin.com/in/example/','https://evil.example/in/example/',
    'https://www.linkedin.com@evil.example/in/example/','https://localhost/in/example/',
    'https://www.linkedin.com/messaging/','https://www.linkedin.com:8443/in/example/'])
def test_research_navigation_rejects_other_hosts_actions_and_ports(url):
    with pytest.raises(ValueError):research_url(url,'profile')
