import threading
from types import SimpleNamespace
import pytest
from workbench.reader import run_reader
from workbench.store import Store
from workbench.demo import DemoProvider
from workbench.errors import ProviderError

@pytest.fixture
def store(tmp_path):
 s=Store(tmp_path)
 s.add_lead(DemoProvider().discover('fixture',1)[0])
 return s

def row(store):
 return dict(ident='fixture-message',lead_id=store.list('leads')[0]['id'],body='A fixture incoming reply',received='2026-01-01T12:00:00+00:00',thread='fixture-thread')

def test_incremental_replies_survive_later_failure_and_deduplicate(store):
 class Provider:
  def read(self,leads,limit,on_reply,on_progress,stop):
   on_reply(row(store))
   assert store.list('replies')
   raise ProviderError('Fixture browser interruption')
 with pytest.raises(ProviderError):run_reader(store,Provider(),3)
 assert store.setting('last_reader_report')['added']==1
 assert store.setting('last_reader_report')['phase']=='failed'
 assert store.list('leads')[0]['status']=='replied'
 report=run_reader(store,SimpleNamespace(read=lambda *a,**k:[row(store)]),3)
 assert report['added']==0 and report['duplicates']==1
 with store.db() as db:
  assert db.execute('SELECT COUNT(*) FROM crm_messages').fetchone()[0]==1
  assert db.execute("SELECT COUNT(*) FROM workspace_changes WHERE kind='reply'").fetchone()[0]==1
  from workbench.crm import enrich
  assert not enrich(db,store.list('leads'))[0]['outreach_available']

def test_reader_passes_limit_stop_and_reports_progress(store):
 stop=threading.Event();stop.set()
 class Provider:
  def read(self,leads,limit,on_reply,on_progress,stop):
   assert limit==100 and stop.is_set()
   on_progress({'unique_conversations_checked':2,'reason':'stopped_by_user'})
   return []
 report=run_reader(store,Provider(),100,stop)
 assert report['reason']=='stopped_by_user' and report['unique_conversations_checked']==2
 assert report['added']==0

def test_cron_update_preserves_other_jobs_and_is_idempotent():
 import importlib.util
 from pathlib import Path
 spec=importlib.util.spec_from_file_location('installer',Path(__file__).parents[1]/'scripts/install-reader-cron.py')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 old='MAILTO=operator@example.com\n0 12 * * * /keep/this\n'
 updated=module.updated_crontab(old,Path('/tmp/work bench'))
 assert '0 12 * * * /keep/this' in updated
 assert updated.count('0 14 * * 1-5')==1
 assert module.updated_crontab(updated,Path('/tmp/work bench'))==updated
 assert module.START not in module.updated_crontab(updated,Path('/tmp'),True)

def test_scheduled_client_skips_busy_without_submit(monkeypatch):
 import json
 from workbench import reader_job
 calls=[]
 class Response:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def read(self):return json.dumps({'mode':'live','busy':True}).encode()
 def request(req,**kwargs):calls.append(req.full_url);return Response()
 monkeypatch.setenv('WORKBENCH_TOKEN','fixture-token')
 monkeypatch.setattr(reader_job,'urlopen',request)
 assert reader_job.run()['status']=='skipped'
 assert len(calls)==1 and calls[0].endswith('/status')

def test_current_inbox_div_controls_do_not_require_href():
 from workbench.linkedin import fresh_conversation_cards
 cards=[{'id':'ember1','name':'Known person','href':None},
        {'id':'ember2','name':None,'href':None},
        {'id':'ember3','name':'Another person','href':'https://www.linkedin.com/messaging/thread/abc/'}]
 assert fresh_conversation_cards(cards,set())==[cards[0],cards[2]]
 assert fresh_conversation_cards(cards,{'ember1',cards[2]['href']})==[]

def test_browser_reader_current_layout_through_crm(store,monkeypatch):
 """Exercise real reader navigation/identity/extraction with a deterministic DOM driver."""
 import base64
 from workbench.linkedin import LinkedInBrowser
 from selenium.webdriver.common.by import By
 lead=store.list('leads')[0];internal='https://www.linkedin.com/in/ACoFixtureIdentity'
 thread='https://www.linkedin.com/messaging/thread/fixture/'
 urn='(urn,2-'+base64.urlsafe_b64encode(b'1700000000000_fixture').decode().rstrip('=')+')'
 class Element:
  def __init__(self,kind):self.kind=kind
  @property
  def text(self):return lead['name']
  def find_element(self,by,selector):return Element('link' if 'listitem__link' in selector else 'text')
  def get_attribute(self,key):return internal
  def click(self):driver.urls[driver.current_window_handle]=thread
 class Switch:
  def new_window(self,kind):driver.current_window_handle='child';driver.urls['child']='about:blank'
  def window(self,handle):driver.current_window_handle=handle
 class Driver:
  current_window_handle='parent'
  urls={'parent':'https://www.linkedin.com/messaging/'}
  switch_to=Switch()
  @property
  def current_url(self):return self.urls[self.current_window_handle]
  def close(self):del self.urls[self.current_window_handle]
  def find_element(self,by,value):return Element('card')
  def find_elements(self,by,selector):
   assert selector!='main h1','Profile identity must not depend on legacy h1 layout'
   if 'overlay/contact-info' in selector:return []
   return [Element('header')]
  def execute_script(self,script):
   if 'map(e=>({id:e.id' in script:return [{'id':'ember-fixture','name':lead['name'],'href':None},{'id':'loading','name':None,'href':None}]
   if 'let sender=null' in script:return [{'id':urn,'sender':internal,'text':'Fixture reply from the actual participant'},{'id':urn+'out','sender':'https://www.linkedin.com/in/sender-self/','text':'Outgoing fixture'}]
   if 'scrollTop' in script:return False
   raise AssertionError('Unexpected browser operation')
 driver=Driver();browser=LinkedInBrowser(SimpleNamespace(),store);browser.driver=driver
 browser.require_session=lambda:None;browser.check=lambda:None
 browser.navigate=lambda url:driver.urls.update({driver.current_window_handle:lead['url'] if url==internal else url})
 monkeypatch.setattr('workbench.linkedin.time.sleep',lambda _:None)
 provider=SimpleNamespace(read=browser.read)
 first=run_reader(store,provider,1)
 assert first['matched_contacts']==1 and first['added']==1 and not first['review_cases']
 assert store.list('replies')[0]['body']=='Fixture reply from the actual participant'
 assert driver.current_window_handle=='parent' and driver.current_url==thread
 second=run_reader(store,provider,1)
 assert second['added']==0 and second['duplicates']==1
