"""Read-only browser service diagnostics. Never creates or resets a session."""
from urllib.parse import urlsplit
import httpx


def browser_status(settings, client=None):
    host = urlsplit(settings.selenium_url).hostname or 'browser'
    if ':' in host:
        host = '[' + host + ']'
    viewer = f'http://{host}:7900/vnc.html'
    def probe(c):
        result = {'driver_available': False, 'viewer_available': False,
                  'viewer_port': settings.browser_port, 'mode': settings.mode}
        try:
            response = c.get(settings.selenium_url.rstrip('/') + '/status', timeout=2)
            result['driver_available'] = response.status_code == 200 and isinstance(response.json().get('value'), dict)
        except (httpx.HTTPError, ValueError):
            pass
        try:
            response = c.get(viewer, timeout=2)
            result['viewer_available'] = response.status_code == 200
        except httpx.HTTPError:
            pass
        result['available'] = result['driver_available'] and result['viewer_available']
        result['message'] = ('Browser services are reachable. Open the viewer to connect.' if result['available'] else
            'Browser services are not reachable yet. Start the browser container, wait for it to finish, then check again.')
        return result
    if client is not None:
        return probe(client)
    with httpx.Client(trust_env=False) as c:
        return probe(c)
