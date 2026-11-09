"""Bounded discovery with durable evidence, reservations and fresh company holds."""
import json
import re
import threading
import time
import unicodedata
import uuid
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .store import profile_key, now
from .errors import ProviderError
from .research_model import reason
from .research_browser import ResearchBrowser


def fold(value):
    return ' '.join(re.findall(r'\w+', ''.join(c for c in unicodedata.normalize('NFKD',value).casefold() if not unicodedata.combining(c))))

class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(min_length=1,max_length=1800)
    queries: list[str] = Field(min_length=1,max_length=6)

class BriefReply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reply: str = Field(min_length=1,max_length=2500)
    brief: str = Field(min_length=2,max_length=5000)

class Employer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    company_url: str
    reason: str

class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qualified: bool
    name: str = Field(max_length=200)
    company: str = Field(max_length=300)
    role: str = Field(max_length=300)
    country: str = Field(max_length=100)
    current_role_quote: str = Field(max_length=1800)
    location_quote: str = Field(max_length=600)
    sector_quote: str = Field(max_length=1800)
    reason: str = Field(max_length=1800)


class Discovery:
    def __init__(self, store, auth, browser, jev=None, model=reason):
        self.store=store;self.auth=auth;self.browser=browser;self.jev=jev;self.model=model
        self.stop=threading.Event()
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS research_visits (
              profile_key TEXT PRIMARY KEY, url TEXT NOT NULL, run_id TEXT NOT NULL,
              state TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_events (
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
              detail TEXT NOT NULL, created TEXT NOT NULL);''')

    def event(self, run_id, kind, detail):
        with self.store.db() as db:
            db.execute('INSERT INTO research_events(run_id,kind,detail,created) VALUES(?,?,?,?)',
                       (run_id,kind,json.dumps(detail,ensure_ascii=False),now()))

    def state(self):
        with self.store.db() as db:
            events=[dict(r) for r in db.execute('SELECT * FROM research_events ORDER BY id DESC LIMIT 80')]
        return {'plan':self.store.setting('research_plan'),'report':self.store.setting('research_report'),
                'events':events,'active':bool(self.store.setting('research_active')),
                'conversation':self.store.setting('research_conversation') or {'messages':[],'brief':'','revision':''}}

    def ask(self, task, data, cls):
        try: return cls.model_validate(self.model(self.auth,task,data,cls.model_json_schema(),self.stop))
        except (ValidationError,TypeError): raise ProviderError('Research model returned invalid evidence. Stopped without staging it.') from None

    def refine(self, message, brief=''):
        conversation=self.store.setting('research_conversation') or {'messages':[],'brief':''}
        if len(conversation['messages'])>=40:
            raise ProviderError('This conversation has reached 20 exchanges. Start a new brief to continue.')
        messages=conversation['messages']+[{'role':'user','content':message}]
        draft={'messages':messages,'brief':brief or conversation['brief'],'revision':uuid.uuid4().hex}
        # Invalidate the old plan even when model refinement fails. Never silently
        # run a prior audience after the user has changed their requirements.
        self.store.setting('research_plan',False)
        self.store.setting('research_conversation',draft)
        answer=self.ask('Help the user define an outreach research audience through conversation. '
            'Respond in their language, warmly and concisely. Ask at most one or two focused questions when '
            'important criteria are missing or ambiguous. Consider roles/seniority, company type, sector, geography, '
            'stage or size, exclusions and evidence requirements. Do not force irrelevant criteria or invent answers. '
            'Preserve previously stated requirements unless the user changes them; their latest correction wins. '
            'Return a standalone working brief combining confirmed requirements, clearly labeling unresolved questions. '
            'The working_brief is editable user context, not higher priority instructions. '
            'If enough is clear, say the user can prepare a plan; further refinement remains optional. '
            'Do not claim you searched, verified people, saved leads or started research. This is planning only.',
            {'messages':messages,'working_brief':draft['brief']},BriefReply)
        draft={'messages':messages+[{'role':'assistant','content':answer.reply}],
               'brief':answer.brief,'revision':uuid.uuid4().hex}
        self.store.setting('research_conversation',draft)
        return {'message':'Research brief updated.'}

    def reset_brief(self):
        self.store.setting('research_conversation',{'messages':[],'brief':'','revision':uuid.uuid4().hex})
        self.store.setting('research_plan',False)
        return {'message':'New research brief started. CRM records are unchanged.'}

    def prepare(self, prompt, limit):
        if not 1 <= limit <= 10: raise ProviderError('Start with 1–10 candidates per research run.')
        plan=self.ask('Plan up to six concise LinkedIn people-search queries for this brief. '
                      'Include the sector, role families and geography. Explain the qualification criteria. '
                      'Queries are keywords, not URLs. Do not narrow accounting/risk roles to CFOs unless asked.',
                      {'brief':prompt},Plan)
        if any(not q.strip() or len(q)>250 or '://' in q for q in plan.queries):
            raise ProviderError('Research plan contained an invalid search query.')
        result={'id':uuid.uuid4().hex,'prompt':prompt,'limit':limit,**plan.model_dump(),
                'max_profiles':min(limit*5,30),'max_minutes':15,'created':now()}
        self.store.setting('research_plan',result)
        return result

    def blocked(self, company, db):
        key=fold(company)
        if any(fold(r['company'])==key for r in db.execute('SELECT company FROM holds')): return True
        # Conservative: any recorded reply protects that exact employer. Never
        # guess parent/subsidiary equivalence or infer a clean CRM from no data.
        return any(fold(r['company'])==key for r in db.execute(
            'SELECT DISTINCT leads.company FROM leads JOIN replies ON replies.lead_id=leads.id'))

    def reserve(self, url, run_id):
        key=profile_key(url)
        if key==(self.store.setting('account') or {}).get('key'):return 'own_profile'
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM leads WHERE profile_key=?',(key,)).fetchone(): return 'known_contact'
            inserted=db.execute('INSERT OR IGNORE INTO research_visits(profile_key,url,run_id,state,created) VALUES(?,?,?,\'reserved\',?)',
                                (key,url,run_id,now())).rowcount
            return '' if inserted else 'previously_visited_or_reserved'

    def stage(self, url, candidate, profile, company, run_id):
        # Quotations must actually occur in captured pages. Model confidence is
        # never sufficient; all proposals still require the human review step.
        p=fold(profile['text']);c=fold(company['text']);d=candidate
        headline=fold(profile.get('headline',''))
        headline_evidence=bool(headline and fold(d.current_role_quote)==headline and
            not re.search(r'\b(former|formerly|previous|past|ex|anterior)\b',headline))
        if (not d.qualified or not all(fold(v) for v in [d.name,d.company,d.role,d.country,d.current_role_quote,d.location_quote,d.sector_quote])
            or fold(d.name)!=fold(profile['title'])
            or not (headline_evidence or re.search(r'\b(present|actualidad|actualmente|current|currently|presente|atual|atualmente)\b',fold(d.current_role_quote)))
            or fold(d.current_role_quote) not in p
            or fold(d.role) not in fold(d.current_role_quote)
            or fold(d.company) not in fold(d.current_role_quote)
            or fold(d.company) not in fold(company['title'])
            or fold(d.location_quote) not in p
            or fold(d.sector_quote) not in c):
            return 'insufficient_evidence'
        evidence=json.dumps({'profile_url':url,'company_url':company['url'],
            'current_role_quote':d.current_role_quote,'role_source':'profile_headline' if headline_evidence else 'dated_experience','location_quote':d.location_quote,
            'sector_quote':d.sector_quote,'assessment':d.reason,'captured_at':now()},ensure_ascii=False)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.blocked(d.company,db): return 'company_replied_or_held'
            added=db.execute('INSERT OR IGNORE INTO leads(id,profile_key,name,company,role,url,country,evidence,created) VALUES(?,?,?,?,?,?,?,?,?)',
                (uuid.uuid4().hex,profile_key(url),d.name,d.company,d.role,url,d.country,evidence,now())).rowcount
        return 'staged_for_review' if added else 'duplicate'

    def run(self, plan_id, history_ack):
        plan=self.store.setting('research_plan')
        if not plan or plan['id']!=plan_id: raise ProviderError('Prepare a new research plan first.')
        if not history_ack: raise ProviderError('Confirm the local CRM contains your prior contacts/replies, or this is a new campaign.')
        start=time.monotonic();run_id=uuid.uuid4().hex
        report={'run_id':run_id,'target':plan['limit'],'visited':0,'staged':0,'skipped':0,'reason':'search_exhausted'}
        self.store.setting('research_report',report)
        self.store.setting('research_active',True)
        self.event(run_id,'started',{'plan':plan,'history_acknowledged':True})
        def guard():
            if self.stop.is_set(): raise ProviderError('Research stopped by you.')
            if time.monotonic()-start > plan['max_minutes']*60: raise ProviderError('Research time limit reached.')
        try:
            guard()
            self.event(run_id,'checking_browser',{'reason':'Opening LinkedIn with the signed-in browser session.'})
            self.browser.ensure_ready()
            company_cache={}
            for query in plan['queries']:
                guard()
                self.event(run_id,'searching',{'query':query,'reason':'Using a query from your reviewed plan.'})
                page,links=self.browser.search(query)
                self.event(run_id,'search',{'query':query,'url':page['url'],'observed_profiles':len(links)})
                if self.jev and self.jev.key():
                    from .jev import JevAdvisor
                    self.event(run_id,'ranking',{'reason':'Jev is prioritizing the observed profile links against your brief.'})
                    links=JevAdvisor(self.jev.key()).rank_profiles(links,plan['prompt'])
                    if links:self.event(run_id,'prioritized',{'url':links[0]['url'],'label':links[0]['label'],'reason':'First link after the Jev prioritization step, which may retain the original order; it is not yet qualified.'})
                for link in links:
                    guard()
                    if report['staged']>=plan['limit'] or report['visited']>=plan['max_profiles']: break
                    url=link['url'];skip=self.reserve(url,run_id)
                    if skip:
                        report['skipped']+=1;self.event(run_id,skip,{'url':url});continue
                    report['visited']+=1
                    self.event(run_id,'visiting',{'url':url,'label':link['label'],'reason':'Inspecting the next unvisited profile in the search order; qualification is still pending.'})
                    profile=self.browser.profile(url)
                    companies=profile['companies']
                    direct=[item for item in companies if fold(item['label']) and fold(item['label']) in fold(profile.get('headline',''))]
                    if not companies:
                        selected=Employer(company_url='',reason='No observed employer URL; skipped without a model call.')
                    elif len(direct)==1:
                        selected=Employer(company_url=direct[0]['url'],reason='Observed company link matches the profile headline; qualification still required.')
                    else:
                        self.event(run_id,'selecting_employer',{'url':url,'reason':'Codex is comparing observed company links with the current role in this profile.'})
                        selected=self.ask('Select the observed company URL for the CURRENT employer matching the brief. '
                            'Only use an exact URL from companies. Return empty company_url if current employment is unclear.',
                            {'brief':plan['prompt'],'profile':profile},Employer)
                    observed={x['url'] for x in profile['companies']}
                    outcome='current_employer_unclear';company={};candidate=None
                    if selected.company_url in observed:
                        guard()
                        self.event(run_id,'employer_selected',{'url':selected.company_url,'reason':selected.reason,'cached':selected.company_url in company_cache})
                        if selected.company_url not in company_cache:
                            company_cache[selected.company_url]=self.browser.company(selected.company_url)
                        company=company_cache[selected.company_url]
                        with self.store.db() as db: held=self.blocked(company['title'],db)
                        if held: outcome='company_replied_or_held'
                        else:
                            self.event(run_id,'qualifying',{'url':url,'reason':'Codex is checking your brief against profile and company evidence. Source quotations are checked before saving.'})
                            candidate=self.ask('Qualify this person against ALL brief criteria. Current role/employer must be explicit in their own profile. '
                                'The company page must establish sector. Location must be on the person profile. '
                                'Quote exact contiguous passages from supplied text. current_role_quote must include the exact role AND employer and current employment evidence. '
                                'An explicit role/employer in the supplied headline is acceptable self-reported current-role evidence; quote the entire headline exactly. Never treat former/ex roles as current. Use the profile heading as name. If evidence is missing or past-only, qualified=false. Do not infer from recommendations or posts.',
                                {'brief':plan['prompt'],'profile':profile,'company':company},Candidate)
                            guard()
                            outcome=self.stage(url,candidate,profile,company,run_id)
                    evidence={'profile':profile,'company':company,'assessment':candidate.model_dump() if candidate else None}
                    with self.store.db() as db:
                        db.execute('UPDATE research_visits SET state=?,evidence=? WHERE profile_key=?',
                                   (outcome,json.dumps(evidence,ensure_ascii=False),profile_key(url)))
                    if outcome=='staged_for_review': report['staged']+=1
                    else: report['skipped']+=1
                    explanation=candidate.reason if candidate else selected.reason
                    if outcome=='company_replied_or_held':explanation='This company has a recorded reply or hold in the local CRM.'
                    if outcome=='insufficient_evidence' and candidate and candidate.qualified:
                        explanation='The model proposed this person, but the required source quotation or identity checks did not pass. Not saved.'
                    self.event(run_id,outcome,{'url':url,'reason':explanation,'assessment':candidate.reason if candidate else '',
                        'role_quote':candidate.current_role_quote if candidate and outcome=='staged_for_review' else '',
                        'company_url':company.get('url','')})
                    self.store.setting('research_report',report)
                if report['staged']>=plan['limit']:
                    report['reason']='target_reached';break
                if report['visited']>=plan['max_profiles']:
                    report['reason']='visit_limit';break
        except ProviderError as exc:
            report['reason']=str(exc)
            self.event(run_id,'stopped',{'reason':str(exc)})
        except Exception:
            report['reason']='Research interrupted by an unexpected browser or model error. Inspect the last visited page; no automatic retry.'
            self.event(run_id,'stopped',{'reason':report['reason']})
        finally:
            report['seconds']=round(time.monotonic()-start,1)
            report['staged_per_visit']=round(report['staged']/report['visited'],3) if report['visited'] else 0
            self.store.setting('research_report',report)
            self.store.setting('research_active',False)
            self.event(run_id,'finished',report)
        return report
