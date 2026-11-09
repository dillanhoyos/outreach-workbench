from test_research import setup, model, PROFILE, PERSON, COMPANY
from workbench import research_web


def test_duplicates_then_new_queries_reach_three_without_revisiting(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    engine.reserve(PROFILE,'old-run')
    queries=[]
    def search(query):
        queries.append(query)
        if len(queries)==1:return {'url':'https://www.linkedin.com/search/results/people/'},[{'url':PROFILE,'label':'Seen'}]
        return {'url':'https://www.linkedin.com/search/results/people/'},[{'url':f'https://www.linkedin.com/in/fixture-new-{i}/','label':'New'} for i in range(3)]
    browser.search=search
    def reasoning(*args):
        if args[3]['title']=='Plan' and 'previous_queries' in args[2]:
            assert args[2]['previous_queries']==plan['queries']
            return {'summary':'Different search, same audience','queries':['fresh company founders']}
        return model(*args)
    engine.model=reasoning
    monkeypatch.setattr(research_web,'discover',lambda *a:(_ for _ in ()).throw(AssertionError('Target reached before web needed')))
    report=engine.run(plan['id'],True)
    assert report['staged']==3 and report['visited']==3 and report['reason']=='target_reached'
    assert browser.visits==3 and len(store.list('leads'))==3
    assert len(queries)==2 and not store.list('deliveries')
    assert any(e['kind']=='filtered_seen' for e in engine.state()['events'])


def test_duplicate_only_queries_switch_to_web_and_stop_at_target(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    engine.reserve(PROFILE,'old')
    rounds=[]
    def web(*args):
        p=args[1];rounds.append(p)
        return [{'url':f'https://www.linkedin.com/in/fresh-web-{i}/','label':'New','web_company':browser.company(COMPANY)} for i in range(4)]
    monkeypatch.setattr(research_web,'discover',web)
    report=engine.run(plan['id'],True)
    assert report['staged']==3 and report['visited']==3
    assert len(rounds)==1 and rounds[0]['exclude_visited'] is True
    assert not store.list('deliveries')


def test_no_new_results_end_with_explicit_budget_reason(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    engine.reserve(PROFILE,'old')
    rounds=[]
    monkeypatch.setattr(research_web,'discover',lambda *a:rounds.append(1) or [])
    report=engine.run(plan['id'],True)
    assert len(rounds)==2 and report['reason']=='discovery_budget_exhausted'
    assert report['visited']==0 and report['staged']==0


def test_targeted_profile_never_expands_to_other_people(tmp_path,monkeypatch):
    store,browser,engine,plan=setup(tmp_path)
    engine.reserve(PROFILE,'old')
    plan['profile_url']=PROFILE;store.setting('research_plan',plan)
    monkeypatch.setattr(research_web,'discover',lambda *a:(_ for _ in ()).throw(AssertionError('No expansion')))
    report=engine.run(plan['id'],True)
    assert report['visited']==0 and report['staged']==0
