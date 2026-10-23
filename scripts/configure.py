"""Generate deployment-local secrets, without printing them or putting them in images."""
import os
import secrets
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'.env'
try:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
except FileExistsError:
    raise SystemExit('Existing .env preserved') from None
with os.fdopen(fd,'w') as stream:
    os.fchmod(stream.fileno(),0o600)
    stream.write('DB_PASSWORD='+secrets.token_urlsafe(32)+'\nHOST_DATA_ROOT='+str(root/'data')+'\nPUBLIC_ORIGIN=http://localhost:8787\nENGINE_IMAGE=private-gee-engine:arm64\n')
for d in ['assets','jobs','raw','catalog']:
    (root/'data'/d).mkdir(parents=True,exist_ok=True)
print('Created .env and data directories')
