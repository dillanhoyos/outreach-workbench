"""Read-only LinkedIn navigation. Model output cannot supply arbitrary URLs/actions."""
import re
from urllib.parse import urlsplit, quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from .errors import ProviderError
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

    def verify(self): return self.linkedin.require_account()

    def snapshot(self, url):
        self.linkedin.navigate(url)
        driver = self.linkedin.browser()
        WebDriverWait(driver, 12).until(lambda d:d.find_elements(By.TAG_NAME,'main'))
        self.linkedin.check()
        # Capture only main professional content. Sidebar suggestions and activity
        # must not be mistaken for the person's employer or experience.
        data = driver.execute_script('''
          const main = document.querySelector('main');
          const links = [...main.querySelectorAll('a[href]')].filter(a=>a.getClientRects().length)
            .map(a=>({url:a.href,label:(a.innerText||a.getAttribute('aria-label')||'').slice(0,300)}));
          let text = main.innerText;
          main.querySelectorAll('aside,nav,section').forEach(e=>{
            if(e.matches('aside,nav') || e.querySelector('#activity,#recommendations,#interests,#people-also-viewed'))
              text=text.replace(e.innerText,'');
          });
          return {title:main.querySelector('h1')?.innerText||'',text,links};
        ''')
        return {'url':driver.current_url,'title':data['title'][:200],
                'text':re.sub(r'\s+',' ',data['text']).strip()[:18000], 'links':data['links'][:120]}

    def search(self, query):
        page = self.snapshot('https://www.linkedin.com/search/results/people/?keywords='+quote(query,safe=''))
        links = {}
        for link in page['links']:
            try: url = research_url(link['url'],'profile')
            except ValueError: continue
            links.setdefault(url,{'url':url,'label':link['label']})
        return page, list(links.values())[:20]

    def profile(self, url):
        safe = research_url(url,'profile')
        page = self.snapshot(safe)
        if profile_key(page['url']) != profile_key(safe):
            raise ProviderError('Profile redirected to a different identity. Research stopped.')
        page['url'] = safe
        companies = {}
        for link in page['links']:
            try: company = research_url(link['url'],'company')
            except ValueError: continue
            companies.setdefault(company, {'url':company,'label':link['label']})
        page['companies'] = list(companies.values())[:12]
        page.pop('links',None)
        return page

    def company(self, url):
        page = self.snapshot(research_url(url,'company'))
        # Numeric/company-slug redirects are recorded as source provenance.
        research_url(page['url'],'company')
        page.pop('links',None)
        return page
