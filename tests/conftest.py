import pytest

@pytest.fixture
def fixture_web(monkeypatch,short_research_deadline):
    from test_research import PROFILE
    # Replace external discovery only; exercise real orchestration and browser sequencing.
    monkeypatch.setattr('workbench.research_web.discover',lambda *a,**kw:[{'url':PROFILE,'label':'Fixture'}])

@pytest.fixture
def short_research_deadline(monkeypatch):
    # Exercise deadline/cancellation without waiting minutes for exhausted fixtures.
    import threading
    timer=threading.Timer
    monkeypatch.setattr('workbench.research.threading.Timer',lambda interval,callback:timer(min(interval,.3),callback))
