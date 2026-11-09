"""UI + real noVNC checks for a disposable live-mode test workspace.
Install Playwright separately: pip install playwright && playwright install chromium.
Never run against a browser containing a real account: --login-page navigates it.
No LinkedIn credentials are entered and no invitations are sent.
"""
import argparse
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--login-page', action='store_true', help='Also open the real LinkedIn login page in the disposable browser.')
parser.add_argument('--screenshot', help='Optional screenshot path after testing; keep screenshots private.')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
values = {}
if (root / '.env').exists():
    for line in (root / '.env').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
token = os.environ.get('WORKBENCH_TOKEN', values.get('WORKBENCH_TOKEN', ''))
password = os.environ.get('VNC_PASSWORD', values.get('VNC_PASSWORD', ''))
url = os.environ.get('WORKBENCH_URL', 'http://localhost:18081')
assert token and password, 'Supply local app and viewer credentials privately.'
with sync_playwright() as p:
    executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
    browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
    page = browser.new_page(viewport={'width': 1600, 'height': 1200})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    expect(page.locator('#login')).to_be_disabled()
    page.locator('#token').fill('wrong-password')
    page.locator('#connect').click()
    expect(page.locator('#error')).to_contain_text('token')
    # Simulate the reported offline state before connecting the real viewer.
    page.route('**/api/browser/status', lambda route: route.fulfill(json={
        'available': False, 'viewer_available': False, 'driver_available': False,
        'viewer_port': 17900, 'mode': 'live', 'message': 'Browser services are not reachable yet. Start the browser container.'}))
    page.locator('#token').fill(token)
    page.locator('#connect').click()
    expect(page.locator('#browser-badge')).to_have_text('Browser offline')
    expect(page.locator('#browser-help')).to_have_attribute('open', '')
    expect(page.locator('#login')).to_be_disabled()
    expect(page.locator('#browser-frame')).not_to_have_attribute('src', 'http://localhost:7900')
    page.unroute('**/api/browser/status')
    page.locator('#check-browser').click()
    expect(page.locator('#browser-badge')).to_have_text('Services reachable', timeout=15000)
    page.locator('#open-browser').click()
    expect(page.locator('#browser-frame')).to_be_visible()
    viewer = page.frame_locator('#browser-frame')
    password_input = viewer.locator('#noVNC_password_input')
    expect(password_input).to_be_visible(timeout=20000)
    password_input.fill(password)
    viewer.locator('#noVNC_credentials_button').click()
    expect(viewer.locator('html')).to_have_class(__import__('re').compile(r'.*noVNC_connected.*'), timeout=20000)
    assert token not in page.locator('#browser-frame').get_attribute('src')
    assert password not in page.locator('#browser-frame').get_attribute('src')
    page.locator('#expand-browser').click()
    page.wait_for_function("document.fullscreenElement?.id === 'browser-stage'")
    page.evaluate('document.exitFullscreen()')
    if args.login_page:
        page.locator('#login').click()
        expect(page.locator('#login-progress')).not_to_have_text('', timeout=15000)
        page.wait_for_function("!document.getElementById('login-progress').textContent.includes('Opening LinkedIn')", timeout=90000)
        if 'Saved browser session is unavailable' in page.locator('#login-progress').inner_text():
            # A container rebuild invalidates the driver connection, not saved cookies.
            page.locator('#browser-help').evaluate('(element) => element.open = true')
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('#reset-browser').click()
            expect(page.locator('#login-progress')).to_contain_text('Connection reset', timeout=15000)
            page.locator('#login').click()
        expect(page.locator('#login-progress')).to_contain_text('LinkedIn is open below', timeout=90000)
    if args.screenshot:
        page.locator('#browser-help').evaluate('(element) => element.open = false')
        page.screenshot(path=args.screenshot, full_page=True)
    if args.login_page:
        page.locator('#profile').fill('https://www.linkedin.com/in/workbench-fictional-test')
        page.locator('#verify').click()
        expect(page.locator('#error')).to_be_visible(timeout=90000)
        expect(page.locator('#account-name')).to_have_text('No account verified')
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors, errors
    browser.close()
print('PASS: app authentication, offline guidance, custom-port embedded viewer, VNC authentication, and mobile layout' + ('; login-page job completed' if args.login_page else ''))
