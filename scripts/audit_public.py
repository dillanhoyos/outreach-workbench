"""Conservative public-release check of tracked files and reachable Git blobs.
This supplements (does not replace) a credential scanner and human review.
"""
import re
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git',*args],cwd=root)
patterns={
 'private key':rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
 'GitHub credential':rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})',
 'Google credential':rb'"private_key_id"\s*:\s*"[a-f0-9]{30,}"',
 'production destination':rb'docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]{35,}',
 'personal machine path':rb'/home/dilla/',
}
errors=[]
files=git('ls-files','-z').decode().split('\0')
for name in filter(None,files):
    if name=='.env' or name.startswith(('secrets/','data/','.venv/')) or name.endswith(('.sqlite','.log')):
        errors.append((name,'private runtime file tracked'))
    if name=='scripts/audit_public.py':continue
    data=(root/name).read_bytes()
    for label,pattern in patterns.items():
        if re.search(pattern,data):errors.append((name,label))
# Scan all reachable blobs, not merely current HEAD. Report identifiers, not values.
for line in git('rev-list','--objects','--all').decode().splitlines():
    oid,_,name=line.partition(' ')
    if name=='scripts/audit_public.py':continue
    if git('cat-file','-t',oid).strip()!=b'blob':continue
    data=git('cat-file','blob',oid)
    for label,pattern in patterns.items():
        if re.search(pattern,data):errors.append((oid[:12]+' '+name,label))
for name,label in errors:print('FAIL:',label,'in',name)
if errors:sys.exit(1)
print('PASS: tracked files and reachable history contain no matches for configured private-data patterns')
