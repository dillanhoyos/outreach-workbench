"""Read-only LinkedIn navigation. Model output cannot supply arbitrary URLs/actions."""
import re
import hashlib
from .store import now
from urllib.parse import urlsplit, quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from .errors import ProviderError, ProfileIdentityError
from .store import profile_key


def research_url(value, kind):
    u = urlsplit(value)
    host = u.hostname or ''
    if u.scheme != 'https' or u.username or u.password or u.port not in (None,443):
        raise ValueError('Invalid research URL')
    if host not in ('linkedin.com','www.linkedin.com') and not (len(host.split('.')[0]) == 2 and host.endswith('.linkedin.com')):
        raise ValueError('Research is limited to LinkedIn pages')
    if kind == 'profile':
        profile_key(value)
        return 'https://www.linkedin.com' + u.path.rstrip('/') + '/'
    if kind == 'company' and re.fullmatch(r'/company/[a-zA-Z0-9_%.-]+/(?:about/?)?',u.path):
        return 'https://www.linkedin.com/company/' + u.path.split('/')[2] + '/about/'
    raise ValueError('Unsupported research page')


class ResearchBrowser:
    def __init__(self, linkedin): self.linkedin = linkedin

    def ensure_ready(self): return self.linkedin.require_session()

    def snapshot(self, url):
        self.linkedin.navigate(url)
        driver = self.linkedin.browser()
        # LinkedIn 404/unavailable pages have no <main>; classify the navigation
        # before waiting for profile markup. navigate() already checks auth/429.
        if urlsplit(url).path.startswith('/in/'):
            try:
                same_identity=profile_key(driver.current_url)==profile_key(url)
            except ValueError:
                same_identity=False
            if not same_identity:
                raise ProfileIdentityError(url,driver.current_url)
        WebDriverWait(driver, 12).until(lambda d:d.find_elements(By.TAG_NAME,'main'))
        self.linkedin.check()
        # Capture only main professional content. Sidebar suggestions and activity
        # must not be mistaken for the person's employer or experience.
        data = driver.execute_script(r'''
          const main = document.querySelector('main');
          const heading = main.querySelector('h1') || main.querySelector('section h2');
          const top = heading?.closest('section');
          const headline = top?.querySelector('.text-body-medium')?.innerText ||
            [...(top?.querySelectorAll('p') || [])].find(e=>e.getClientRects().length &&
              e.innerText.trim() && !/^(?:[·\s]*(?:1st|2nd|3rd|3rd\+)|he\/him|she\/her|they\/them)$/i.test(e.innerText.trim()))?.innerText || '';
          const excluded = [...main.querySelectorAll('aside,nav,footer,section')].filter(e=>
            e.matches('aside,nav,footer') || e.querySelector('#activity,#recommendations,#interests,#people-also-viewed') ||
            /^(Activity|Actividad|Recommendations|Recomendaciones|Interests|Intereses|More profiles for you|Explore Premium profiles)$/i.test(
              e.querySelector('h2,h3')?.innerText.trim() || ''));
          const links = [...main.querySelectorAll('a[href]')].filter(a=>a.getClientRects().length && !excluded.some(e=>e.contains(a)))
            .map(a=>({url:a.href,label:(a.innerText||a.getAttribute('aria-label')||'').slice(0,300)}));
          let text = main.innerText;
          excluded.forEach(e=>{text=text.replace(e.innerText,'');});
          // A post may expose the employer URL, but is never role evidence.
          // Only admit company links whose full label occurs in the profile headline.
          const clean=s=>s.toLocaleLowerCase().replace(/\s+/g,' ').trim();
          if (location.pathname.startsWith('/in/') && headline) {
            for (const a of main.querySelectorAll('a[href*="/company/"]')) {
              const label=a.innerText.trim();
              if (a.getClientRects().length && label.length>2 && clean(headline).includes(clean(label)))
                links.push({url:a.href,label:label.slice(0,300)});
            }
          }
          return {title:heading?.innerText||'',headline,text,links};
        ''')
        return {'url':driver.current_url,'requested_url':url,'captured_at':now(),
                'content_hash':hashlib.sha256(data['text'].encode()).hexdigest(),
                'text_truncated':len(data['text'])>18000,'title':data['title'][:200],
                'headline':re.sub(r'\s+',' ',data['headline']).strip()[:600],
                'text':re.sub(r'\s+',' ',data['text']).strip()[:18000], 'links':data['links'][:120]}

    def search(self, query):
        page = self.snapshot('https://www.linkedin.com/search/results/people/?keywords='+quote(query,safe=''))
        # Read only each result's primary person link, excluding mutual contacts.
        driver=self.linkedin.browser()
        primary=driver.execute_script('''
          return [...document.querySelectorAll('main [role="listitem"], main li.reusable-search__result-container')]
            .filter(card=>!card.closest('aside'))
            .map(card=>card.querySelector('a[href*="/in/"]'))
            .filter(a=>a && a.getClientRects().length)
            .map(a=>({url:a.href,label:(a.innerText||a.getAttribute('aria-label')||'').slice(0,300)}));
        ''')
        links = {}
        for link in primary:
            try: url = research_url(link['url'],'profile')
            except ValueError: continue
            links.setdefault(url,{'url':url,'label':link['label']})
        return page, list(links.values())[:20]

    def profile(self, url):
        safe = research_url(url,'profile')
        page = self.snapshot(safe)
        try:
            same_identity=profile_key(page['url']) == profile_key(safe)
        except ValueError:
            same_identity=False
        if not same_identity:
            raise ProfileIdentityError(safe,page['url'])
        page['url'] = safe
        companies = {}
        for link in page['links']:
            try: company = research_url(link['url'],'company')
            except ValueError: continue
            companies.setdefault(company, {'url':company,'label':link['label']})
        page['companies'] = list(companies.values())[:12]
        page['recommendations']=self.recommended_profiles(safe)
        page.pop('links',None)
        return page

    def company(self, url):
        page = self.snapshot(research_url(url,'company'))
        # Numeric/company-slug redirects are recorded as source provenance.
        research_url(page['url'],'company')
        page.pop('links',None)
        return page

    def evidence_image(self, url):
        """Capture the profile header in the same serial browser, without navigation."""
        driver=self.linkedin.browser()
        self.linkedin.check()
        if profile_key(driver.current_url)!=profile_key(url):
            raise ProfileIdentityError(url,driver.current_url)
        heading=driver.find_element(By.CSS_SELECTOR,'main h1, main section h2')
        section=driver.execute_script("return arguments[0].closest('section') || arguments[0]",heading)
        content=section.screenshot_as_png
        if len(content)>2_000_000:raise ProviderError('Profile image exceeds capture limit.')
        return content

    def recommended_profiles(self, parent_url):
        """Read recommendation hints separately, only from the expected profile."""
        driver=self.linkedin.browser()
        try:
            if profile_key(driver.current_url)!=profile_key(parent_url):return []
        except ValueError:return []
        recommended=driver.execute_script("""
          const sections=[...document.querySelectorAll('aside,section')].filter(e=>
            /^(More profiles for you|People also viewed|Personas que también vieron|Más perfiles para ti)$/i.test(
              e.querySelector('h2,h3')?.innerText.trim() || ''));
          return sections.flatMap(e=>[...e.querySelectorAll('a[href*="/in/"]')])
            .filter(a=>a.getClientRects().length && a.innerText.trim().length>3)
            .map(a=>({url:a.href,label:a.innerText.trim().slice(0,500)})).slice(0,24);
        """)
        hints={}
        for hint in recommended or []:
            try:link=research_url(hint['url'],'profile')
            except ValueError:continue
            if link!=parent_url and len(hint['label'])>len(hints.get(link,{}).get('label','')):
                hints[link]={'url':link,'label':hint['label']}
        return list(hints.values())[:12]
