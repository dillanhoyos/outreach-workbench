"""Visible-browser adapter. No credential capture, private API calls or retries.

Selectors are intentionally conservative: an ambiguous layout stops the action.
The reader only imports incoming messages matched to a known CRM profile.
"""
import base64
import hashlib
import re
import time
import unicodedata
from datetime import datetime,timezone
from urllib.parse import urlsplit
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.command import Command
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, InvalidSessionIdException
from .store import profile_key
from .errors import ProviderError


def normalized(s):
    return ''.join(x for x in unicodedata.normalize('NFKD',s).casefold() if x.isalnum())


def message_time(urn):
    m=re.search(r',2-([A-Za-z0-9_=+-]+)\)$',urn or '')
    if not m:raise ProviderError('Unrecognized message identifier; cannot verify its timestamp.')
    try:
        raw=base64.urlsafe_b64decode(m[1]+'='*(-len(m[1])%4)).decode()
        stamp=int(re.match(r'^(\d{13})',raw)[1])/1000
        dt=datetime.fromtimestamp(stamp,timezone.utc)
        if not datetime(2003,1,1,tzinfo=timezone.utc)<=dt<=datetime.now(timezone.utc):raise ValueError()
        return dt.isoformat()
    except Exception:raise ProviderError('Cannot verify message date.') from None


def incoming_rows(messages, lead, participant_url, thread):
    """Only verified sender URLs become replies; connection events do not."""
    allowed={profile_key(participant_url),profile_key(lead['url'])}
    rows=[]
    for message in messages:
        if not message.get('sender') or not message.get('text') or not message.get('id'):continue
        if profile_key(message['sender']) not in allowed:continue
        rows.append({'ident':hashlib.sha256((thread+'\n'+message['id']).encode()).hexdigest(),
            'lead_id':lead['id'],'body':message['text'],'received':message_time(message['id']),'thread':thread})
    return rows


class LinkedInBrowser:
    def __init__(self,settings,store):
        self.settings=settings;self.store=store;self.driver=None

    def browser(self):
        if self.driver is None:
            options=webdriver.ChromeOptions()
            options.add_argument('--user-data-dir=/home/seluser/workbench-profile')
            options.add_argument('--window-size=1440,1000')
            options.set_capability('goog:loggingPrefs',{'performance':'ALL'})
            saved=self.store.setting('browser_session')
            if saved:
                class AttachedDriver(webdriver.Remote):
                    def start_session(this, capabilities):
                        this.session_id=saved['id']
                        this.caps=saved['capabilities']
                candidate=AttachedDriver(command_executor=self.settings.selenium_url,options=options)
                try:
                    candidate.current_url
                except Exception:
                    raise ProviderError('Saved browser session is unavailable. Restart the browser container and use Reset browser connection; do not retry uncertain invitations.') from None
                self.driver=candidate
            else:
                self.driver=webdriver.Remote(command_executor=self.settings.selenium_url,options=options)
                self.store.setting('browser_session',{'id':self.driver.session_id,'capabilities':self.driver.capabilities})
                self.driver.maximize_window()
            self.driver.set_page_load_timeout(35)
        return self.driver

    def reset_connection(self):
        # Explicit operator action after restarting the isolated container.
        # Never deletes cookies or changes an invitation outcome.
        if self.driver is not None:
            self.driver.command_executor.close()
        self.driver=None
        self.store.setting('browser_session',False)
        return {'message':'Connection metadata cleared. Start login again after restarting the browser container. Saved profile cookies were preserved.'}

    def close_transport(self):
        if self.driver is not None:self.driver.command_executor.close()

    def check(self):
        d=self.browser();path=urlsplit(d.current_url).path.lower()
        if any(path.startswith(x) for x in ('/login','/checkpoint','/authwall','/challenge','/uas/')):
            raise ProviderError('LinkedIn sign-in or verification required. Open the browser and complete it manually.')
        body=d.find_element(By.TAG_NAME,'body').text.casefold()
        for phrase in ('weekly invitation limit','límite semanal de invitaciones','commercial use limit','monthly limit',
                       'límite de uso comercial','account has been restricted','cuenta ha sido restringida','too many requests'):
            if phrase in body:
                self.store.setting('linkedin_restriction',{'reason':phrase,'at':datetime.now(timezone.utc).isoformat()})
                raise ProviderError('LinkedIn reported a restriction. Work stopped; review it manually before continuing.')
        # A real rate-limit response is never hidden behind a successful page load.
        import json
        for entry in d.execute(Command.GET_LOG, {'type':'performance'})['value']:
            try:m=json.loads(entry['message'])['message']
            except (KeyError,ValueError):continue
            response=m.get('params',{}).get('response',{})
            host=urlsplit(response.get('url','')).hostname or ''
            if m.get('method')=='Network.responseReceived' and response.get('status')==429 and (host=='linkedin.com' or host.endswith('.linkedin.com')):
                self.store.setting('linkedin_restriction',{'reason':'HTTP 429','at':datetime.now(timezone.utc).isoformat()})
                raise ProviderError('LinkedIn returned HTTP 429. Work stopped without retry.')

    def navigate(self,url):
        self.browser().get(url);self.check()

    def start_login(self):
        try:
            self.browser().get('https://www.linkedin.com/login')
        except InvalidSessionIdException:
            raise ProviderError('Saved browser session is unavailable. Restart the browser container and use Reset browser connection; saved cookies are preserved.') from None
        return {'message':'Open the browser viewer, sign in and complete 2FA. Then return to Research and start your reviewed plan.'}

    def require_session(self):
        if self.store.setting('linkedin_restriction'):
            raise ProviderError('A LinkedIn restriction is recorded. Review it in the browser and explicitly clear it after it is resolved.')
        # Use the current browser session; no profile URL or saved identity required.
        self.navigate('https://www.linkedin.com/feed/')

    def unique_button(self,scope,labels):
        matches=[e for e in scope.find_elements(By.CSS_SELECTOR,'button,[role="button"]')
                 if e.is_displayed() and e.is_enabled() and e.text.strip() in labels]
        if len(matches)!=1:raise ProviderError('Expected one unambiguous action button; LinkedIn layout may have changed.')
        return matches[0]

    def connect_button(self, card):
        # Jev can only choose among already validated, recipient-scoped controls.
        labels = {'Connect', 'Conectar'}
        def candidates():
            return [e for e in card.find_elements(By.CSS_SELECTOR, 'button,[role="button"]')
                    if e.is_displayed() and e.is_enabled() and e.text.strip() in labels]
        matches = candidates()
        if len(matches) == 1:
            return matches[0]
        if not matches or getattr(self.settings, 'browser_advisor', 'none') != 'jev':
            raise ProviderError('Expected one unambiguous Connect control. Review the browser layout.')
        from .jev import JevAdvisor
        page_url = self.browser().current_url
        controls = [{'text': e.text.strip(), 'label': e.get_attribute('aria-label') or ''} for e in matches]
        from .connections import JevConnection
        selected = JevAdvisor(JevConnection(self.settings).key()).choose_connect(controls)
        # Never use a model-generated selector or URL, or act on a changed page.
        self.check()
        current = candidates()
        if self.browser().current_url != page_url or current != matches or any(
                e.text.strip() != c['text'] or (e.get_attribute('aria-label') or '') != c['label']
                for e, c in zip(current, controls)):
            raise ProviderError('Connect controls changed during Jev selection. No click attempted.')
        return current[selected]

    def topcard(self):
        d=self.browser()
        WebDriverWait(d,12).until(lambda d:d.find_elements(By.CSS_SELECTOR,'main h1'))
        h=d.find_element(By.CSS_SELECTOR,'main h1')
        return h.find_element(By.XPATH,'ancestor::section[1]')

    def send(self,lead):
        self.require_session()
        self.navigate(lead['url'])
        d=self.browser();card=self.topcard()
        if profile_key(d.current_url)!=profile_key(lead['url']) or normalized(card.find_element(By.CSS_SELECTOR,'h1').text)!=normalized(lead['name']):
            return {'status':'blocked','evidence':'Recipient identity mismatch; no send attempted.'}
        if normalized(lead['company']) not in normalized(card.text):
            return {'status':'blocked','evidence':'Current company not corroborated in the profile top card; no send attempted.'}
        labels={e.text.strip() for e in card.find_elements(By.CSS_SELECTOR,'button,[role="button"]') if e.is_displayed()}
        if labels & {'Pending','Pendiente','Message','Mensaje','Enviar mensaje'}:
            return {'status':'skipped','evidence':'Pending invitation or existing connection visible; no send attempted.'}
        # Only a directly visible top-card Connect button is supported. Never
        # select a recommendation card or a global matching button.
        self.connect_button(card).click()
        modal=WebDriverWait(d,8).until(lambda d:next((e for e in d.find_elements(By.CSS_SELECTOR,'[role="dialog"]') if e.is_displayed()),False))
        self.check()
        if modal.find_elements(By.CSS_SELECTOR,'input[type="email"]'):
            return {'status':'blocked','evidence':'Recipient email required; no send attempted.'}
        self.unique_button(modal,{'Add a note','Añadir una nota','Agregar una nota'}).click()
        fields=[e for e in modal.find_elements(By.CSS_SELECTOR,'textarea') if e.is_displayed()]
        if len(fields)!=1:raise ProviderError('Invitation note field is ambiguous.')
        fields[0].send_keys(lead['note'])
        if fields[0].get_attribute('value')!=lead['note']:raise ProviderError('Invitation note did not match the approved text.')
        self.check()
        self.unique_button(modal,{'Send','Enviar','Send invitation','Enviar invitación'}).click()
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            self.check()
            if any(e.is_displayed() and e.text.strip() in ('Pending','Pendiente') for e in card.find_elements(By.CSS_SELECTOR,'button,[role="button"]')):
                return {'status':'confirmed','evidence':'Recipient identity verified; Pending visible after the single Send click.'}
            time.sleep(.5)
        return {'status':'uncertain','evidence':'Send clicked once; no conclusive Pending state observed. Never automatically retry.'}

    def read(self,leads,limit=100):
        self.require_session();self.navigate('https://www.linkedin.com/messaging/')
        d=self.browser();known={profile_key(x['url']):x for x in leads}
        seen=set();rows=[];cases=[];checked=0;stable=0
        deadline=time.monotonic()+600
        WebDriverWait(d,12).until(lambda d:d.find_elements(By.CSS_SELECTOR,'.msg-conversation-listitem'))
        while checked<limit and time.monotonic()<deadline:
            cards=d.execute_script("return [...document.querySelectorAll('.msg-conversation-listitem')].map(e=>({id:e.id,name:e.querySelector('h3')?.innerText?.trim()}))")
            fresh=[c for c in cards if c['id'] and c['id'] not in seen]
            for card in fresh:
                if checked>=limit or time.monotonic()>=deadline:break
                seen.add(card['id']);checked+=1
                try:
                    item=d.find_element(By.ID,card['id'])
                    if item.find_element(By.CSS_SELECTOR,'h3').text.strip()!=card['name']:raise ProviderError('Conversation changed while opening.')
                    item.find_element(By.CSS_SELECTOR,'.msg-conversation-listitem__link').click()
                    header=WebDriverWait(d,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'.msg-thread__link-to-profile'))
                    self.check()
                    if header.find_element(By.CSS_SELECTOR,'h2').text.strip()!=card['name']:raise ProviderError('Conversation header mismatch.')
                    thread=d.current_url
                    if urlsplit(thread).path.startswith('/messaging/thread/') is False:raise ProviderError('Conversation URL not verified.')
                    internal=header.get_attribute('href')
                    # Resolve the exact participant in a temporary tab. Never match by name alone.
                    parent=d.current_window_handle
                    d.switch_to.new_window('tab')
                    try:
                        self.navigate(internal)
                        WebDriverWait(d,10).until(lambda d:d.find_elements(By.CSS_SELECTOR,'main h1'))
                        links=d.find_elements(By.CSS_SELECTOR,'a[href*="/overlay/contact-info/"]')
                        keys={profile_key(e.get_attribute('href').split('/overlay/contact-info/')[0]) for e in links}
                        if not keys:keys={profile_key(d.current_url)}
                        matches=keys & known.keys()
                        if len(matches)!=1:continue
                        lead=known[next(iter(matches))]
                    finally:
                        d.close();d.switch_to.window(parent)
                    messages=d.execute_script('''let sender=null;return [...document.querySelectorAll('.msg-thread .msg-s-event-listitem')].map(e=>{const a=e.querySelector('.msg-s-message-group__meta a[href*="/in/"]')||e.querySelector('a.msg-s-event-listitem__link');if(a)sender=a.href;return {id:e.getAttribute('data-event-urn'),sender,text:e.querySelector('.msg-s-event-listitem__body')?.innerText||''};});''')
                    rows.extend(incoming_rows(messages,lead,internal,thread))
                except ProviderError as exc:
                    if self.store.setting('linkedin_restriction') or 'sign-in' in str(exc):raise
                    cases.append({'conversation':card['id'],'reason':str(exc)})
                except Exception:
                    cases.append({'conversation':card['id'],'reason':'Layout or identity could not be verified.'})
            moved=d.execute_script("const e=document.querySelector('.msg-conversations-container__conversations-list');if(!e)return false;const p=e.scrollTop;e.scrollTop+=e.clientHeight*.85;return e.scrollTop!==p")
            stable=stable+1 if not fresh and not moved else 0
            if stable>=3:break
            time.sleep(.6)
        self.store.setting('last_reader_report',{'unique_conversations_checked':checked,'incoming_messages_observed':len(rows),
            'review_cases':cases,'limit':limit,'scope':'Current inbox, currently loaded messages only; no historical completeness claim.'})
        return rows
