"""Isolated Google fixture E2E: real browser, app routes and SQLite; no Google calls.
Run .venv/bin/python scripts/sheets_ui_smoke.py. Google consent/Picker SDK are fixtures.
"""
import asyncio,json,os,socket,tempfile,threading,time
from pathlib import Path
from unittest.mock import patch
import uvicorn
from playwright.async_api import async_playwright
from workbench.app import create_app
from workbench.config import Settings
from workbench.google_connection import GoogleConnection
from workbench.sheets_import import SheetsImport
from workbench.store import Store

state={'connected':False,'granted':False}
def metadata(self,path,params=None):
    if not state['granted']:return None
    if '/values/' in path:
        return {'values':[['Name','LinkedIn','Company','Status'],['Ada Fixture','https://www.linkedin.com/in/ada-fixture/','Fixture Co','new'],['Bea Fixture','https://www.linkedin.com/in/bea-fixture/','Fixture Co','sent'],['Ada duplicate','https://www.linkedin.com/in/ada-fixture/','Other','replied'],['Invalid','not a URL','','new']]}
    return {'properties':{'title':'Fixture prospects'},'sheets':[{'properties':{'sheetId':0,'title':'Prospects','gridProperties':{'columnCount':4}}}]}
def finish(self,*args,**kwargs):state['connected']=True
async def main(base,directory):
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=str(next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))),args=['--no-sandbox'])
        page=await browser.new_page(viewport={'width':1400,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def consent(route):
            await route.fulfill(content_type='text/html',body='<a id="consent" href="'+base+'/api/connections/google/callback?state=fixture&code=fixture">Allow fixture consent</a>')
        await page.context.route('https://accounts.google.com/**',consent)
        picker_js="""
        window.gapi={load:(name,options)=>options.callback()};
        class View {setFileIds(id){if(typeof id!=='string')throw Error('Expected string file ID');return this;}}
        class Builder {
          addView(){return this;}setOAuthToken(t){if(t!=='fixture-access')throw Error('Wrong token');return this;}
          setDeveloperKey(){return this;}setAppId(){return this;}setOrigin(){return this;}
          setCallback(cb){this.cb=cb;return this;}
          build(){const cb=this.cb;return {dispose(){},setVisible(){const b=document.createElement('button');b.id='fixture-pick';b.textContent='Select fixture spreadsheet';b.onclick=async()=>{await fetch('/fixture/grant',{method:'POST'});b.remove();cb({action:'picked',docs:[{id:'fixture-sheet-id'}]});};document.body.append(b);}};}
        }
        window.google={picker:{DocsView:View,PickerBuilder:Builder,ViewId:{SPREADSHEETS:'sheets'},Action:{PICKED:'picked',CANCEL:'cancel'}}};
        """
        await page.route('https://apis.google.com/js/api.js',lambda route:route.fulfill(content_type='text/javascript',body=picker_js))
        await page.goto(base);await page.fill('#token','x'*32);await page.click('#connect')
        await page.click('nav a[href="#connections"]');await page.locator('#optional-sheets').evaluate('(e)=>e.open=true')
        async with page.expect_popup() as event:await page.click('#google-login')
        popup=await event.value;await popup.locator('#consent').click();await popup.close()
        await page.wait_for_function("document.querySelector('#google-message').textContent.includes('Google connected')")
        await page.fill('#google-import-url','https://docs.google.com/spreadsheets/d/fixture-sheet-id/edit')
        await page.click('#google-inspect');await page.wait_for_function("document.querySelector('#google-import-status').textContent.includes('Grant this app')")
        await page.click('#google-picker');await page.click('#fixture-pick')
        await page.locator('#google-tab-step').wait_for(state='visible');await page.click('#google-load-rows')
        await page.locator('#google-map-step').wait_for(state='visible')
        assert await page.locator('[data-field="url"]').input_value()=='1'
        await page.click('#google-preview');await page.locator('#google-preview-step').wait_for(state='visible')
        assert '2 new contacts' in await page.locator('#google-preview-summary').inner_text()
        assert await page.locator('#google-import-commit').is_disabled()
        await page.check('#google-import-confirm');await page.click('#google-import-commit')
        await page.wait_for_function("document.querySelector('#google-import-status').textContent.startsWith('Imported 2')")
        await page.click('nav a[href="#outreach"]');await page.wait_for_function("document.querySelector('#leads').textContent.includes('Ada Fixture')")
        import sqlite3
        with sqlite3.connect(Path(directory)/'demo'/'workbench.sqlite') as db:
            assert db.execute('SELECT COUNT(*) FROM leads').fetchone()[0]==2
            assert db.execute('SELECT COUNT(*) FROM crm_exclusions').fetchone()[0]==2
            assert db.execute("SELECT COUNT(*) FROM crm_assessments WHERE qualification='qualified'").fetchone()[0]==0
            assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==0
        await page.click('nav a[href="#connections"]');await page.screenshot(path='/tmp/workbench-sheets-import.png',full_page=True)
        await page.set_viewport_size({'width':390,'height':844})
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        await browser.close()
        print('PASS: fixture consent → URL access denied → Picker grant → tab → auto mapping → preview → confirmed local import → CRM; duplicate/history exclusions; mobile; no JS errors')

with tempfile.TemporaryDirectory(prefix='sheets-e2e-') as directory:
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base='http://127.0.0.1:'+str(port)
    with patch.object(GoogleConnection,'status',lambda self:{'configured':True,'connected':state['connected'],'message':''}),patch.object(GoogleConnection,'start',lambda self:{'authorization_url':'https://accounts.google.com/fixture'}),patch.object(GoogleConnection,'finish',finish),patch.object(GoogleConnection,'saved',lambda self:{'refresh_token':'fixture'} if state['connected'] else {}),patch.object(GoogleConnection,'picker_config',lambda self:{'access_token':'fixture-access','api_key':'fixture-key','app_id':'123'}),patch.object(SheetsImport,'get',metadata):
        app=create_app(Settings(Path(directory),'x'*32,'demo','',10,'',''))
        @app.post('/fixture/grant')
        def grant():state['granted']=True;return {}
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',access_log=False))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.05)
            asyncio.run(main(base,directory))
        finally:server.should_exit=True;thread.join(timeout=5)
