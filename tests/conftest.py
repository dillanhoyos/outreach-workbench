import pytest

@pytest.fixture
def fixture_web(monkeypatch):
    from test_research import PROFILE
    # Replace external discovery only; exercise real orchestration and browser sequencing.
    monkeypatch.setattr('workbench.research_web.discover',lambda *a,**kw:[{'url':PROFILE,'label':'Fixture'}])
