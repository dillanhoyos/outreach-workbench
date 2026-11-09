import httpx
import pytest
from workbench.discovery import ApolloDiscovery
from workbench.errors import ProviderError


def test_credit_consent_required_before_network():
    with pytest.raises(ProviderError,match='Explicitly'):
        ApolloDiscovery('test-key').discover('Finance',1)


def test_search_enrichment_and_filters():
    seen=[]
    def handle(req):
        import json
        body=json.loads(req.content);seen.append((req.url.path,body))
        assert req.headers['x-api-key']=='fixture-key'
        if 'api_search' in req.url.path:
            return httpx.Response(200,json={'people':[{'id':'fixture-1'},{'id':'fixture-2'}]})
        if body['id']=='fixture-2':return httpx.Response(200,json={'person':None})
        return httpx.Response(200,json={'person':{'id':'fixture-1','name':'Fictional Person','title':'CFO',
            'country':'Example','organization':{'name':'Example Co'},'linkedin_url':'https://www.linkedin.com/in/fixture-person'}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        r=ApolloDiscovery('fixture-key',client).discover('CFO, Controller',2,locations=['Example'],domains=['example.com'],allow_paid_enrichment=True)
    assert len(r['candidates'])==1 and r['skipped_incomplete']==1
    assert seen[0][1]['person_titles']==['CFO','Controller']
    assert seen[0][1]['person_locations']==['Example']
    assert all(not b.get('reveal_phone_number') for _,b in seen[1:])


def test_429_stops_without_retry_or_secret_output():
    calls=[]
    def handle(req):
        calls.append(req)
        return httpx.Response(429,json={'secret':'do-not-display'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError,match='rate limit') as e:
            ApolloDiscovery('fixture-key',client).discover('CFO',allow_paid_enrichment=True)
    assert len(calls)==1 and 'do-not-display' not in str(e.value)
