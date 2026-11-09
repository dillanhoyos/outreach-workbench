"""Hosted web discovery plus independently captured public-source evidence."""
import http.client
import json
import ipaddress
import socket
import ssl
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
from pydantic import BaseModel, ConfigDict, Field
from .errors import ProviderError
from .research_model import reason
from .research_browser import research_url


class Prospect(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str = Field(max_length=200)
    company: str = Field(max_length=300)
    profile_url: str = Field(max_length=1000)
    source_url: str = Field(max_length=1000)


class Shortlist(BaseModel):
    model_config=ConfigDict(extra='forbid')
    prospects: list[Prospect] = Field(max_length=20)


class CompanyFit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    qualified: bool
    reason: str = Field(max_length=1800)
    quotes: list[str] = Field(max_length=12)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.links=[];self.hidden=0;self.title=[];self.in_title=False;self.yc_company=None
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.hidden+=1
        # YC ships its public directory facts in the page's Inertia payload.
        # Capture only explicit company/founder fields, never unrelated page data.
        payload=dict(attrs).get('data-page')
        if payload:
            try:
                data=json.loads(payload)
                if data.get('component')=='ycdc_new/pages/Companies/ShowPage':
                    self.yc_company=data.get('props',{}).get('company')
            except (ValueError,TypeError):pass
        if tag=='title':self.in_title=True
        if tag=='a':
            href=dict(attrs).get('href')
            if href:self.links.append(href)
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript'):self.hidden=max(0,self.hidden-1)
        if tag=='title':self.in_title=False
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
        if self.in_title:self.title.append(data)


def public_address(url):
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise ValueError('Only public HTTPS sources are supported')
    addresses=socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private network sources are not allowed')
    return u,addresses[0][4][0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address):super().__init__(host,timeout=15);self.address=address
    def connect(self):
        # Pin the validated public address, retaining TLS hostname verification.
        sock=socket.create_connection((self.address,443),timeout=self.timeout)
        try:self.sock=ssl.create_default_context().wrap_socket(sock,server_hostname=self.host)
        except Exception:sock.close();raise


def fetch_source(url):
    # YC job listings omit product facts and founder links present on the company
    # overview. Resolve directory subpages to that canonical primary source.
    parsed=urlsplit(url)
    match=re.fullmatch(r'/companies/([a-zA-Z0-9_-]+)(?:/.*)?',parsed.path)
    if parsed.scheme=='https' and parsed.hostname in ('www.ycombinator.com','ycombinator.com') and match and not parsed.username and not parsed.password and parsed.port in (None,443):
        url='https://www.ycombinator.com/companies/'+match.group(1)
    for _ in range(4):
        u,address=public_address(url);connection=PinnedHTTPS(u.hostname,address)
        try:
            connection.request('GET',(u.path or '/') + ('?'+u.query if u.query else ''),headers={'User-Agent':'OutreachWorkbench/0.1 research','Accept':'text/html'})
            response=connection.getresponse()
            if response.status==429:raise ProviderError('Web source returned HTTP 429. Research stopped without retry.')
            if response.status in (301,302,303,307,308):
                url=urljoin(url,response.getheader('Location',''));continue
            if response.status!=200:raise ValueError('Source is unavailable')
            if 'text/html' not in response.getheader('Content-Type',''):raise ValueError('Source must be an HTML page')
            body=response.read(2_000_001)
            if len(body)>2_000_000:raise ValueError('Source exceeds capture limit')
        finally:connection.close()
        parser=PageText();parser.feed(body.decode('utf-8',errors='replace'))
        if u.hostname in ('www.ycombinator.com','ycombinator.com') and isinstance(parser.yc_company,dict):
            company=parser.yc_company
            for field in ('name','batch','batch_name','one_liner','long_description'):
                value=company.get(field)
                if isinstance(value,str):parser.parts.append(field+': '+value)
            for founder in company.get('founders',[]):
                if not isinstance(founder,dict):continue
                for field in ('full_name','title','founder_bio'):
                    if isinstance(founder.get(field),str):parser.parts.append(field+': '+founder[field])
                if isinstance(founder.get('linkedin_url'),str):parser.links.append(founder['linkedin_url'])
        return {'url':url,'title':' '.join(parser.title)[:300],
                'text':re.sub(r'\s+',' ',' '.join(parser.parts)).strip()[:35000],
                'links':[urljoin(url,x) for x in parser.links][:500]}
    raise ValueError('Too many source redirects')


def discover(engine,plan,run_id,guard):
    from .research import fold
    def event(detail):
        action=detail.get('action') or {}
        engine.event(run_id,'web_search',{'query':detail.get('query','')[:1000],
            'url':action.get('url',''),'reason':'Hosted web search: '+str(action.get('type','search'))})
    engine.event(run_id,'web_search',{'reason':'Finding primary company evidence before visiting LinkedIn. Hosted searches appear here, not in the browser.'})
    with engine.store.db() as db:
        known=[r[0] for r in db.execute('SELECT url FROM leads')]
        if plan.get('exclude_visited'):
            known.extend(r[0] for r in db.execute('SELECT url FROM research_visits'))
    data=reason(engine.auth,
        'Use web search now to shortlist people matching the brief. Search company-first. '
        'Use primary sources: accelerator directories for exact batch, official company pages for product/sector. '
        'Find up to the requested shortlist_size promising current founders/professionals across distinct companies where possible. '
        'Return primary company source URLs establishing the company criteria. You may leave name and profile_url empty: the controller will extract founder LinkedIn links directly from the primary page. '
        'For YC briefs prefer the official YC company directory page, which lists batch, product, founders and LinkedIn links. '
        'Do not invent URLs or use remembered facts without searching. Exclude known profiles. '
        'Do not silently broaden hard criteria. Return fewer when evidence is unavailable.',
        {'brief':plan['prompt'],'queries':plan['queries'],'shortlist_size':min(plan['limit']+2,20),'known_profiles':known},
        Shortlist.model_json_schema(),engine.stop,timeout=min(240,plan['max_minutes']*60),web=True,on_search=event)
    shortlist=Shortlist.model_validate(data);cache={};links=[];seen=set()
    for item in shortlist.prospects:
        guard()
        if item.source_url not in cache:
            engine.event(run_id,'web_source',{'url':item.source_url,'reason':'Capturing primary evidence and checking all company criteria before LinkedIn.'})
            try:page=fetch_source(item.source_url)
            except (ValueError,OSError,http.client.HTTPException):
                engine.event(run_id,'web_excluded',{'url':item.source_url,'reason':'Primary source could not be captured; not sent to LinkedIn.'});continue
            fit=engine.ask('Check ALL company-level requirements in the brief using only this captured primary source. '
                'Exact accelerator batch must match when specified. Agent memory and monitoring count only when the brief includes them. '
                'Ignore person-level role/location requirements here; LinkedIn will confirm those. '
                'Provide exact contiguous quotations supporting each required company criterion. Missing or ambiguous evidence means qualified=false.',
                {'brief':plan['prompt'],'source':page},CompanyFit)
            cache[item.source_url]=(page,fit)
        page,fit=cache[item.source_url]
        observed=set()
        for href in page['links']:
            try:observed.add(research_url(href,'profile'))
            except ValueError:pass
        if (not fit.qualified or not fit.quotes or any(not fold(q) or fold(q) not in fold(page['text']) for q in fit.quotes)
                or not observed or fold(item.company) not in fold(page['title'])):
            engine.event(run_id,'web_excluded',{'url':page['url'],'reason':fit.reason+' Primary quotation, company identity and profile-link checks must also pass.'});continue
        with engine.store.db() as db:held=engine.blocked(item.company,db)
        if held:continue
        if item.profile_url:
            try:chosen=[research_url(item.profile_url,'profile')]
            except ValueError:chosen=[]
        else:chosen=sorted(observed)
        for url in chosen:
            if url not in observed or url in seen:continue
            seen.add(url)
            links.append({'url':url,'label':item.name+' — '+item.company,'web_company':{
                **page,'company_criteria_quotes':fit.quotes,'company_assessment':fit.reason}})
    counts={}
    def priority(link):
        key=link['web_company']['url'];count=counts.get(key,0);counts[key]=count+1;return count
    links.sort(key=priority)
    engine.event(run_id,'web_shortlist',{'reason':f'{len(links)} profiles have captured company evidence. Now confirming current roles on LinkedIn.'})
    return links
