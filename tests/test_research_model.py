from workbench.research_model import reason
from workbench.errors import ProviderError
from types import SimpleNamespace
import pytest

class Auth:
    def __init__(self,tmp_path,status='completed'):
        self.directory=tmp_path/'codex';self.events=None;self.calls=[];self.end_status=status
    def status(self):return {'signed_in':True}
    def _rpc(self,method,params):
        self.calls.append((method,params))
        if method=='thread/start':return {'thread':{'id':'fixture-thread'}}
        if method=='turn/start':
            self.events.put({'method':'item/completed','params':{'threadId':'fixture-thread',
                'item':{'type':'agentMessage','text':'{"answer":"fixture"}'}}})
            self.events.put({'method':'turn/completed','params':{'threadId':'fixture-thread',
                'turn':{'id':'fixture-turn','status':self.end_status}}})
            return {'turn':{'id':'fixture-turn'}}
        return {}

def test_model_structured_output_and_restricted_tools(tmp_path):
    auth=Auth(tmp_path)
    assert reason(auth,'Task',{}, {'type':'object'})=={'answer':'fixture'}
    config=auth.calls[0][1]['config']
    assert config['features.shell_tool'] is False
    assert config['features.apps'] is False and config['web_search']=='disabled'
    assert config['permissions.workbench-research']['network']['enabled'] is False
    assert auth.events is None

def test_model_failed_turn_never_returns_partial_answer(tmp_path):
    with pytest.raises(ProviderError,match='did not complete'):
        reason(Auth(tmp_path,'failed'),'Task',{}, {'type':'object'})


def test_concurrent_turn_notifications_are_isolated(tmp_path):
    import threading,json
    from concurrent.futures import ThreadPoolExecutor
    from workbench.codex_auth import CodexAuth
    class Routed(CodexAuth):
        def __init__(self):
            super().__init__(tmp_path)
            self.barrier=threading.Barrier(2)
        def status(self):return {'signed_in':True}
        def _rpc(self,method,params=None):
            ident=str(threading.get_ident())
            if method=='thread/start':return {'thread':{'id':ident}}
            if method=='turn/start':
                self.barrier.wait(timeout=5)
                self.dispatch({'method':'item/completed','params':{'threadId':ident,'item':{'type':'agentMessage','text':json.dumps({'id':ident})}}})
                self.dispatch({'method':'turn/completed','params':{'threadId':ident,'turn':{'id':ident,'status':'completed'}}})
                return {'turn':{'id':ident}}
            return {}
    auth=Routed()
    def run():
        result=reason(auth,'Task',{}, {'type':'object'})
        assert result['id']==str(threading.get_ident())
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:run(),range(2)))
    assert not auth.subscribers
