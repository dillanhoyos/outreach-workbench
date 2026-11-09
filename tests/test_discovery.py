from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings


def test_live_discovery_reports_missing_worker_without_running_or_adding_leads(tmp_path):
    settings = Settings(tmp_path, 'x'*32, 'live', '', 10, '', '')
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + 'x'*32
        assert client.get('/api/status').json()['discovery'] == {'ready': False, 'provider': 'not_connected'}
        result = client.post('/api/discover', json={'prompt': 'Find accounting managers at road operators', 'limit': 3})
        assert result.status_code == 503 and 'No research job was started' in result.json()['detail']
        assert client.get('/api/records/jobs').json() == []
        assert client.get('/api/records/leads').json() == []


def test_discovery_requires_research_brief_and_rejects_provider_filters(tmp_path):
    settings = Settings(tmp_path, 'x'*32, 'demo', '', 10, '', '')
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + 'x'*32
        assert client.post('/api/discover', json={'limit': 3}).status_code == 422
        assert client.post('/api/discover', json={'prompt': 'Find finance people', 'locations': ['Example']}).status_code == 422
        assert client.get('/api/status').json()['discovery'] == {'ready': True, 'provider': 'demo'}
