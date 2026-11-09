"""Apollo discovery: explicit filters and explicit consent to credit usage."""
import httpx
from .errors import ProviderError, check_response
from .store import now, profile_key

class ApolloDiscovery:
    def __init__(self,key,client=None):
        self.key=key
        self.client=client

    def discover(self,query,limit=10,*,locations=None,domains=None,allow_paid_enrichment=False):
        if not self.key:raise ProviderError('Add APOLLO_API_KEY to .env and restart the app.')
        if not allow_paid_enrichment:
            raise ProviderError('Retrieving LinkedIn URLs requires Apollo enrichment. Explicitly allow provider credit usage for this search.')
        # This is title filtering, not an LLM interpreting free text.
        titles=[s.strip() for s in query.split(',') if s.strip()]
        payload={'person_titles':titles,'include_similar_titles':True,'per_page':limit,'page':1}
        if locations:payload['person_locations']=locations
        if domains:payload['q_organization_domains_list']=domains
        client=self.client or httpx.Client(timeout=30)
        owned=self.client is None
        try:
            headers={'X-Api-Key':self.key,'Content-Type':'application/json','Accept':'application/json'}
            data=check_response(client.post('https://api.apollo.io/api/v1/mixed_people/api_search',headers=headers,json=payload),'Apollo')
            people=data.get('people',[])
            if not isinstance(people,list):raise ProviderError('Apollo returned an unexpected search response.')
            candidates=[];skipped=0
            for match in people[:limit]:
                ident=match.get('id')
                if not ident:skipped+=1;continue
                data=check_response(client.post('https://api.apollo.io/api/v1/people/match',headers=headers,json={
                    'id':ident,'reveal_personal_emails':False,'reveal_phone_number':False}),'Apollo')
                p=data.get('person') or {}
                if p.get('id')!=ident or data.get('match_confidence') in ('none','low'):
                    skipped+=1;continue
                url=p.get('linkedin_url') or ''
                try:profile_key(url)
                except ValueError:skipped+=1;continue
                name=p.get('name');role=p.get('title');company=(p.get('organization') or {}).get('name')
                if not all(isinstance(x,str) and x.strip() for x in (name,role,company)):
                    skipped+=1;continue
                candidates.append({'name':name,'role':role,'company':company,'url':url,
                    'country':p.get('country') or 'Not provided',
                    'evidence':f'Apollo person {ident}; retrieved {now()}. Provider-reported employment; review before approval.'})
            return {'candidates':candidates,'searched':len(people),'skipped_incomplete':skipped}
        finally:
            if owned:client.close()
