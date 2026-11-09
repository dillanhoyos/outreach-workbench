"""Generate local secrets without collecting third-party passwords."""
from pathlib import Path
import secrets
import os

root=Path(__file__).resolve().parents[1]
p=root/'.env'
if p.exists():
    print('.env already exists. Kept your existing configuration.')
else:
    os.umask(0o077)
    p.write_text('WORKBENCH_MODE=demo\nWORKBENCH_TOKEN='+secrets.token_urlsafe(32)+'\nVNC_PASSWORD='+secrets.token_hex(4)+'\nDAILY_SEND_LIMIT=10\n')
    print('Created private .env. Start with: docker compose up --build -d')
    print('Open http://localhost:8080 and enter WORKBENCH_TOKEN from .env.')
(root/'secrets').mkdir(mode=0o700,exist_ok=True)
