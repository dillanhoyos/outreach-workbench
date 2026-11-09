import json
from types import SimpleNamespace
import httpx
import pytest
from workbench.errors import ProviderError
from workbench.jev import JevAdvisor
from workbench.linkedin import LinkedInBrowser

CONTROLS = [{'text': 'Connect', 'label': 'Connect with Example Person'},
            {'text': 'Connect', 'label': 'Connect with Example Person'}]


def answer(choice='0'):
    return {'answers': {'connect_control': {'type': 'choice', 'choice': choice,
            'confidence': .95, 'probabilities': {'0': .95, '1': .04, 'unknown': .01}}}}


def test_jev_request_is_bounded_and_response_validated():
    def handle(req):
        body = json.loads(req.content)
        assert str(req.url) == 'https://api.typesafe.ai/v1/systemone'
        assert req.headers['Authorization'] == 'Bearer fixture-key'
        assert set(body['state']) == {'controls'}
        assert set(body['state']['controls'][0]) == {'id', 'text', 'label'}
        assert len(body['state']['controls'][0]['label']) == 160
        return httpx.Response(200, json=answer())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert JevAdvisor('fixture-key', client).choose_connect([dict(CONTROLS[0], label='x'*300), CONTROLS[1]]) == 0


@pytest.mark.parametrize('status,payload', [(429, {'secret': 'private-response'}),
    (401, {'secret': 'private-response'}), (200, answer('unknown')),
    (200, answer('invented-selector')), (200, {'answers': {}})])
def test_failures_stop_with_one_call_and_no_body_leak(status, payload):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(status, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError) as error:
            JevAdvisor('fixture-key', client).choose_connect(CONTROLS)
    assert len(calls) == 1
    assert 'private-response' not in str(error.value) and 'fixture-key' not in str(error.value)


class Button:
    def __init__(self, text, visible=True, enabled=True):
        self.text = text; self.visible = visible; self.enabled = enabled
    def is_displayed(self): return self.visible
    def is_enabled(self): return self.enabled
    def get_attribute(self, name): return 'Connect with Example Person'


def test_browser_advisor_is_optional_scoped_and_rechecks_page(monkeypatch, tmp_path):
    one, two, send = Button('Connect'), Button('Connect'), Button('Send')
    elements = [one, send, Button('Connect', visible=False), Button('Connect', enabled=False)]
    card = SimpleNamespace(find_elements=lambda *args: elements)
    b = LinkedInBrowser(SimpleNamespace(browser_advisor='none', typesafe_key='fixture', data_dir=tmp_path), None)
    b.driver = SimpleNamespace(current_url='https://www.linkedin.com/in/example')
    b.check = lambda: None
    calls = []
    def choose(self, controls):
        calls.append(controls)
        return 1
    monkeypatch.setattr(JevAdvisor, 'choose_connect', choose)
    assert b.connect_button(card) is one and not calls
    elements.append(two)
    with pytest.raises(ProviderError): b.connect_button(card)
    assert not calls
    b.settings.browser_advisor = 'jev'
    assert b.connect_button(card) is two
    assert len(calls[0]) == 2 and all(c['text'] == 'Connect' for c in calls[0])
    def changed(self, controls):
        b.driver.current_url = 'https://www.linkedin.com/in/someone-else'
        return 0
    monkeypatch.setattr(JevAdvisor, 'choose_connect', changed)
    with pytest.raises(ProviderError, match='changed'): b.connect_button(card)


@pytest.mark.parametrize('field,value', [('confidence', float('nan')), ('confidence', True),
    ('probabilities', {'0': 1.0, '1': 1.0, 'unknown': 0.0})])
def test_invalid_probability_values_stop(field, value):
    payload = answer()
    payload['answers']['connect_control'][field] = value
    class Client:
        def post(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: payload)
    with pytest.raises(ProviderError, match='invalid data'):
        JevAdvisor('fixture-key', Client()).choose_connect(CONTROLS)
