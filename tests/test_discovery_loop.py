import threading
from test_research import setup, PROFILE, COMPANY
from workbench import research_web


def test_parallel_web_serial_linkedin_dedupe_and_target(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    plan['web_first']=False;store.setting('research_plan',plan) # old plans also migrate
    engine.reserve(PROFILE,'old-run')
    barrier=threading.Barrier(2);threads=[];browser_threads=[]
    original=browser.profile;committed_counts=[]
    def profile(url):
        committed_counts.append(len(store.list('leads')))
        browser_threads.append(threading.get_ident());return original(url)
    browser.profile=profile
    browser.search=lambda q:(_ for _ in ()).throw(AssertionError('Web first required'))
    def web(worker,p,*args,**kwargs):
        assert worker.browser is None
        threads.append(threading.get_ident());barrier.wait(timeout=5)
        return [{'url':PROFILE,'label':'Seen'}]+[{'url':f'https://www.linkedin.com/in/new-{i}/','label':'New','web_company':browser.company(COMPANY)} for i in range(4)]
    monkeypatch.setattr(research_web,'discover',web)
    report=engine.run(plan['id'],True)
    assert report['staged']==3 and report['visited']==3 and report['reason']=='target_reached'
    assert len(set(threads))==2 and set(browser_threads)=={threading.get_ident()}
    assert report['web_first'] and len(store.list('leads'))==3
    assert committed_counts==[0,1,2]  # each prior result committed before the next visit
    with store.db() as db:
        assert db.execute("SELECT count(*) FROM workspace_changes WHERE kind='research_assessment' AND after_state='review'").fetchone()[0]==3
    assert not store.list('deliveries')


def test_empty_results_continue_past_three_rounds_until_stopped(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path);rounds=[]
    def empty(*a,**kw):
        rounds.append(1)
        if len(rounds)>=8:engine.stop.set()
        return []
    monkeypatch.setattr(research_web,'discover',empty)
    report=engine.run(plan['id'],True)
    assert len(rounds)>=8 and 'stopped by you' in report['reason']
    assert report['visited']==0


def test_targeted_profile_searches_web_without_expanding(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    plan['profile_url']=PROFILE;store.setting('research_plan',plan)
    calls=[]
    monkeypatch.setattr(research_web,'discover',lambda *a:calls.append(a[1]) or [])
    report=engine.run(plan['id'],True)
    assert len(calls)==1 and PROFILE in calls[0]['prompt']
    assert report['staged']==1 and browser.visits==1


def test_worker_failure_cancels_peer_and_finishes_before_inactive(tmp_path,monkeypatch):
    from workbench.errors import ProviderError
    store,browser,engine,plan=setup(tmp_path);barrier=threading.Barrier(2);ended=[]
    def web(worker,p,*args,**kw):
        barrier.wait(timeout=5)
        if 'lane 1' in p['prompt']:raise ProviderError('HTTP 429: stopped')
        while not worker.stop.is_set():threading.Event().wait(.01)
        ended.append(True);return []
    monkeypatch.setattr(research_web,'discover',web)
    report=engine.run(plan['id'],True)
    assert '429' in report['reason'] and ended and not engine.state()['active']
    assert browser.visits==0


def test_shared_primary_source_is_captured_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from workbench.research_pool import SourceCache
    cache=SourceCache();barrier=threading.Barrier(2);calls=[]
    def capture():calls.append(1);return {'evidence':'exact source'}
    def work():
        barrier.wait(timeout=5)
        return cache.get('https://example.com/company',capture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:work(),range(2)))
    assert calls==[1] and results[0] is results[1]


def test_explicit_visit_cap_stops_before_target(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    plan['max_profiles']=2;store.setting('research_plan',plan)
    monkeypatch.setattr(research_web,'discover',lambda *a,**kw:[{'url':f'https://www.linkedin.com/in/capped-{i}/','label':'New','web_company':browser.company(COMPANY)} for i in range(5)])
    result=engine.run(plan['id'],True)
    assert result['visited']==2 and result['staged']==2 and result['reason']=='visit_limit'


def test_deadline_cancels_inflight_workers(tmp_path,monkeypatch,short_research_deadline):
    store,browser,engine,plan=setup(tmp_path);ended=[]
    def busy(worker,*a,**kw):
        while not worker.stop.is_set():threading.Event().wait(.01)
        ended.append(True);return []
    monkeypatch.setattr(research_web,'discover',busy)
    result=engine.run(plan['id'],True)
    assert result['reason']=='Research time limit reached.' and len(ended)==2
    assert not engine.state()['active'] and browser.visits==0


def test_redirected_candidate_is_recorded_and_remaining_three_save(tmp_path,monkeypatch):
    from workbench.errors import ProfileIdentityError
    store,browser,engine,plan=setup(tmp_path)
    original=browser.profile
    bad='https://www.linkedin.com/in/redirected-candidate/'
    def profile(url):
        if url==bad:
            raise ProfileIdentityError(url,'https://www.linkedin.com/in/other-person/')
        return original(url)
    browser.profile=profile
    links=[{'url':bad,'label':'Redirected'}]+[
        {'url':f'https://www.linkedin.com/in/good-{i}/','label':'Candidate','web_company':browser.company(COMPANY)}
        for i in range(3)]
    monkeypatch.setattr(research_web,'discover',lambda *a,**kw:links)
    report=engine.run(plan['id'],True)
    assert report['reason']=='target_reached'
    assert report['staged']==3 and report['visited']==4
    assert all(lead['url']!=bad for lead in store.list('leads'))
    with store.db() as db:
        import json
        visit=db.execute("SELECT state,evidence FROM research_visits WHERE profile_key='redirected-candidate'").fetchone()
        assert visit['state']=='insufficient_evidence'
        assert json.loads(visit['evidence'])['observed_url'].endswith('/other-person/')
        record=json.loads(db.execute("SELECT record FROM crm_research_profiles WHERE profile_key='redirected-candidate'").fetchone()[0])
        assert record['status']=='missing_evidence'
    assert not store.list('deliveries')


def test_profile_auth_failure_still_stops_research(tmp_path,monkeypatch):
    from workbench.errors import ProviderError
    store,browser,engine,plan=setup(tmp_path)
    browser.profile=lambda url:(_ for _ in ()).throw(ProviderError('LinkedIn sign-in required'))
    monkeypatch.setattr(research_web,'discover',lambda *a,**kw:[{'url':PROFILE,'label':'Candidate'}])
    report=engine.run(plan['id'],True)
    assert report['visited']==1 and report['staged']==0
    assert report['reason']=='LinkedIn sign-in required'


def test_browser_redirect_never_returns_other_person_evidence():
    import pytest
    from workbench.research_browser import ResearchBrowser
    from workbench.errors import ProfileIdentityError
    browser=ResearchBrowser(None)
    browser.snapshot=lambda url:dict(url='https://www.linkedin.com/in/someone-else/',title='Other',links=[])
    with pytest.raises(ProfileIdentityError):
        browser.profile(PROFILE)


def test_linkedin_starts_while_web_worker_still_researching(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    visited=threading.Event()
    original=browser.profile
    def profile(url):
        visited.set()
        return original(url)
    browser.profile=profile
    def web(worker,p,*a,**kw):
        if 'lane 1' not in p['prompt']:return []
        worker._publish_candidates([{'url':PROFILE,'label':'First','web_company':browser.company(COMPANY)}])
        assert visited.wait(3), 'LinkedIn waited for the whole web shortlist'
        later=[{'url':f'https://www.linkedin.com/in/streamed-{i}/','label':'Later','web_company':browser.company(COMPANY)} for i in range(2)]
        worker._publish_candidates(later)
        return later
    monkeypatch.setattr(research_web,'discover',web)
    report=engine.run(plan['id'],True)
    assert report['staged']==3 and report['visited']==3
    assert report['reason']=='target_reached'


def test_recheck_backlog_does_not_block_fresh_web_candidates(tmp_path,monkeypatch):
    from workbench.errors import ProfileIdentityError
    store,browser,engine,plan=setup(tmp_path)
    old='https://www.linkedin.com/in/old-unresolved/'
    redirected='https://www.linkedin.com/in/newer-redirect/'
    evidence={'assessment':{'needs_web_evidence':True,'reason':'Identity unavailable'}}
    engine.remember(old,'insufficient_evidence',evidence,'old-run','Old brief','2026-01-01T00:00:00+00:00')
    engine.remember(redirected,'insufficient_evidence',evidence,'old-run','Old brief','2026-01-02T00:00:00+00:00')
    plan['recheck_failed']=True;store.setting('research_plan',plan)
    original=browser.profile;visited=[]
    def profile(url):
        visited.append(url)
        if url==redirected:raise ProfileIdentityError(url,'https://www.linkedin.com/in/renamed/')
        return original(url)
    browser.profile=profile
    def web(worker,p,*a,**kw):
        if 'Research ONLY' in p['prompt']:return []
        return [{'url':f'https://www.linkedin.com/in/fresh-{i}/','label':'New','web_company':browser.company(COMPANY)} for i in range(3)]
    monkeypatch.setattr(research_web,'discover',web)
    report=engine.run(plan['id'],True)
    assert visited[0]==redirected and old not in visited
    assert report['staged']==3 and report['visited']==4 and report['reason']=='target_reached'


def test_profile_404_is_skipped_before_waiting_for_missing_main():
    import pytest
    from types import SimpleNamespace
    from workbench.errors import ProfileIdentityError
    from workbench.research_browser import ResearchBrowser
    driver=SimpleNamespace(current_url='https://www.linkedin.com/404/')
    linkedin=SimpleNamespace(navigate=lambda url:None,browser=lambda:driver)
    with pytest.raises(ProfileIdentityError) as error:
        ResearchBrowser(linkedin).profile(PROFILE)
    assert error.value.observed_url=='https://www.linkedin.com/404/'
