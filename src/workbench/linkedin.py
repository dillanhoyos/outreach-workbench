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
from selenium.common.exceptions import TimeoutException, InvalidSessionIdException, StaleElementReferenceException
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
        self.invitation_receipt=None;self._invitation_audit=None

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
        entries=d.execute(Command.GET_LOG, {'type':'performance'})['value']
        if self.invitation_receipt:
            self.invitation_receipt.feed(entries)
            if self._invitation_audit:self._invitation_audit()
        for entry in entries:
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

    def topcard(self,expected_name=None):
        d=self.browser()
        def locate(_):
            candidates=[e for e in d.find_elements(By.CSS_SELECTOR,'main h1,main h2') if e.is_displayed()]
            headings=[e for e in candidates if not expected_name or normalized(e.text)==normalized(expected_name)]
            if not headings:return False
            h=headings[0]
            return d.execute_script("""
                const h=arguments[0];let e=h.parentElement;
                for(let n=0;e && n<18;n++,e=e.parentElement){
                  if(e.matches('main,body,article,aside'))return null;
                  const actions=Array.from(e.querySelectorAll('button,a,[role="button"]')).some(x=>x.getClientRects().length && ['Connect','Conectar','More','Más','Pending','Pendiente','Follow','Seguir'].includes((x.innerText||'').trim()));
                  if(actions && e.innerText.length<7000)return e;
                }return null;
            """,h)
        return WebDriverWait(d,12,ignored_exceptions=(StaleElementReferenceException,)).until(locate)

    def open_invitation(self,card,lead):
        controls=[e for e in card.find_elements(By.CSS_SELECTOR,'button,a,[role="button"]')
                  if e.is_displayed() and e.is_enabled() and e.text.strip() in ('Connect','Conectar')]
        if controls:
            if len(controls)!=1:raise ProviderError('Ambiguous recipient Connect controls. No click attempted.')
            controls[0].click();return
        self.unique_button(card,{'More','Más'}).click()
        from .invitation_receipt import invite_url_matches
        def observed(_):
            links=[e for e in self.browser().find_elements(By.CSS_SELECTOR,'a[href]') if e.is_displayed() and e.is_enabled()
                   and e.text.strip() in ('Connect','Conectar') and invite_url_matches(e.get_attribute('href') or '',lead['url'])]
            return links if links else False
        links=WebDriverWait(self.browser(),8).until(observed)
        if len(links)!=1:raise ProviderError('Ambiguous invitation link. No invitation control clicked.')
        self.check()
        if profile_key(self.browser().current_url)!=profile_key(lead['url']):raise ProviderError('Profile changed while opening invitation menu.')
        links[0].click()

    def invitation_form(self,lead):
        from .invitation_receipt import invite_url_matches
        def locate(d):
            candidates=d.find_elements(By.CSS_SELECTOR,'[role="dialog"]')
            candidates+=d.execute_script("""return Array.from(document.querySelector("#interop-outlet")?.shadowRoot?.querySelectorAll('[role="dialog"]') || [])""")
            dialogs=[e for e in candidates if e.is_displayed()]
            if len(dialogs)==1:return dialogs[0]
            if not dialogs and invite_url_matches(d.current_url,lead['url']):
                main=d.find_elements(By.CSS_SELECTOR,'main')
                if len(main)==1:return main[0]
            return False
        return WebDriverWait(self.browser(),8).until(locate)

    def collect_invitation(self):
        receipt=self.invitation_receipt
        if receipt is None:return
        try:receipt.feed(self.browser().execute(Command.GET_LOG,{'type':'performance'})['value'])
        except Exception:receipt.unavailable=True
        if self._invitation_audit:self._invitation_audit()
        if receipt.rate_limited:
            self.store.setting('linkedin_restriction',{'reason':'HTTP 429','at':datetime.now(timezone.utc).isoformat()})

    def invitation_feedback(self,lead):
        # Network first: a stale DOM or a renderer timeout cannot hide an accepted POST.
        self.collect_invitation()
        r=self.invitation_receipt
        if r.accepted:return 'network_200'
        if r.rate_limited:raise ProviderError('LinkedIn returned HTTP 429. Work stopped without retry.')
        if r.rejected:raise ProviderError('LinkedIn rejected the invitation request. No automatic retry.')
        if len(r.requests)>1:raise ProviderError('Multiple invitation requests observed. Review the receipt; no retry.')
        self.check()
        # check() can collect additional network events too.
        if r.accepted:return 'network_200'
        card=self.topcard(lead['name'])
        if profile_key(self.browser().current_url)!=profile_key(lead['url']):return False
        if any(e.is_displayed() and e.text.strip() in ('Pending','Pendiente') for e in card.find_elements(By.CSS_SELECTOR,'button,[role="button"]')):return 'pending'
        return False

    def send(self,lead):
        phase='session';clicked=False;self.invitation_receipt=None
        def audit():
            if lead.get('id'):
                self.store.invitation_audit(lead['id'],phase,clicked,self.invitation_receipt.snapshot() if self.invitation_receipt else {})
        def step(name):
            nonlocal phase
            phase=name;audit()
        def result(status,evidence):
            audit()
            return {'status':status,'evidence':evidence}
        self._invitation_audit=audit
        try:
            audit();self.require_session();step('profile_navigation')
            self.navigate(lead['url']);d=self.browser();step('profile_identity')
            def snapshot(_):
                card=self.topcard(lead['name'])
                headings=[h for h in card.find_elements(By.CSS_SELECTOR,'h1,h2') if h.is_displayed() and normalized(h.text)==normalized(lead['name'])]
                labels={e.text.strip() for e in card.find_elements(By.CSS_SELECTOR,'button,a,[role="button"]') if e.is_displayed()}
                return card,bool(headings),labels,card.text
            card,has_heading,labels,card_text=WebDriverWait(d,12,ignored_exceptions=(StaleElementReferenceException,)).until(snapshot)
            if profile_key(d.current_url)!=profile_key(lead['url']) or not has_heading:
                return result('blocked','Recipient identity mismatch; no send click attempted.')
            if labels & {'Pending','Pendiente'} or (labels & {'Message','Mensaje','Enviar mensaje'} and re.search(r'(?m)^\s*(?:·\s*)?(?:1st|1er|1º|1°)\s*$',card_text)):
                return result('skipped','Pending invitation or existing connection visible; no new send attempted.')
            if normalized(lead['company']) not in normalized(card_text):
                return result('blocked','Current company not corroborated in the profile top card; no send click attempted.')
            step('identity_verified')
            step('opening_invitation');self.open_invitation(card,lead)
            modal=self.invitation_form(lead)
            self.check()
            if modal.find_elements(By.CSS_SELECTOR,'input[type="email"]'):
                return result('blocked','Recipient email required; no send click attempted.')
            if not any(e.is_displayed() for e in modal.find_elements(By.CSS_SELECTOR,'textarea')):
                self.unique_button(modal,{'Add a note','Añadir una nota','Agregar una nota'}).click()
            def note_ready(_):
                current=self.invitation_form(lead)
                text=normalized(getattr(current,'text',''))
                if any(phrase in text for phrase in ('outoffreecustomnotes','nofreepersonalizedinvitations','sintepersonalizadasgratuitas','agotadolasnotas')):
                    return current,None
                fields=[e for e in current.find_elements(By.CSS_SELECTOR,'textarea') if e.is_displayed()]
                if len(fields)>1:raise ProviderError('Invitation note field is ambiguous.')
                return (current,fields) if fields else False
            modal,fields=WebDriverWait(d,8,ignored_exceptions=(StaleElementReferenceException,)).until(note_ready)
            if fields is None:
                step('custom_note_limit')
                return result('blocked','LinkedIn reports no free custom invitation notes remaining. No send click attempted; the approved note was not omitted.')
            fields[0].send_keys(lead['note'])
            if fields[0].get_attribute('value')!=lead['note']:raise ProviderError('Invitation note did not match the approved text.')
            self.check();button=self.unique_button(modal,{'Send','Enviar','Send invitation','Enviar invitación'})
            # Discard old network traffic before arming this verified one-recipient click.
            d.execute(Command.GET_LOG,{'type':'performance'})
            from .invitation_receipt import InvitationReceipt
            self.invitation_receipt=InvitationReceipt(lead['url'],time.time())
            clicked=True;step('send_click_started')
            button.click();step('awaiting_confirmation')
            outcome=WebDriverWait(d,15,poll_frequency=.3).until(lambda _:self.invitation_feedback(lead))
            step('confirmed_'+outcome)
            return result('confirmed','Invitation POST returned HTTP 200 for this verified recipient and send attempt.' if outcome=='network_200' else 'Recipient identity verified; Pending visible after the single Send click.')
        except Exception as exc:
            if clicked:
                self.collect_invitation()
                if self.invitation_receipt.accepted:
                    step('confirmed_network_200_after_error')
                    return result('confirmed','Invitation POST returned HTTP 200 despite a browser timeout/error. No second click was made.')
            # A failure before any invitation control is clicked is known not sent.
            status='blocked' if phase in ('session','profile_navigation','profile_identity','identity_verified') else 'uncertain'
            if clicked:status='uncertain'
            message=str(exc) if isinstance(exc,ProviderError) else type(exc).__name__
            return result(status,f'Invitation stopped at {phase}: {message}. '+('No send click attempted.' if not clicked else 'Send click attempted once; no conclusive acceptance. Never automatically retry.'))
        finally:self.invitation_receipt=None;self._invitation_audit=None

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
