"""Generate deployment-local secrets, without printing them or putting them in images."""
import os
import secrets
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'.env'
if path.exists(): raise SystemExit('Existing .env preserved')
path.write_text('DB_PASSWORD='+secrets.token_urlsafe(32)+'\nHOST_DATA_ROOT='+str(root/'data')+'\nPUBLIC_ORIGIN=http://localhost:8787\nENGINE_IMAGE=private-gee-engine:arm64\n')
path.chmod(0o600)
for d in ['assets','jobs','raw','catalog']:
    (root/'data'/d).mkdir(parents=True,exist_ok=True)
print('Created .env and data directories')
