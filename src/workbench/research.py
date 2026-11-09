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
    needs_web_evidence: bool
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
              detail TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS crm_research_profiles (
              profile_key TEXT PRIMARY KEY, record TEXT NOT NULL);''')
        # Backfill existing visits once; keep these CRM records across log resets.
        with store.db() as db:
            visits=[dict(r) for r in db.execute('SELECT v.* FROM research_visits v LEFT JOIN crm_research_profiles c USING(profile_key) WHERE c.profile_key IS NULL')]
            starts={r['run_id']:json.loads(r['detail']).get('plan',{}).get('prompt','') for r in db.execute("SELECT run_id,detail FROM research_events WHERE kind='started'")}
        for visit in visits:
            self.remember(visit['url'],visit['state'],json.loads(visit['evidence']),visit['run_id'],starts.get(visit['run_id'],''),visit['created'])

        from .crm import backfill
        with store.db() as db:backfill(db,research=True)

    def remember(self,url,state,evidence,run_id,brief,visited_at=None):
        profile=evidence.get('profile') or {};assessment=evidence.get('assessment') or {}
        status={'reserved':'visit_interrupted','current_employer_unclear':'missing_evidence',
            'company_replied_or_held':'company_excluded','staged_for_review':'review','duplicate':'review'}.get(state,
            'missing_evidence' if assessment.get('needs_web_evidence') else 'not_applicable')
        record={'id':'visited:'+profile_key(url),'profile_key':profile_key(url),'url':url,
            'name':profile.get('title') or 'Profile not captured',
            'company':assessment.get('company') or (evidence.get('company') or {}).get('title',''),
            'role':assessment.get('role',''),'country':assessment.get('country',''),'status':status,'note':'',
            'visit_state':state,'run_id':run_id,'visited_at':visited_at or now(),'created':visited_at or now(),
            'assessed_at':now(),'audience':brief,'reason':assessment.get('reason') or state.replace('_',' '),
            'evidence':json.dumps(evidence,ensure_ascii=False),'visited':bool(profile)}
        with self.store.db() as db:
            old=db.execute('SELECT record FROM crm_research_profiles WHERE profile_key=?',(record['profile_key'],)).fetchone()
            history=json.loads(old['record']).get('research_history',[]) if old else []
            entry={k:record[k] for k in ('run_id','audience','status','reason','visited_at')}
            history=[x for x in history if x['run_id']!=run_id]+[entry]
            record['research_history']=history
            previous=json.loads(old['record']) if old else {}
            if previous.get('status')!=record['status'] or previous.get('reason')!=record['reason']:
                db.execute('INSERT INTO workspace_changes(lead_id,name,kind,before_state,after_state,detail,created) VALUES(?,?,?,?,?,?,?)',
                    (record['id'],record['name'],'research_assessment',previous.get('status'),record['status'],record['reason'],now()))

            db.execute('INSERT INTO crm_research_profiles VALUES(?,?) ON CONFLICT(profile_key) DO UPDATE SET record=excluded.record',
                       (record['profile_key'],json.dumps(record,ensure_ascii=False)))
            from .crm import assessment
            assessment(db,record)
            from .crm import sync_lead
            lead=db.execute("SELECT id FROM leads WHERE profile_key=?",(record["profile_key"],)).fetchone()
            if lead:sync_lead(db,lead["id"])

    def crm_records(self):
        leads=self.store.list('leads')
        with self.store.db() as db:
            visited={r['profile_key']:json.loads(r['record']) for r in db.execute('SELECT * FROM crm_research_profiles')}
        result=[]
        for lead in leads:
            extra=visited.pop(lead['profile_key'],{})
            result.append({**extra,**lead})
        from .crm import enrich
        with self.store.db() as db:return enrich(db,result+list(visited.values()))

    def previous_visit(self,db,key):
        row=db.execute('SELECT * FROM research_visits WHERE profile_key=?',(key,)).fetchone()
        if row:return dict(row)
        archived=db.execute('SELECT record FROM crm_research_profiles WHERE profile_key=?',(key,)).fetchone()
        if not archived:return None
        record=json.loads(archived['record'])
        return {'state':record['visit_state'],'run_id':record['run_id'],'evidence':record['evidence']}

    def event(self, run_id, kind, detail):
        with self.store.db() as db:
            db.execute('INSERT INTO research_events(run_id,kind,detail,created) VALUES(?,?,?,?)',
                       (run_id,kind,json.dumps(detail,ensure_ascii=False),now()))
            from .crm import record_event
            record_event(db,run_id,kind,detail,now())

    def state(self):
        with self.store.db() as db:
            events=[dict(r) for r in db.execute('SELECT * FROM research_events ORDER BY id DESC LIMIT 80')]
        return {'plan':self.store.setting('research_plan'),'report':self.store.setting('research_report'),
                'events':events,'active':bool(self.store.setting('research_active')),
                'conversation':self.store.setting('research_conversation') or {'messages':[],'brief':'','revision':''}}

    def ask(self, task, data, cls):
        try: return cls.model_validate(self.model(self.auth,task,data,cls.model_json_schema(),getattr(self,"_run_stop",self.stop)))
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

    def clear_history(self):
        """Explicit reset of read-only discovery history, never CRM/action state."""
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute("SELECT value FROM settings WHERE key='research_active'").fetchone()
            if active and json.loads(active['value']):
                raise ProviderError('Stop research and wait for it to finish before clearing search history.')
            visits=db.execute('DELETE FROM research_visits').rowcount
            events=db.execute('DELETE FROM research_events').rowcount
            db.execute("DELETE FROM jobs WHERE kind='discovery'")
            db.execute("DELETE FROM settings WHERE key='research_report'")
        return {'visits_cleared':visits,'events_cleared':events,
                'message':f'Search logs cleared ({visits} run visit records). CRM profiles and visit tags, contacts, replies, outreach records, connections and your brief are preserved. Use Recheck to deliberately revisit unqualified profiles.'}

    def reset_brief(self):
        self.store.setting('research_conversation',{'messages':[],'brief':'','revision':uuid.uuid4().hex})
        self.store.setting('research_plan',False)
        return {'message':'New research brief started. CRM records are unchanged.'}

    def prepare(self, prompt, limit, web_first=True, recheck_failed=False, profile_url="", max_minutes=15, max_profiles=0):
        if type(max_profiles) is not int or not 0 <= max_profiles <= 500: raise ProviderError('Choose a visit limit from 1 to 500, or 0 for time only.')
        if type(max_minutes) is not int or not 1 <= max_minutes <= 60: raise ProviderError('Choose a research time limit from 1 to 60 minutes.')
        if not 1 <= limit <= 10: raise ProviderError('Start with 1–10 candidates per research run.')
        if profile_url:
            from .research_browser import research_url
            profile_url=research_url(profile_url,'profile')
        web_first=True
        plan=self.ask('Plan up to six concise web searches for primary company sources, then LinkedIn confirmation. '+
                      'Include the sector, role families and geography. Explain the qualification criteria. '
                      'Queries are keywords, not URLs. Do not narrow accounting/risk roles to CFOs unless asked.',
                      {'brief':prompt},Plan)
        if any(not q.strip() or len(q)>250 or '://' in q for q in plan.queries):
            raise ProviderError('Research plan contained an invalid search query.')
        result={'id':uuid.uuid4().hex,'prompt':prompt,'limit':limit,**plan.model_dump(),
                'max_profiles':max_profiles,'max_minutes':max_minutes,'created':now(),'web_first':web_first,'recheck_failed':recheck_failed,'profile_url':profile_url}
        self.store.setting('research_plan',result)
        return result

    def blocked(self, company, db):
        from .crm import excluded
        companies=db.execute('SELECT id,name FROM crm_companies').fetchall()
        if any(fold(c['name'])==fold(company) and excluded(db,company_id=c['id']) for c in companies):return True
        key=fold(company)
        if any(fold(r['company'])==key for r in db.execute('SELECT company FROM holds')): return True
        # Conservative: any recorded reply protects that exact employer. Never
        # guess parent/subsidiary equivalence or infer a clean CRM from no data.
        return any(fold(r['company'])==key for r in db.execute(
            'SELECT DISTINCT leads.company FROM leads JOIN replies ON replies.lead_id=leads.id'))

    def reserve(self, url, run_id, recheck_failed=False):
        key=profile_key(url)
        if key==(self.store.setting('account') or {}).get('key'):return 'own_profile'
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM leads WHERE profile_key=?',(key,)).fetchone(): return 'known_contact'
            previous=self.previous_visit(db,key)
            if recheck_failed and previous and previous['run_id']!=run_id and previous['state'] in ('insufficient_evidence','current_employer_unclear'):
                # Keep the earlier evidence in the event history before replacing the reservation.
                db.execute('INSERT INTO research_events(run_id,kind,detail,created) VALUES(?,?,?,?)',
                    (run_id,'rechecking',json.dumps({'url':url,'previous_run':previous['run_id'],'previous_state':previous['state'],'previous_evidence':json.loads(previous['evidence']),'reason':'Rechecking a prior evidence failure with fresh sources.'}),now()))
                db.execute("INSERT INTO research_visits(profile_key,url,run_id,state,evidence,created) VALUES(?,?,?,'reserved',?,?) ON CONFLICT(profile_key) DO UPDATE SET run_id=excluded.run_id,state='reserved'",(key,url,run_id,previous['evidence'],now()))
                return ''
            if previous:return 'previously_visited_or_reserved'
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
        if (not d.qualified or not all(fold(v) for v in [d.name,d.company,d.role,d.current_role_quote,d.sector_quote])
            or fold(d.name)!=fold(profile['title'])
            or not (headline_evidence or re.search(r'\b(present|actualidad|actualmente|current|currently|presente|atual|atualmente)\b',fold(d.current_role_quote)))
            or fold(d.current_role_quote) not in p
            or fold(d.role) not in fold(d.current_role_quote)
            or fold(d.company) not in fold(d.current_role_quote)
            or fold(d.company) not in fold(company['title'])
            or (not company.get('company_criteria_quotes') and not all([d.country,d.location_quote]))
            or (bool(d.country)!=bool(d.location_quote))
            or fold(d.location_quote) not in p
            or fold(d.sector_quote) not in c):
            return 'insufficient_evidence'
        evidence=json.dumps({'profile_url':url,'company_url':company['url'],
            'current_role_quote':d.current_role_quote,'role_source':'profile_headline' if headline_evidence else 'dated_experience','location_quote':d.location_quote,
            'sector_quote':d.sector_quote,'company_criteria_quotes':company.get('company_criteria_quotes',[]),'company_assessment':company.get('company_assessment',''),'assessment':d.reason,'captured_at':now()},ensure_ascii=False)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            from .crm import excluded
            known=db.execute('SELECT id FROM crm_people WHERE profile_key=?',(profile_key(url),)).fetchone()
            if self.blocked(d.company,db) or (known and excluded(db,person_id=known['id'])): return 'company_replied_or_held'
            added=db.execute('INSERT OR IGNORE INTO leads(id,profile_key,name,company,role,url,country,evidence,created) VALUES(?,?,?,?,?,?,?,?,?)',
                (uuid.uuid4().hex,profile_key(url),d.name,d.company,d.role,url,d.country,evidence,now())).rowcount
            if added:
                from .crm import sync_lead
                lead=db.execute('SELECT id FROM leads WHERE profile_key=?',(profile_key(url),)).fetchone()
                sync_lead(db,lead['id'])
        return 'staged_for_review' if added else 'duplicate'

    def qualify(self,plan,profile,company):
        return self.ask('Qualify this person against ALL brief criteria. Current role/employer must be explicit in their own profile. '
            'Set needs_web_evidence=true only when required COMPANY facts such as batch or sector are missing, not when they contradict the brief or the current role is wrong. '
            'The company page must establish sector and any batch requirement. In web-first mode it is a captured primary web source. '
            'Location must be on the person profile when required by the brief. In web-first mode only, if geography is unrestricted, country and location_quote may both be empty. '
            'Quote exact contiguous passages from supplied text. current_role_quote must include the exact role AND employer and current employment evidence. '
            'An explicit role/employer in the supplied headline is acceptable self-reported current-role evidence; quote the entire headline exactly. Never treat former/ex roles as current. Use the profile heading as name. If evidence is missing or past-only, qualified=false. Do not infer from recommendations or posts.',
            {'brief':plan['prompt'],'profile':profile,'company':company},Candidate)

    def fresh_links(self, links, plan, run_id):
        """Filter without reserving: an unseen candidate is reserved only on visit."""
        fresh=[];seen=set()
        own=(self.store.setting('account') or {}).get('key')
        with self.store.db() as db:
            for link in links:
                key=profile_key(link['url'])
                if key in seen or key==own:continue
                seen.add(key)
                if db.execute('SELECT 1 FROM leads WHERE profile_key=?',(key,)).fetchone():continue
                previous=self.previous_visit(db,key)
                if previous and not (plan.get('recheck_failed') and previous['run_id']!=run_id and previous['state'] in ('insufficient_evidence','current_employer_unclear')):continue
                fresh.append(link)
        removed=len(links)-len(fresh)
        if removed:self.event(run_id,'filtered_seen',{'reason':f'Excluded {removed} known, previously visited or duplicate profiles before ranking. {len(fresh)} candidates remain.'})
        return fresh

    def reassess_cached(self,plan,run_id,report,guard):
        """Reuse recent captured evidence for a new audience, without a LinkedIn visit."""
        from datetime import datetime, timezone, timedelta
        from .crm import ident
        campaign_id=ident('campaign',plan['prompt'].strip())
        with self.store.db() as db:
            records=[json.loads(r[0]) for r in db.execute('SELECT record FROM crm_research_profiles')]
        for old in records:
            guard()
            if report['staged']>=plan['limit']:return
            if not old.get('audience') or old['audience']==plan['prompt'] or not old.get('visited'):continue
            with self.store.db() as db:
                if db.execute('SELECT 1 FROM leads WHERE profile_key=?',(old['profile_key'],)).fetchone():continue
                if db.execute('SELECT 1 FROM crm_assessments a JOIN crm_people p ON p.id=a.person_id WHERE p.profile_key=? AND a.campaign_id=?',(old['profile_key'],campaign_id)).fetchone():continue
            try:recent=datetime.fromisoformat(old['visited_at'])>datetime.now(timezone.utc)-timedelta(days=30)
            except (ValueError,TypeError):recent=False
            ev=json.loads(old['evidence']);profile=ev.get('profile');company=ev.get('company')
            if not recent or not profile or not company:continue
            self.event(run_id,'reassessing_cached',{'url':old['url'],'reason':'Checking recent saved evidence against this new audience; no repeat LinkedIn visit.'})
            candidate=self.qualify(plan,profile,company);guard()
            outcome=self.stage(old['url'],candidate,profile,company,run_id)
            self.remember(old['url'],outcome,{**ev,'assessment':candidate.model_dump()},run_id,plan['prompt'],old['visited_at'])
            report['cached_assessments']=report.get('cached_assessments',0)+1
            if outcome=='staged_for_review':report['staged']+=1
            else:report['skipped']+=1
            self.event(run_id,outcome,{'url':old['url'],'reason':candidate.reason,'cached':True})

    def batches(self, plan, run_id, report, guard, seeds):
        """Continue discovery after duplicates/failed qualification, never after limits."""
        from .research_web import discover
        def remaining():
            guard()
            return report['staged']<plan['limit'] and (not plan['max_profiles'] or report['visited']<plan['max_profiles'])
        if seeds is not None:
            for seed in seeds:
                guard()
                targeted={**plan,'limit':1,'prompt':plan['prompt']+' Research ONLY the current company of '+seed['url']+'; return this exact profile URL.'}
                matches=discover(self,targeted,run_id,guard)
                # A missing web result still permits explicit rechecks, after web search.
                matched=[x for x in matches if profile_key(x['url'])==profile_key(seed['url'])]
                yield matched or [seed]
            # A deliberately targeted run must never expand to unrelated people.
            if plan.get('profile_url'):return
        round_number=0
        tried_queries=list(plan["queries"])
        while remaining():
            round_number+=1
            if not remaining():return
            self.event(run_id,'expanding_web',{'reason':f'{report["staged"]}/{plan["limit"]} saved. Two web workers are finding primary company evidence.'})
            with self.store.db() as db:
                recent=[json.loads(r['detail']) for r in db.execute("SELECT detail FROM research_events WHERE run_id=? AND kind IN ('web_source','web_excluded','insufficient_evidence') ORDER BY id DESC LIMIT 30",(run_id,))]
            web_plan={**plan,'limit':plan['limit']-report['staged'],'exclude_visited':True,
                'round':round_number,'previous_results':recent}
            if round_number>1:
                revised=self.ask('Prepare NEW web search queries for the same audience. Earlier results are exhausted. Try other companies and terminology without relaxing any requirement.',
                    {'brief':plan['prompt'],'previous_queries':tried_queries[-60:],'recent_results':recent},Plan)
                web_plan['queries']=revised.queries
                tried_queries.extend(revised.queries)
            for links in self._web_pool.batches(web_plan):
                yield self.fresh_links(links,plan,run_id)
                if not remaining():return


    def run(self, plan_id, history_ack):
        plan=self.store.setting('research_plan')
        if not plan or plan['id']!=plan_id: raise ProviderError('Prepare a new research plan first.')
        if not history_ack: raise ProviderError('Confirm the local CRM contains your prior contacts/replies, or this is a new campaign.')
        plan={**plan,'web_first':True}
        self._web_failure=None
        start=time.monotonic();run_id=uuid.uuid4().hex
        report={'run_id':run_id,'target':plan['limit'],'visited':0,'staged':0,'skipped':0,'reason':'search_exhausted'}
        self.store.setting('research_report',report)
        self.store.setting('research_active',True)
        self.event(run_id,'started',{'plan':plan,'history_acknowledged':True})
        deadline=threading.Event()
        from .research_pool import CombinedStop
        self._run_stop=CombinedStop(self.stop,deadline)
        timer=threading.Timer(plan['max_minutes']*60,deadline.set)
        timer.daemon=True
        timer.start()
        def guard():
            if deadline.is_set(): raise ProviderError('Research time limit reached.')
            if self._web_failure: raise self._web_failure
            if self.stop.is_set(): raise ProviderError('Research stopped by you.')
            if time.monotonic()-start > plan['max_minutes']*60: raise ProviderError('Research time limit reached.')
        from .research_pool import WebPool
        self._web_pool=WebPool(self,plan,run_id,guard)
        try:
            guard()
            self.event(run_id,'checking_browser',{'reason':'Opening LinkedIn with the signed-in browser session.'})
            if not plan.get('profile_url') and not plan.get('recheck_failed'):
                self.reassess_cached(plan,run_id,report,guard)
            if report['staged']>=plan['limit']:
                report['reason']='target_reached'
                return report
            self.browser.ensure_ready()
            company_cache={}
            web_links=None
            fallback_count=0
            if plan.get('profile_url'):
                web_links=[{'url':plan['profile_url'],'label':'Requested profile'}]
            elif plan.get('recheck_failed'):
                with self.store.db() as db:
                    rows=[json.loads(r['record']) for r in db.execute('SELECT record FROM crm_research_profiles')]
                    web_links=[{'url':r['url'],'label':'Prior evidence failure'} for r in sorted(rows,key=lambda r:r['visited_at'],reverse=True)
                        if r['visit_state'] in ('insufficient_evidence','current_employer_unclear')][:plan['max_profiles'] or None]
                if not web_links:web_links=None
            for links in self.batches(plan,run_id,report,guard,web_links):
                guard()
                for link in links:
                    guard()
                    if report['staged']>=plan['limit'] or (plan['max_profiles'] and report['visited']>=plan['max_profiles']): break
                    url=link['url'];skip=self.reserve(url,run_id,plan.get('recheck_failed',False))
                    if skip:
                        report['skipped']+=1;self.event(run_id,skip,{'url':url});continue
                    report['visited']+=1
                    self.event(run_id,'visiting',{'url':url,'label':link['label'],'reason':'Inspecting the next unvisited profile in the search order; qualification is still pending.'})
                    self.remember(url,'reserved',{},run_id,plan['prompt'])
                    profile=self.browser.profile(url)
                    self.remember(url,'reserved',{'profile':profile},run_id,plan['prompt'])
                    companies=profile['companies']
                    direct=[item for item in companies if fold(item['label']) and fold(item['label']) in fold(profile.get('headline',''))]
                    if link.get('web_company'):
                        company_cache[link['web_company']['url']]=link['web_company']
                        selected=Employer(company_url=link['web_company']['url'],reason='Company criteria checked against captured primary web evidence; confirming current role on LinkedIn.')
                    elif not companies:
                        selected=Employer(company_url='',reason='No observed employer URL; skipped without a model call.')
                    elif len(direct)==1:
                        selected=Employer(company_url=direct[0]['url'],reason='Observed company link matches the profile headline; qualification still required.')
                    else:
                        self.event(run_id,'selecting_employer',{'url':url,'reason':'Codex is comparing observed company links with the current role in this profile.'})
                        selected=self.ask('Select the observed company URL for the CURRENT employer matching the brief. '
                            'Only use an exact URL from companies. Return empty company_url if current employment is unclear.',
                            {'brief':plan['prompt'],'profile':profile},Employer)
                    observed={x['url'] for x in profile['companies']}
                    if link.get('web_company'):observed.add(link['web_company']['url'])
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
                            candidate=self.qualify(plan,profile,company)
                            guard()
                            outcome=self.stage(url,candidate,profile,company,run_id)
                    linkedin_company=company if not link.get('web_company') else {}
                    # Missing evidence is not a confirmed mismatch. Try primary web
                    # sources, but keep role confirmation on the captured LinkedIn profile.
                    if (outcome=='current_employer_unclear' or (outcome=='insufficient_evidence' and candidate and candidate.needs_web_evidence)) and not link.get('web_company') and fallback_count<2:
                        guard();fallback_count+=1
                        self.event(run_id,'web_fallback',{'url':url,'reason':'Checking primary web sources before rejecting incomplete LinkedIn evidence.'})
                        from .research_web import discover
                        fallback_plan={**plan,'limit':1,'prompt':plan['prompt']+'\nResearch ONLY this person and their current company: '+profile['title']+' '+url+' Headline: '+profile.get('headline','')+'. Return this exact profile_url. Do not substitute another person.', 'queries':[profile['title']+' '+profile.get('headline','')]}
                        matches=discover(self,fallback_plan,run_id,guard)
                        for match in matches:
                            if profile_key(match['url'])!=profile_key(url):continue
                            company=match['web_company']
                            candidate=self.qualify(plan,profile,company)
                            guard();outcome=self.stage(url,candidate,profile,company,run_id)
                            break
                    evidence={'profile':profile,'linkedin_company':linkedin_company,'company':company,'assessment':candidate.model_dump() if candidate else None}
                    with self.store.db() as db:
                        db.execute('UPDATE research_visits SET state=?,evidence=? WHERE profile_key=?',
                                   (outcome,json.dumps(evidence,ensure_ascii=False),profile_key(url)))
                    self.remember(url,outcome,evidence,run_id,plan['prompt'])
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
                if (plan['max_profiles'] and report['visited']>=plan['max_profiles']):
                    report['reason']='visit_limit';break
        except ProviderError as exc:
            report['reason']='Research time limit reached.' if deadline.is_set() else str(self._web_failure or exc)
            self.event(run_id,'stopped',{'reason':report['reason']})
        except Exception:
            report['reason']='Research interrupted by an unexpected browser or model error. Inspect the last visited page; no automatic retry.'
            self.event(run_id,'stopped',{'reason':report['reason']})
        finally:
            self._web_pool.close()
            timer.cancel()
            del self._run_stop
            with self.store.db() as db:
                search_count=db.execute("SELECT COUNT(*) FROM research_events WHERE run_id=? AND kind='web_search' AND json_type(detail,'$.query') IS NOT NULL",(run_id,)).fetchone()[0]
                counts={r['kind']:r['n'] for r in db.execute('SELECT kind,COUNT(*) AS n FROM research_events WHERE run_id=? GROUP BY kind',(run_id,))}
            report['linkedin_searches']=counts.get('search',0)
            report['query_revisions']=counts.get('adapting_search',0)
            report['web_expansions']=counts.get('expanding_web',0)
            report['web_fallbacks']=counts.get('web_fallback',0)
            report['rechecked']=counts.get('rechecking',0)
            report['web_first']=bool(plan.get('web_first'))
            report['web_searches']=search_count
            report['web_sources']=counts.get('web_source',0)
            report['web_excluded']=counts.get('web_excluded',0)
            report['seconds']=round(time.monotonic()-start,1)
            report['staged_per_visit']=round(report['staged']/report['visited'],3) if report['visited'] else 0
            self.store.setting('research_report',report)
            self.store.setting('research_active',False)
            self.event(run_id,'finished',report)
        return report
