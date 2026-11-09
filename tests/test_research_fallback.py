import pytest
pytestmark = pytest.mark.usefixtures("fixture_web")
import json
import pytest
from test_research import setup, model, PERSON, PROFILE, COMPANY
from workbench import research_web


def test_missing_company_fact_uses_web_and_saves_only_matching_profile(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    plan['profile_url']=PROFILE;store.setting('research_plan',plan)
    calls=[]
    def missing_first(*args):
        result=model(*args)
        if args[3]['title']=='Candidate':
            public='company_criteria_quotes' in args[2]['company']
            result.update(qualified=public,needs_web_evidence=not public)
        return result
    def fallback(*args):
        calls.append(1)
        return [{'url':PROFILE,'label':'Fixture','web_company':{**browser.company(COMPANY),
            'company_criteria_quotes':['Summer 2024'],'company_assessment':'Fixture'}}]
    engine.model=missing_first
    monkeypatch.setattr(research_web,'discover',fallback)
    assert engine.run(plan['id'],True)['staged']==1
    assert calls==[1] and browser.visits==1
    assert store.list('leads')[0]['status']=='review'
    assert not store.list('deliveries')


def test_confirmed_mismatch_does_not_trigger_second_web_search(tmp_path,monkeypatch):
    def mismatch(*args):
        answer=model(*args)
        if args[3]['title']=='Candidate':answer.update(qualified=False,needs_web_evidence=False)
        return answer
    store,browser,engine,plan=setup(tmp_path,mismatch)
    plan['profile_url']=PROFILE;store.setting('research_plan',plan)
    calls=[]
    monkeypatch.setattr(research_web,'discover',lambda *a:calls.append(1) or [])
    assert engine.run(plan['id'],True)['staged']==0
    assert calls==[1]


@pytest.mark.parametrize('state,allowed',[('insufficient_evidence',True),('current_employer_unclear',True),('reserved',False),('company_replied_or_held',False),('staged_for_review',False)])
def test_recheck_only_completed_evidence_failures_and_preserves_history(tmp_path,state,allowed):
    store,browser,engine,plan=setup(tmp_path)
    assert engine.reserve(PROFILE,'original')==''
    with store.db() as db:db.execute('UPDATE research_visits SET state=?,evidence=?',(state,json.dumps({'old':'evidence'})))
    assert engine.reserve(PROFILE,'new')=='previously_visited_or_reserved'
    assert (engine.reserve(PROFILE,'new',True)=='') is allowed
    assert engine.reserve(PROFILE,'new',True)=='previously_visited_or_reserved'
    if allowed:
        detail=json.loads(engine.state()['events'][0]['detail'])
        assert detail['previous_evidence']=={'old':'evidence'}


def test_known_contact_not_rechecked(tmp_path):
    store,browser,engine,plan=setup(tmp_path)
    store.add_lead({**PERSON,'url':PROFILE,'evidence':'fixture'})
    assert engine.reserve(PROFILE,'new',True)=='known_contact'


def test_candidate_schema_requires_every_field_for_codex():
    from workbench.research import Candidate
    schema=Candidate.model_json_schema()
    assert set(schema['required'])==set(schema['properties'])


def test_explicit_recheck_runs_prior_failure_and_saves(tmp_path):
    def reject(*args):
        result=model(*args)
        if args[3]['title']=='Candidate':result['qualified']=False
        return result
    store,browser,engine,plan=setup(tmp_path,reject)
    assert engine.run(plan['id'],True)['staged']==0
    engine.model=model
    plan=engine.prepare('Fixture',1,recheck_failed=True,profile_url=PROFILE)
    browser.search=lambda q:pytest.fail('Targeted recheck must not run broad searches')
    report=engine.run(plan['id'],True)
    assert report['staged']==1 and report['rechecked']==1
    assert browser.visits==2
    assert engine.run(plan['id'],True)['staged']==0


def test_fallback_cannot_substitute_a_different_person(tmp_path,monkeypatch):
    def missing(*args):
        result=model(*args)
        if args[3]['title']=='Candidate':result.update(qualified=False,needs_web_evidence=True)
        return result
    store,browser,engine,plan=setup(tmp_path,missing)
    monkeypatch.setattr(research_web,'discover',lambda *a:[{'url':'https://www.linkedin.com/in/different-fixture/','web_company':browser.company(COMPANY)}])
    assert engine.run(plan['id'],True)['staged']==0
    assert not store.list('leads')
