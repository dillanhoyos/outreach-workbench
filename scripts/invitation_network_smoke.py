"""Isolated Selenium + local fake invitation server. Never uses a signed-in browser.

Start a disposable Selenium container, then set FIXTURE_SELENIUM_URL and
FIXTURE_HOST (the address of this machine as seen by that container).
Only the fixture transport adapter rewrites local receipt URLs to the expected
LinkedIn endpoint; there is no real LinkedIn request or invitation.
"""
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from selenium.webdriver.remote.command import Command
from workbench.linkedin import LinkedInBrowser
from workbench.store import Store
from workbench.invitation_receipt import INVITATION_PATH

mode='h2-more';posts=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        heading='h2' if mode=='h2-more' else 'h1'
        controls='''<button onclick="document.querySelector('#invite').hidden=false">More</button><a id="invite" hidden href="https://www.linkedin.com/preload/custom-invite/?vanityName=example-person" onclick="event.preventDefault();document.querySelector('[role=dialog]').hidden=false">Connect</a>''' if mode=='h2-more' else '''<button onclick="document.querySelector('[role=dialog]').hidden=false">Connect</button>'''
        html=f'''<!doctype html><main><section><div><{heading}>Example Person</{heading}><p>Founder at Example Company</p><button>Example Company</button></div>{controls}</section></main>
        <div role="dialog" hidden><button onclick="document.querySelector('textarea').hidden=false">Add a note</button><textarea hidden></textarea>
        <button onclick="window.sends=(window.sends||0)+1;fetch('{INVITATION_PATH}',{{method:'POST',body:document.querySelector('textarea').value}})">Send</button></div>'''
        if mode=='shadow-dialog':
            html+="""<div id="interop-outlet"></div><script>
            const shadow=document.querySelector('#interop-outlet').attachShadow({mode:'open'});
            shadow.append(document.querySelector('[role=dialog]'));
            document.querySelector('main section>button').onclick=()=>shadow.querySelector('[role=dialog]').hidden=false;
            const buttons=shadow.querySelectorAll('button');
            buttons[0].onclick=()=>shadow.querySelector('textarea').hidden=false;
            buttons[1].onclick=()=>{window.sends=(window.sends||0)+1;fetch('RECEIPT_PATH',{method:'POST',body:shadow.querySelector('textarea').value})};
            </script>""".replace('RECEIPT_PATH',INVITATION_PATH)
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(html.encode())
    def do_POST(self):
        assert self.path==INVITATION_PATH
        posts.append(self.rfile.read(int(self.headers['Content-Length'])).decode())
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"accepted":true}')

server=ThreadingHTTPServer(('0.0.0.0',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
root='http://'+os.environ['FIXTURE_HOST']+':'+str(server.server_port)
try:
    with tempfile.TemporaryDirectory() as directory:
        store=Store(Path(directory));settings=SimpleNamespace(selenium_url=os.environ['FIXTURE_SELENIUM_URL'])
        b=LinkedInBrowser(settings,store);driver=b.browser()
        class FixtureDriver:
            current_url='https://www.linkedin.com/in/example-person/'
            def __getattr__(self,name):return getattr(driver,name)
            def execute(self,command,params):
                result=driver.execute(command,params)
                if command==Command.GET_LOG:
                    for entry in result['value']:
                        parsed=json.loads(entry['message']);data=parsed.get('message',{}).get('params',{})
                        for key in ('request','response'):
                            item=data.get(key,{})
                            if item.get('url')==root+INVITATION_PATH:item['url']='https://www.linkedin.com'+INVITATION_PATH
                        entry['message']=json.dumps(parsed)
                return result
        b.driver=FixtureDriver();b.require_session=lambda:None;b.navigate=lambda url:driver.get(root)
        try:
            for mode in ('h2-more','h1-direct','shadow-dialog'):
                lead={'name':'Example Person','company':'Example Company','role':'Founder','country':'Example','url':FixtureDriver.current_url,'note':'Hello from a fictional fixture.'}
                wrong=b.send({**lead,'company':'Different employer'})
                assert wrong['status']=='blocked' and not posts
                result=b.send(lead)
                assert result['status']=='confirmed',result
                assert 'POST returned HTTP 200' in result['evidence']
                assert driver.execute_script('return window.sends')==1
                assert posts==[lead['note']]
                posts.clear()
                print('PASS:',mode,'recipient/company guard, exact note, single local POST 200, no Pending UI',flush=True)
        finally:driver.quit()
finally:server.shutdown();server.server_close()
