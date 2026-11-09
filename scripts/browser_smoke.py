"""Real Chromium fixture tests. No external websites, logins or invitations.
Run inside the app container with source and tests mounted, or locally with
SELENIUM_URL pointing at the isolated test browser.
"""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from workbench.linkedin import LinkedInBrowser
from workbench.store import Store

root=Path(__file__).resolve().parents[1]
fixture='data:text/html;charset=utf-8,'+quote((root/'tests/fixtures/profile.html').read_text())
with tempfile.TemporaryDirectory() as t:
    store=Store(Path(t));settings=SimpleNamespace(selenium_url=os.environ['SELENIUM_URL'])
    b=LinkedInBrowser(settings,store);driver=b.browser()
    driver.get(fixture)
    sid=driver.session_id;b.close_transport()
    b=LinkedInBrowser(settings,store);driver=b.browser()
    assert driver.session_id==sid
    class FixtureDriver:
        current_url='https://www.linkedin.com/in/example-person'
        def __getattr__(self,name):return getattr(driver,name)
    b.driver=FixtureDriver()
    b.require_account=lambda:None
    b.navigate=lambda url:driver.get(fixture)
    b.check=lambda:None
    lead=dict(name='Wrong Person',company='Example Company',url=FixtureDriver.current_url,note='Hello from the fixture')
    assert b.send(lead)['status']=='blocked'
    assert driver.execute_script('return window.sends||0')==0
    lead['name']='Example Person'
    assert b.send(lead)['status']=='confirmed'
    assert driver.execute_script('return window.sends')==1
    assert driver.find_element('css selector','textarea').get_attribute('value')==lead['note']
    driver.quit()
print('PASS: isolated Chromium, session reattachment, wrong-recipient block, exact note, single confirmed fixture send')
