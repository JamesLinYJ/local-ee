"""Build the TypeScript/React frontend away from the live mount and publish index last."""
import hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];web=root/'web'
with tempfile.TemporaryDirectory(prefix='private-gee-web-') as temporary:
 output=Path(temporary)/'dist'
 subprocess.run(['npm','run','build','--','--outDir',str(output)],cwd=web,check=True)
 target=web/'dist';target.mkdir(exist_ok=True)
 for source in output.iterdir():
  if source.name=='index.html':continue
  if source.is_dir():shutil.copytree(source,target/source.name,dirs_exist_ok=True)
  else:shutil.copy2(source,target/source.name)
 report={'framework':'TypeScript + React','package_lock_sha256':hashlib.sha256((web/'package-lock.json').read_bytes()).hexdigest(),'node':subprocess.check_output(['node','--version'],text=True).strip(),'files':{str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file()}}
 pending=target/'.index-pending';shutil.copyfile(output/'index.html',pending);os.replace(pending,target/'index.html')
 (root/'deploy/web-lock.json').write_text(json.dumps(report,indent=2)+'\n')
print('Published React frontend; assets first, index last. Existing asset hashes preserved for open tabs.')
