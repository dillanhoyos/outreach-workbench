"""Fictional records only; never communicates with LinkedIn."""
import hashlib
from .store import now

class DemoProvider:
    def discover(self, query, limit=10):
        return [dict(name=f'Demo Person {i+1}',company=f'Example Infrastructure {i//3+1}',
                     role='Finance Manager',country='Example Country',
                     url=f'https://www.linkedin.com/in/workbench-fictional-{i+1}',
                     evidence='Fictional demonstration record, not a verified real person')
                for i in range(min(limit,10))]

    def send(self,lead):
        return {'status':'simulated','evidence':'Demo only. No invitation was sent.'}

    def read(self,leads,limit=100):
        eligible=[x for x in leads if x['status']=='simulated'][:limit]
        return [dict(ident=hashlib.sha256(('demo-reply:'+x['id']).encode()).hexdigest(),
                     lead_id=x['id'],body='Fictional reply: Please share more information.',
                     received=now(),thread='demo:'+x['id']) for x in eligible]
