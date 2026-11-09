import json,time
from types import SimpleNamespace
import pytest
from workbench.invitation_receipt import InvitationReceipt,INVITATION_PATH,invite_url_matches
from workbench.linkedin import LinkedInBrowser
from workbench.store import Store
from selenium.common.exceptions import TimeoutException

PROFILE='https://www.linkedin.com/in/example-person/'
URL='https://www.linkedin.com'+INVITATION_PATH

def event(kind,params):return {'message':json.dumps({'message':{'method':kind,'params':params}})}
def request(rid='1',method='POST',url=URL,wall=100):
    return event('Network.requestWillBeSent',{'requestId':rid,'wallTime':wall,'request':{'url':url,'method':method,'headers':{'cookie':'SECRET'},'postData':'PRIVATE NOTE'}})
def response(rid='1',status=200,url=URL,**extra):
    return event('Network.responseReceived',{'requestId':rid,'response':{'url':url,'status':status,**extra}})


def test_exact_post_response_correlated_and_redacted():
    r=InvitationReceipt(PROFILE,99);r.feed([request(url=URL+'?secret=SECRET'),response()])
    assert r.accepted
    assert 'SECRET' not in json.dumps(r.snapshot()) and 'PRIVATE NOTE' not in json.dumps(r.snapshot())


@pytest.mark.parametrize('events',[
    [response()], [request(method='GET'),response()], [request(wall=98),response()],
    [request(),response(rid='other')], [request(),response(status=201)],
    [request(),response(fromServiceWorker=True)], [request(),response(fromDiskCache=True)],
    [request(url='https://evil.example'+INVITATION_PATH),response()],
    [request(),response(url='https://www.linkedin.com/voyager/api/unrelated')],
    [request(),request(rid='2'),response()],
    [request(),request(method='GET'),response()],
])
def test_unrelated_stale_cached_or_ambiguous_200_does_not_confirm(events):
    r=InvitationReceipt(PROFILE,99);r.feed(events);assert not r.accepted


def test_429_and_accepted_request_can_coexist():
    r=InvitationReceipt(PROFILE,99);r.feed([request(),response(),response(rid='other',status=429)])
    assert r.accepted and r.rate_limited


def test_invitation_link_requires_exact_recipient():
    assert invite_url_matches('https://www.linkedin.com/preload/custom-invite/?vanityName=example-person',PROFILE)
    for url in ('https://www.linkedin.com/preload/custom-invite/?vanityName=other',
                'https://www.linkedin.com/preload/custom-invite/?vanityName=example-person&vanityName=other',
                'https://evil.example/preload/custom-invite/?vanityName=example-person'):
        assert not invite_url_matches(url,PROFILE)


def send_fixture(tmp_path,*,click_error=False,accepted=True):
    store=Store(tmp_path);store.add_lead({'name':'Example Person','company':'Example Company','role':'Founder','country':'Example','url':PROFILE,'evidence':'fixture'})
    lead=store.list('leads')[0];store.approve(lead['id'],'Hello');lead=store.reserve(lead['id'],5)
    state={'clicks':0,'logs':[]}
    class Element:
        text='Example Person'
        def is_displayed(self):return True
        def is_enabled(self):return True
        def send_keys(self,text):self.value=text
        def get_attribute(self,name):return getattr(self,'value','')
        def click(self):
            state['clicks']+=1
            if accepted:state['logs']=[request(wall=time.time()+.01),response()]
            if click_error:raise TimeoutException('renderer timed out')
    field=Element();button=Element()
    card=SimpleNamespace(text='Example Person Founder Example Company',find_elements=lambda by,s:[Element()] if s=='h1,h2' else [])
    modal=SimpleNamespace(find_elements=lambda by,s:[field] if s=='textarea' else [])
    class Driver:
        current_url=PROFILE
        def execute(self,*args):
            logs=state['logs'];state['logs']=[];return {'value':logs}
    browser=LinkedInBrowser(SimpleNamespace(),store);browser.driver=Driver()
    browser.require_session=lambda:None;browser.navigate=lambda u:None;browser.topcard=lambda name=None:card
    browser.open_invitation=lambda *a:None;browser.invitation_form=lambda *a:modal
    browser.unique_button=lambda *a:button;browser.check=lambda:None
    return store,browser,lead,state


def test_post_200_confirms_before_any_dom_poll(tmp_path):
    store,b,lead,state=send_fixture(tmp_path)
    original=b.topcard
    def card(name=None):
        if state['clicks']:raise AssertionError('DOM must not be read after accepted network response')
        return original(name)
    b.topcard=card
    result=b.send(lead)
    assert result['status']=='confirmed' and state['clicks']==1
    with store.db() as db:
        audit=db.execute('SELECT * FROM invitation_attempts').fetchone()
        assert audit['click_attempted']==1 and json.loads(audit['network'])['accepted']


def test_click_timeout_with_matching_200_is_confirmed_without_retry(tmp_path):
    store,b,lead,state=send_fixture(tmp_path,click_error=True)
    assert b.send(lead)['status']=='confirmed' and state['clicks']==1


def test_click_timeout_without_receipt_remains_uncertain(tmp_path):
    store,b,lead,state=send_fixture(tmp_path,click_error=True,accepted=False)
    assert b.send(lead)['status']=='uncertain' and state['clicks']==1


def test_heading_failure_is_recorded_before_send(tmp_path):
    store,b,lead,state=send_fixture(tmp_path)
    b.topcard=lambda *a:(_ for _ in ()).throw(TimeoutException('heading unavailable'))
    result=b.send(lead)
    assert result['status']=='blocked' and state['clicks']==0
    with store.db() as db:
        row=db.execute('SELECT * FROM invitation_attempts').fetchone()
        assert row['phase']=='profile_identity' and not row['click_attempted']


def test_profile_rerender_rechecks_identity_without_duplicate_click(tmp_path):
    from selenium.common.exceptions import StaleElementReferenceException
    store,b,lead,state=send_fixture(tmp_path)
    original=b.topcard
    reads=[]
    def card(name=None):
        reads.append(name)
        if len(reads)==1:raise StaleElementReferenceException('Profile rerendered')
        return original(name)
    b.topcard=card
    assert b.send(lead)['status']=='confirmed'
    assert len(reads)==2 and state['clicks']==1
