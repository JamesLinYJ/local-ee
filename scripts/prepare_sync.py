"""Provision a dedicated catalogue-only sync login without exposing its credential."""
import os,secrets,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];env=root/'.env'
lines=env.read_text().splitlines();existing=next((s.split('=',1)[1] for s in lines if s.startswith('SYNC_DB_PASSWORD=')),None)
password=existing or secrets.token_urlsafe(32)
code='''import sys\nfrom psycopg import sql\nfrom gee import db\npassword=sys.stdin.read().strip()\nwith db.connect() as c:\n    if not c.execute("SELECT 1 FROM pg_roles WHERE rolname='gee_sync'").fetchone():\n        c.execute('CREATE ROLE gee_sync LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION')\n    c.execute(sql.SQL('ALTER ROLE gee_sync PASSWORD {}').format(sql.Literal(password)))\n    c.execute('GRANT CONNECT ON DATABASE gee TO gee_sync')\n    c.execute('GRANT USAGE ON SCHEMA public TO gee_sync')\n    c.execute('GRANT SELECT,INSERT,UPDATE ON collections,items,sync_runs TO gee_sync')\nprint('Catalogue-only database login configured')\n'''
subprocess.run(['docker-compose','exec','-T','api','python','-c',code],cwd=root,input=password,text=True,check=True)
# Only the explicit ingestion subtrees become writable by uid1000; job directories are excluded.
permissions='''import os\nfrom pathlib import Path\nfor name in ['assets','catalog','raw']:\n    top=Path('/data')/name;top.mkdir(parents=True,exist_ok=True)\n    for folder,dirs,files in os.walk(top,followlinks=False):\n        p=Path(folder)\n        if p.is_symlink():raise RuntimeError('Unexpected ingestion directory symlink')\n        os.chown(p,1000,1000);p.chmod(0o750)\n        for name in files:\n            p=Path(folder)/name\n            if p.is_symlink():raise RuntimeError('Unexpected ingestion file symlink')\n            os.chown(p,1000,1000);p.chmod(0o640)\nprint('Ingestion subtree permissions configured')\n'''
subprocess.run(['docker-compose','exec','-T','worker','python','-c',permissions],cwd=root,check=True)
if not existing:
    temp=env.with_suffix('.pending');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write('\n'.join(lines)+'\nSYNC_DB_PASSWORD='+password+'\n')
    temp.replace(env)
print('Sync can now be explicitly enabled; no provider credential was added')
