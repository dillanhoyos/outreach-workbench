"""Install the pinned official native Codex binary, checking npm's package integrity."""
import base64
import hashlib
import json
import os
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = '0.167.0'
arch = {'x86_64': 'x64', 'aarch64': 'arm64'}.get(platform.machine())
if arch is None:
    raise SystemExit('Codex container supports Linux x86_64 and arm64.')
with urllib.request.urlopen(f'https://registry.npmjs.org/@openai/codex/{VERSION}-linux-{arch}', timeout=30) as response:
    dist = json.load(response)['dist']
algorithm, expected = dist['integrity'].split('-', 1)
if algorithm != 'sha512' or not dist['tarball'].startswith('https://registry.npmjs.org/'):
    raise SystemExit('Unexpected Codex package metadata.')
with tempfile.TemporaryFile() as archive:
    digest = hashlib.sha512()
    with urllib.request.urlopen(dist['tarball'], timeout=60) as response:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk); archive.write(chunk)
    if base64.b64encode(digest.digest()).decode() != expected:
        raise SystemExit('Codex package integrity check failed.')
    archive.seek(0)
    with tarfile.open(fileobj=archive, mode='r:gz') as package:
        target = Path(os.environ.get('WORKBENCH_CODEX_INSTALL', '/usr/local/bin/codex'))
        for name in ('codex','codex-code-mode-host'):
            binaries = [m for m in package.getmembers() if m.isfile() and m.name.endswith('/bin/'+name)]
            if len(binaries) != 1:
                raise SystemExit('Unexpected Codex package layout.')
            destination = target if name=='codex' else target.with_name(name)
            with package.extractfile(binaries[0]) as source, destination.open('wb') as out:
                while chunk := source.read(1024 * 1024): out.write(chunk)
            destination.chmod(0o755)
print(f'Installed official Codex {VERSION} ({arch}); package integrity verified.')
