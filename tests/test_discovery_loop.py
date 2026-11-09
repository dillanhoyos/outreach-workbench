import threading
from test_research import setup, PROFILE, COMPANY
from workbench import research_web


def test_parallel_web_serial_linkedin_dedupe_and_target(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    plan['web_first']=False;store.setting('research_plan',plan) # old plans also migrate
    engine.reserve(PROFILE,'old-run')
    barrier=threading.Barrier(2);threads=[];browser_threads=[]
    original=browser.profile
    def profile(url):
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
    assert not store.list('deliveries')


def test_empty_web_results_exhaust_bounded_rounds(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path);rounds=[]
    monkeypatch.setattr(research_web,'discover',lambda *a,**kw:rounds.append(1) or [])
    report=engine.run(plan['id'],True)
    assert len(rounds)==6 and report['reason']=='discovery_budget_exhausted'
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
