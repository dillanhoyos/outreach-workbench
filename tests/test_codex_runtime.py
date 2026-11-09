"""Optional real-binary protocol smoke; model traffic stays on a local fixture."""
import json
import os
import tempfile
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from workbench.codex_auth import CodexAuth
from workbench.research_model import reason
from workbench.errors import ProviderError


@pytest.mark.skipif(not os.getenv('CODEX_TEST_BINARY'), reason='Set CODEX_TEST_BINARY to the pinned installed Codex binary')
@pytest.mark.parametrize('rate_limited', [False, True])
def test_real_codex_structured_turn_has_no_action_tools(rate_limited):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['content-length'])))
            requests.append(payload)
            if rate_limited:
                self.send_response(429)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"Fixture rate limit","type":"rate_limit_error","code":"rate_limit_exceeded"}}')
                return
            message = {'id':'msg_fixture','type':'message','role':'assistant','status':'completed',
                       'content':[{'type':'output_text','text':'{"answer":"fixture"}','annotations':[]}]}
            result = {'id':'resp_fixture','object':'response','created_at':1,'status':'completed',
                      'model':'fixture-model','output':[message],
                      'usage':{'input_tokens':10,'output_tokens':5,'total_tokens':15}}
            events = [{'type':'response.created','response':{**result,'status':'in_progress','output':[]}},
                      {'type':'response.output_item.done','output_index':0,'item':message},
                      {'type':'response.completed','response':result}]
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            for event in events:
                self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode())
                self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            base = f'http://127.0.0.1:{server.server_port}/v1'
            auth = CodexAuth(Path(directory), [os.environ['CODEX_TEST_BINARY'],'app-server',
                '-c','cli_auth_credentials_store="file"','-c','model_provider="fixture"','-c',
                f'model_providers.fixture={{name="Fixture",base_url="{base}",wire_api="responses",requires_openai_auth=true,request_max_retries=0,stream_max_retries=0}}',
                '--listen','stdio://'])
            try:
                auth._rpc('account/login/start', {'type':'apiKey','apiKey':'local-fixture-only'})
                rpc = auth._rpc

                def fixture_rpc(method, params):
                    if method == 'thread/start':
                        params['modelProvider']='fixture'
                        params['model']='fixture-model'
                        params['config']['features.enable_request_compression']=False
                    return rpc(method,params)

                auth._rpc = fixture_rpc
                schema = {'type':'object','properties':{'answer':{'type':'string'}},
                          'required':['answer'],'additionalProperties':False}
                if rate_limited:
                    with pytest.raises(ProviderError): reason(auth,'Return fixture JSON',{},schema,timeout=20)
                else:
                    assert reason(auth,'Return fixture JSON',{},schema,timeout=20)=={'answer':'fixture'}
                assert len(requests)==1
                assert all((t.get('name') or t.get('type'))=='request_user_input'
                           for request in requests for t in request.get('tools',[]))
            finally:
                auth.close()
    finally:
        server.shutdown()
        server.server_close()
