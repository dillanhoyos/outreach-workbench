import json
import base64
from types import SimpleNamespace
import pytest
from workbench.linkedin import LinkedInBrowser,message_time
from workbench.errors import ProviderError
from workbench.store import Store

class Driver:
    current_url='https://www.linkedin.com/feed/'
    def __init__(self,text='',status=200):self.text=text;self.status=status
    def find_element(self,*args):return SimpleNamespace(text=self.text)
    def get_log(self,kind):return [{'message':json.dumps({'message':{'method':'Network.responseReceived','params':{'response':{'url':'https://www.linkedin.com/feed/','status':self.status}}}})}]


def browser(tmp_path,driver):
    b=LinkedInBrowser(SimpleNamespace(selenium_url='fixture'),Store(tmp_path));b.driver=driver
    return b


def test_login_blocks_and_limits_persist(tmp_path):
    d=Driver();d.current_url='https://www.linkedin.com/checkpoint/challenge'
    b=browser(tmp_path,d)
    with pytest.raises(ProviderError,match='sign-in'):b.check()
    d.current_url='https://www.linkedin.com/feed/';d.status=429
    with pytest.raises(ProviderError,match='429'):b.check()
    assert b.store.setting('linkedin_restriction')['reason']=='HTTP 429'
    with pytest.raises(ProviderError,match='restriction'):b.require_account()


def test_weekly_limit_no_restart(tmp_path):
    b=browser(tmp_path,Driver('You reached the weekly invitation limit'))
    with pytest.raises(ProviderError,match='restriction'):b.check()
    assert b.driver is not None


def test_missing_identity_prevents_send(tmp_path):
    b=browser(tmp_path,Driver())
    with pytest.raises(ProviderError,match='Verify your LinkedIn account'):
        b.send({'url':'https://www.linkedin.com/in/fixture'})


def test_message_timestamp_not_guessed():
    encoded=base64.urlsafe_b64encode(b'1700000000000_fixture').decode().rstrip('=')
    assert message_time('(urn,2-'+encoded+')').startswith('2023-11-14')
    for value in ['yesterday','', '(urn,2-YWJj)']:
        with pytest.raises(ProviderError):message_time(value)
