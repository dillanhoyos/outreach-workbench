from types import SimpleNamespace
import httpx
from fastapi.testclient import TestClient
from workbench.browser_status import browser_status
from workbench.config import Settings
from workbench.app import create_app


def test_driver_busy_is_reachable_and_viewer_port_is_configurable():
    calls = []
    def handle(req):
        calls.append(str(req.url))
        if req.url.port == 4444:
            return httpx.Response(200, json={'value': {'ready': False, 'message': 'Session occupied'}})
        return httpx.Response(200, text='<html>noVNC</html>')
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = browser_status(SimpleNamespace(selenium_url='http://browser:4444', browser_port=17900, mode='live'), client)
    assert result['available'] and result['viewer_port'] == 17900
    assert calls == ['http://browser:4444/status', 'http://browser:7900/vnc.html']


def test_missing_browser_produces_actionable_status_without_session_creation():
    def handle(req):
        assert req.method == 'GET'
        raise httpx.ConnectError('internal details should not be shown')
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = browser_status(SimpleNamespace(selenium_url='http://browser:4444', browser_port=7900, mode='live'), client)
    assert not result['available'] and 'Start the browser container' in result['message']
    assert 'internal details' not in str(result)


def test_login_gates_missing_browser_before_starting_job(tmp_path, monkeypatch):
    import workbench.browser_status as module
    settings = Settings(tmp_path, 'x'*32, 'live', 'http://browser:4444', 10, '', '')
    monkeypatch.setattr(module, 'browser_status', lambda settings: {'available': False})
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/browser/status').status_code == 401
        client.headers['Authorization'] = 'Bearer ' + 'x'*32
        assert client.get('/api/browser/status').json() == {'available': False}
        result = client.post('/api/linkedin/login', json={})
        assert result.status_code == 503 and '--profile live' in result.json()['detail']
        assert client.get('/api/records/jobs').json() == []


def test_demo_login_returns_clear_error_and_static_assets_work(tmp_path):
    settings = Settings(tmp_path, 'x'*32, 'demo', '', 10, '', '')
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + 'x'*32
        result = client.post('/api/linkedin/login', json={})
        assert result.status_code == 400 and 'WORKBENCH_MODE=live' in result.json()['detail']
        assert client.get('/assets/workbench.js').status_code == 200
        assert client.get('/assets/workbench.css').status_code == 200
        assert 'browser-frame' in client.get('/').text


def test_restart_reopens_session_preserving_profile_and_restrictions(tmp_path):
    from workbench.linkedin import LinkedInBrowser
    from workbench.store import Store
    store=Store(tmp_path)
    store.setting('browser_session',{'id':'old'})
    store.setting('linkedin_restriction',{'reason':'HTTP 429'})
    calls=[]
    browser=LinkedInBrowser(SimpleNamespace(),store)
    browser.driver=SimpleNamespace(quit=lambda:calls.append('quit'))
    def open_browser():
        assert browser.driver is None
        assert store.setting('browser_session') is False
        return SimpleNamespace(get=lambda url:calls.append(url))
    browser.browser=open_browser
    browser.restart()
    assert calls==['quit','https://www.linkedin.com/feed/']
    assert store.setting('linkedin_restriction')=={'reason':'HTTP 429'}


def test_restart_recovers_expired_saved_session(tmp_path,monkeypatch):
    from workbench.linkedin import LinkedInBrowser
    from workbench.store import Store
    store=Store(tmp_path);store.setting('browser_session',{'id':'expired'})
    browser=LinkedInBrowser(SimpleNamespace(selenium_url='http://browser:4444'),store)
    calls=[]
    def delete(url,timeout):
        calls.append(url)
        return httpx.Response(404)
    monkeypatch.setattr(httpx,'delete',delete)
    browser.browser=lambda:SimpleNamespace(get=lambda url:calls.append(url))
    browser.restart()
    assert calls==['http://browser:4444/session/expired','https://www.linkedin.com/feed/']
    assert store.setting('browser_session') is False
