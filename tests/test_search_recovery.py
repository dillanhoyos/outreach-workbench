from threading import Timer
import pytest
from test_research import setup,model,PROFILE,COMPANY
from workbench.research import linkedin_keywords


def test_linkedin_query_strips_web_operators_not_audience_terms():
    assert linkedin_keywords('site:linkedin.com/in blockchain "AI" "2026"')=='blockchain "AI" "2026"'
    assert linkedin_keywords('founder inurl:profile intitle:"CEO" filetype:pdf sandbox')=='founder sandbox'


def test_browser_results_are_not_discarded_after_first_visit(tmp_path,monkeypatch):
    monkeypatch.setattr('workbench.research.threading.Timer',lambda interval,callback:Timer(5,callback))
    store,browser,engine,plan=setup(tmp_path)
    urls=[f'https://www.linkedin.com/in/result-{i}/' for i in range(3)];queries=[]
    def search(query):queries.append(query);return {'url':'https://www.linkedin.com/search/results/people/'},[{'url':u,'label':'Accounting director'} for u in urls]
    browser.search=search
    def web(worker,p,*a,**kw):
        return [{'url':p['target_profile'],'label':'Verified','web_company':browser.company(COMPANY)}] if p.get('target_profile') else []
    monkeypatch.setattr('workbench.research_web.discover',web)
    result=engine.run(plan['id'],True)
    assert result['staged']==3 and result['visited']==3
    assert len(queries)==1
    assert {x['url'] for x in store.list('leads')}==set(urls)


def test_revised_linkedin_query_is_used_with_same_audience(tmp_path,monkeypatch):
    monkeypatch.setattr('workbench.research.threading.Timer',lambda interval,callback:Timer(5,callback))
    store,browser,engine,plan=setup(tmp_path);plan['limit']=1
    plan['linkedin_query']='site:linkedin.com/in founder old';store.setting('research_plan',plan)
    engine.reserve(PROFILE,'old-run');queries=[];fresh='https://www.linkedin.com/in/fresh-result/'
    def search(query):
        queries.append(query)
        return {'url':'https://www.linkedin.com/search/results/people/'},[{'url':PROFILE if len(queries)==1 else fresh,'label':'Founder'}]
    browser.search=search
    def reasoner(*args):
        answer=model(*args)
        if args[3]['title']=='Plan':
            assert args[2]['audience']==plan['audience']
            assert args[2]['previous_linkedin_queries']==['founder old']
            answer['linkedin_query']='site:linkedin.com/in founder new'
        return answer
    engine.model=reasoner
    monkeypatch.setattr('workbench.research_web.discover',lambda worker,p,*a,**kw:[{'url':fresh,'label':'Verified','web_company':browser.company(COMPANY)}] if p.get('target_profile') else [])
    result=engine.run(plan['id'],True)
    assert result['staged']==1 and queries==['founder old','founder new']


def test_web_exclusions_honor_recheck_but_keep_known_and_current_run_profiles(tmp_path,monkeypatch):
    from workbench.research_web import discover
    store,browser,engine,plan=setup(tmp_path)
    failed='https://www.linkedin.com/in/failed-evidence/'
    held='https://www.linkedin.com/in/reserved/'
    known='https://www.linkedin.com/in/known/'
    store.add_lead({'name':'Known','role':'CFO','company':'Known Co','country':'Colombia','url':known,'evidence':'fixture'})
    engine.reserve(failed,'prior');engine.reserve(held,'prior')
    with store.db() as db:db.execute("UPDATE research_visits SET state='insufficient_evidence' WHERE url=?",(failed,))
    engine.remember(failed,'insufficient_evidence',{},'prior','Earlier audience')
    inputs=[]
    def reason(auth,task,data,*a,**kw):inputs.append(data);return {'prospects':[]}
    monkeypatch.setattr('workbench.research_web.reason',reason)
    plan={**plan,'exclude_visited':True,'recheck_failed':True}
    discover(engine,plan,'current',lambda:None)
    assert failed not in inputs[-1]['known_profiles']
    assert known in inputs[-1]['known_profiles'] and held in inputs[-1]['known_profiles']
    discover(engine,{**plan,'recheck_failed':False},'current',lambda:None)
    assert failed in inputs[-1]['known_profiles']
    discover(engine,plan,'prior',lambda:None)
    assert failed in inputs[-1]['known_profiles']


def test_exhausted_linkedin_query_is_not_repeated(tmp_path,monkeypatch):
    monkeypatch.setattr('workbench.research.threading.Timer',lambda interval,callback:Timer(5,callback))
    store,browser,engine,plan=setup(tmp_path);calls=[];revisions=[]
    def search(query):calls.append(query);return {'url':'https://www.linkedin.com/search/results/people/'},[]
    browser.search=search
    def reasoner(*args):
        if args[3]['title']=='Plan':
            revisions.append(1)
            if len(revisions)==2:engine.stop.set()
        return model(*args)
    engine.model=reasoner
    monkeypatch.setattr('workbench.research_web.discover',lambda *a,**kw:[])
    result=engine.run(plan['id'],True)
    assert len(calls)==1 and result['staged']==0
    with store.db() as db:assert db.execute("SELECT 1 FROM research_events WHERE kind='query_exhausted'").fetchone()
