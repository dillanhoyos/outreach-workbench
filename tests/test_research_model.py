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
