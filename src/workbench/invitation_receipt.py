"""Observe browser-generated invitation traffic; never issue or replay requests."""
import json
from urllib.parse import urlsplit

INVITATION_PATH='/voyager/api/voyagerRelationshipsDashMemberRelationships'


class InvitationReceipt:
    def __init__(self,profile_url,started_at):
        self.profile_url=profile_url;self.started_at=started_at
        self.requests={};self.events=[];self.rate_limited=False;self.unavailable=False

    def feed(self,entries):
        for entry in entries:
            try:
                message=json.loads(entry['message'])['message'];params=message.get('params',{})
                kind=message.get('method');rid=params.get('requestId')
                if kind=='Network.requestWillBeSent':
                    self.requests.pop(rid,None)
                    req=params['request'];url=urlsplit(req.get('url',''))
                    # wallTime binds requests to this one click, not a delayed prior response.
                    if (url.scheme!='https' or url.netloc!='www.linkedin.com' or url.path!=INVITATION_PATH
                        or req.get('method')!='POST' or params.get('wallTime',0)<self.started_at or not rid):continue
                    if params.get('redirectResponse'):
                        self.requests.pop(rid,None);continue
                    self.requests[rid]={'request_id':rid,'host':url.hostname,'path':url.path,'method':'POST'}
                    self.events.append({**self.requests[rid],'event':'request'})
                elif kind=='Network.responseReceived':
                    res=params.get('response',{});url=urlsplit(res.get('url',''));host=url.hostname or ''
                    if res.get('status')==429 and (host=='linkedin.com' or host.endswith('.linkedin.com')):self.rate_limited=True
                    req=self.requests.get(rid)
                    if not req:continue
                    if url.scheme!='https' or url.hostname!=req['host'] or url.path!=req['path']:continue
                    self.events.append({**req,'event':'response','status':res.get('status'),
                        'cached':bool(res.get('fromServiceWorker') or res.get('fromDiskCache') or res.get('fromPrefetchCache'))})
                elif kind=='Network.loadingFailed' and rid in self.requests:
                    self.events.append({**self.requests[rid],'event':'failed','canceled':bool(params.get('canceled'))})
            except (ValueError,KeyError,TypeError,AttributeError):continue
        # Only sanitized endpoint metadata. No query strings, headers, bodies or notes.
        self.events=list({json.dumps(e,sort_keys=True):e for e in self.events}.values())[-100:]

    @property
    def accepted(self):
        return len(self.requests)==1 and any(e.get('request_id') in self.requests and e['event']=='response' and e.get('status')==200 and not e.get('cached') for e in self.events)

    @property
    def rejected(self):
        return any(e['event']=='response' and e.get('status',0)>=400 for e in self.events)

    def snapshot(self):
        return {'profile_url':self.profile_url,'recipient_binding':'verified profile and one UI send click',
            'started_at':self.started_at,'accepted':self.accepted,'rate_limited':self.rate_limited,
            'network_unavailable':self.unavailable,'events':self.events}


def invite_url_matches(url,profile):
    from urllib.parse import parse_qs
    from .store import profile_key
    try:
        u=urlsplit(url)
        values=parse_qs(u.query,keep_blank_values=True,errors='strict').get('vanityName',[])
        return u.scheme=='https' and u.netloc=='www.linkedin.com' and u.path=='/preload/custom-invite/' and len(values)==1 and values[0].casefold()==profile_key(profile)
    except (ValueError,UnicodeError):return False
