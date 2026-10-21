"""Pin deployment to built image content identities; never prints secrets.

Existing pins are preserved unless --image KEY=TAG explicitly replaces one.
"""
import argparse,json,re,subprocess,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--image',action='append',default=[],metavar='KEY=TAG');args=p.parse_args()
allowed={'APP_IMAGE','ENGINE_IMAGE','POSTGRES_IMAGE','NGINX_IMAGE','JS_IMAGE'}
path=root/'deploy/images-lock.json';report=json.loads(path.read_text()) if path.exists() else {}
env=(root/'.env').read_text();images={}
for value in args.image:
 key,tag=value.split('=',1)
 if key not in allowed or not tag:raise SystemExit('Invalid image key/tag')
 images[key]=tag
if not images:raise SystemExit('Pass --image KEY=TAG for each image to replace')
for key,tag in images.items():
 metadata=json.loads(subprocess.check_output(['docker','image','inspect',tag]))[0]
 digest=metadata['Id'];report[key]={'tag':tag,'id':digest,'repo_digests':metadata.get('RepoDigests',[]),'architecture':metadata['Architecture'],'os':metadata['Os']}
 if re.search('^'+key+'=',env,re.M):env=re.sub('^'+key+'=.*$',key+'='+digest,env,flags=re.M)
 else:env+='\n'+key+'='+digest+'\n'
temporary=root/'.env.pin-pending'
fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as stream:stream.write(env)
temporary.replace(root/'.env');path.write_text(json.dumps(report,indent=2)+'\n');print('Pinned '+', '.join(images))
