"""Run the full one-page UI flow against an isolated demo database.
Requires Playwright and Chromium; never connects to the live app or LinkedIn.
Run: .venv/bin/python scripts/workspace_ui_smoke.py
Optional: PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chromium
"""
import os,sys,socket,subprocess,tempfile,time,urllib.request
from pathlib import Path
import asyncio
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or next(iter(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome')),p.chromium.executable_path).__str__(),args=['--no-sandbox'])
  page=await b.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  await page.goto(base_url);await page.fill('#token','x'*32);await page.click('#connect')
  await page.wait_for_function("document.querySelector('#mode').textContent.includes('Demo') || document.querySelector('#discover').disabled===false")
  await page.locator('#research-brief').evaluate('(e)=>e.open=true');await page.fill('#discovery-prompt','Find fictional finance professionals');await page.click('#discover')
  await page.wait_for_function("document.querySelector('#leads').textContent.includes('Demo Person 1')")
  await page.click('nav a[href="#outreach"]');await page.locator('#leads tr').first.get_by_role('button',name='Compose message').click()
  await page.locator('#browser-frame').evaluate('(e)=>e.dataset.sessionMarker="preserved"')
  for mode in ['discovery','compose','connections','activity','outreach']:
   await page.click('nav a[href="#'+mode+'"]')
   assert await page.locator('#browser-section').is_visible()
   assert await page.locator('#browser-frame').get_attribute('data-session-marker')=='preserved'
  await page.click('#close-panel')
  await page.click('nav a[href="#compose"]')
  await page.fill('#compose-instructions','English, friendly, ask to exchange ideas about finance operations. No product claims.')
  await page.click('#compose-generate');await page.locator('#compose-suggestions button').first.wait_for()
  await page.locator('#compose-suggestions button').first.click()
  assert await page.locator('#compose-send').is_disabled()
  await page.fill('#compose-note','Hi Demo Person 1, would you like to exchange perspectives on finance operations?')
  await page.click('#compose-save');await page.wait_for_function("document.querySelector('#compose-status').textContent.includes('Draft saved')")
  await page.click('#compose-close');await page.click('nav a[href="#outreach"]');await page.locator('#leads tr').first.get_by_role('button',name='Compose message').click()
  assert 'finance operations' in await page.locator('#compose-note').input_value()
  await page.click('#compose-approve');await page.wait_for_function("document.querySelector('#compose-status').textContent.startsWith('Approved.')")
  await page.fill('#compose-note','Changed note');assert await page.locator('#compose-send').is_disabled()
  await page.fill('#compose-note','Hi Demo Person 1, would you like to exchange perspectives on finance operations?')
  await page.check('#compose-confirm');await page.click('#compose-send')
  await page.wait_for_function("document.querySelector('#outreach-watch-status').textContent.includes('simulated')")
  assert await page.locator('#composer').is_visible()
  assert await page.locator('#browser-section').is_visible()
  assert 'Demo Person 1' in await page.locator('#outreach-watch-person').inner_text()
  await page.click('nav a[href="#activity"]')
  await page.wait_for_function("document.querySelector('#history-feed').textContent.includes('simulated')")
  await page.click('#close-panel')
  await page.locator('#composer').wait_for()
  assert await page.locator('#compose-send').is_disabled()
  await page.reload()
  await page.fill('#token','x'*32);await page.click('#connect')
  await page.wait_for_function("document.querySelector('#compose-receipt').textContent.includes('simulated')")
  assert await page.locator('#browser-section').is_visible()
  await page.click('nav a[href="#outreach"]')
  await page.select_option('#crm-filter','available')
  assert 'Demo Person 1' not in await page.locator('#leads').inner_text()
  await page.click('#close-panel')
  await page.screenshot(path='/tmp/outreach-composer-desktop.png',full_page=True)
  await page.set_viewport_size({'width':390,'height':844});await page.screenshot(path='/tmp/outreach-composer-mobile.png',full_page=True)
  assert await page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
  assert await page.locator('nav a[href="#inbox"]').count()==0
  assert not errors,errors
  print('PASS: select → generate → edit → save/reopen → approve → exact-text check → simulated send → receipt; desktop/mobile; no JS errors')
  await b.close()

with tempfile.TemporaryDirectory(prefix="workbench-ui-") as directory:
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 base_url='http://127.0.0.1:'+str(port)
 code="from pathlib import Path;import uvicorn,sys;from workbench.app import create_app;from workbench.config import Settings;uvicorn.run(create_app(Settings(Path(sys.argv[1]),'x'*32,'demo','',10,'','')),host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')"
 server=subprocess.Popen([sys.executable,'-c',code,directory,str(port)],stdout=subprocess.DEVNULL)
 try:
  for _ in range(100):
   if server.poll() is not None:raise RuntimeError('Demo server exited')
   try:
    urllib.request.urlopen(base_url,timeout=1).close();break
   except OSError:time.sleep(.1)
  else:raise RuntimeError('Demo server did not start')
  asyncio.run(main())
 finally:
  server.terminate()
  try:server.wait(timeout=5)
  except subprocess.TimeoutExpired:server.kill();server.wait()

