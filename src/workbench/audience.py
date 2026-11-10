"""Versioned audience contract and literal-source checklist validation."""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Criterion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    requirement:str=Field(min_length=3,max_length=1000)
    scope:Literal['company','person']
    source:Literal['company','profile','either']

class Quotation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:Literal['company','profile']
    quote:str=Field(min_length=1,max_length=1800)

class Check(BaseModel):
    model_config=ConfigDict(extra='forbid')
    criterion_id:str
    status:Literal['pass','fail','missing']
    reason:str=Field(max_length=1000)
    evidence:list[Quotation]=Field(max_length=4)


def lock(brief,criteria):
    body={'version':1,'brief':brief,'criteria':[{'id':f'c{i+1}',**c} for i,c in enumerate(criteria)]}
    return {**body,'id':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()}


def valid(audience,brief):
    if not audience or audience.get('brief')!=brief:return False
    try:
        criteria=[Criterion.model_validate({k:v for k,v in c.items() if k!='id'}).model_dump() for c in audience['criteria']]
        return bool(criteria) and lock(brief,criteria)==audience
    except (ValueError,TypeError,KeyError):return False


def checklist(audience,checks,profile,company):
    from .research import fold
    rows=[];ids=[x.criterion_id for x in checks]
    exact=set(ids)=={c['id'] for c in audience['criteria']} and len(ids)==len(set(ids))
    for criterion in audience['criteria']:
        check=next((x for x in checks if x.criterion_id==criterion['id']),None)
        status=check.status if check and exact else 'missing'
        reason=check.reason if check and exact else 'Missing, duplicate or unexpected criterion result.'
        sources=[]
        if check:
            for ev in check.evidence:
                page=profile if ev.source=='profile' else company
                allowed=criterion['source'] in ('either',ev.source)
                observed=bool(fold(ev.quote)) and fold(ev.quote) in fold(page.get('text',''))
                if not allowed or not observed:
                    status='missing';reason='Quotation is absent from the required source.'
                else:sources.append({'source':ev.source,'url':page.get('url',''),'quote':ev.quote})
        if status=='pass' and not sources:
            status='missing';reason='A pass requires a quotation from an allowed source.'
        rows.append({**criterion,'status':status,'reason':reason,'evidence':sources,'audience_id':audience['id']})
    return rows
