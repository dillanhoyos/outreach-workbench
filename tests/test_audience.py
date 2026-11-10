import copy
from threading import Timer as RealTimer
import json
import pytest
pytestmark=pytest.mark.usefixtures("fixture_web")
from workbench.audience import lock,valid,checklist,Check
from workbench.errors import ProviderError
from test_research import setup,model,PERSON,PROFILE

CRITERIA=[{'requirement':'YC S24','scope':'company','source':'company'},
          {'requirement':'Founder at current company','scope':'person','source':'either'},
          {'requirement':'Currently employed at company','scope':'person','source':'profile'}]


def test_locked_contract_detects_requirement_and_brief_changes():
    audience=lock('S24 founders',CRITERIA)
    assert valid(audience,'S24 founders')
    altered=copy.deepcopy(audience);altered['criteria'][0]['requirement']='Any YC batch'
    assert not valid(altered,'S24 founders')
    assert not valid(audience,'S25 founders')


def test_founder_source_policy_is_consistent_and_requires_all_criteria():
    audience=lock('S24 founders',CRITERIA)
    profile={'url':PROFILE,'text':'CEO at Example'}
    company={'url':'https://example.org','text':'YC S24. Active founder Jane, Example.'}
    checks=[Check(criterion_id='c1',status='pass',reason='batch',evidence=[{'source':'company','quote':'YC S24'}]),
            Check(criterion_id='c2',status='pass',reason='founder',evidence=[{'source':'company','quote':'Active founder Jane, Example.'}]),
            Check(criterion_id='c3',status='pass',reason='current role',evidence=[{'source':'profile','quote':'CEO at Example'}])]
    assert all(x['status']=='pass' for x in checklist(audience,checks,profile,company))
    assert any(x['status']=='missing' for x in checklist(audience,checks[:-1],profile,company))
    assert all(x['status']=='missing' for x in checklist(audience,checks+[checks[0]],profile,company))
    checks[2].evidence[0].source='company';checks[2].evidence[0].quote='YC S24'
    assert checklist(audience,checks,profile,company)[2]['status']=='missing'
    checks[0].evidence[0].quote='YC S25'
    assert checklist(audience,checks,profile,company)[0]['status']=='missing'


def test_missing_check_blocks_save_despite_model_qualified(tmp_path):
    def missing(*args):
        result=model(*args)
        if args[3]['title']=='Candidate':result['checks']=[]
        return result
    store,browser,engine,plan=setup(tmp_path,missing)
    result=engine.run(plan['id'],True)
    assert result['staged']==0 and not store.list('leads')
    records=engine.crm_records()
    assert records[0]['checklist'][0]['status']=='missing'
    assert records[0]['assessments'][0]['checklist'][0]['status']=='missing'


def test_tampered_plan_stops_before_browser(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    plan['audience']['criteria'][0]['requirement']='Anybody'
    store.setting('research_plan',plan)
    with pytest.raises(ProviderError,match='locked'):engine.run(plan['id'],True)
    assert browser.visits==0


def test_recommendation_is_bounded_hint_with_provenance(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    engine._locked_audience=plan['audience'];engine._recommended=[];engine._recommendation_seen=set()
    def pick(auth,task,data,schema,stop):
        assert data['audience']==plan['audience']
        return {'indices':[0,99]}
    engine.model=pick
    profile={'url':PROFILE,'recommendations':[{'url':'https://www.linkedin.com/in/another/','label':'Accounting director'}]}
    engine.recommendations(plan,'r',profile)
    assert len(engine._recommended)==1
    assert engine._recommended[0]['needs_primary_evidence']
    assert engine._recommended[0]['origin']['parent_profile']==PROFILE
    assert not store.list('leads')
    engine.recommendations(plan,'r',profile)
    assert len(engine._recommended)==1


def test_browser_keeps_recommendations_separate_and_rejects_external_urls():
    from types import SimpleNamespace
    from workbench.research_browser import ResearchBrowser
    driver=SimpleNamespace(current_url=PROFILE,execute_script=lambda *args:[
        {'url':'https://www.linkedin.com/in/next/?tracking=1','label':'Founder at Example'},
        {'url':'https://example.org/person','label':'External'},
        {'url':PROFILE,'label':'Self'}])
    browser=ResearchBrowser(SimpleNamespace(browser=lambda:driver))
    browser.snapshot=lambda url:{'url':PROFILE,'title':'Person','headline':'CEO at Original','text':'CEO at Original','links':[]}
    profile=browser.profile(PROFILE)
    assert profile['recommendations']==[{'url':'https://www.linkedin.com/in/next/','label':'Founder at Example'}]
    assert 'Example' not in profile['text'] and profile['companies']==[]


def test_recommended_profiles_follow_full_pipeline_and_save_same_checklist(tmp_path,monkeypatch):
    monkeypatch.setattr('workbench.research.threading.Timer',lambda interval,callback:RealTimer(min(interval,5),callback))
    from test_research import COMPANY
    store,browser,engine,plan=setup(tmp_path)
    children=['https://www.linkedin.com/in/recommended-a/','https://www.linkedin.com/in/recommended-b/']
    original=browser.profile
    def profile(url):
        p=original(url);p['url']=url
        p['recommendations']=[{'url':u,'label':'Accounting director'} for u in children] if url==PROFILE else []
        return p
    browser.profile=profile
    def reasoner(*args):
        return {'indices':[0,1]} if args[3]['title']=='Recommendations' else model(*args)
    engine.model=reasoner
    calls=[]
    def web(worker,p,*args,**kw):
        assert p['audience']==plan['audience']
        url=p.get('target_profile',PROFILE);calls.append(url)
        return [{'url':url,'label':'Fixture','web_company':browser.company(COMPANY)}]
    monkeypatch.setattr('workbench.research_web.discover',web)
    report=engine.run(plan['id'],True)
    assert report['staged']==3 and report['visited']==3
    assert set(children).issubset(calls)
    rows=engine.crm_records()
    assert all(row['audience_id']==plan['audience']['id'] for row in rows)
    assert all(all(c['status']=='pass' for c in row['checklist']) for row in rows)
    assert sum(bool(row['origin']) for row in rows)==2
