"""Consistent native backup; refuses active tasks and never starts containers."""
import argparse,datetime,hashlib,json,os,subprocess,tarfile,tempfile
from pathlib import Path
import native
from zoneinfo import ZoneInfo


def main():
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);args=p.parse_args()
    os.umask(0o077);os.environ.update(native.environment())
    from gee import db
    def active():return db.query("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','running')",one=True)['n']
    if active():raise SystemExit('请先完成或取消排队/运行任务，再备份')
    running=[name for name in ['api','worker'] if native.process(name)]
    args.destination.mkdir(parents=True,exist_ok=True)
    target=args.destination/('private-gee-native-'+datetime.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')+'.tar.gz')
    c=native.config();env={**os.environ,'PGHOST':str(native.RUN/'pg'),'PGPORT':'55432','PGUSER':'gee','PGDATABASE':'gee','PGPASSWORD':c['database_password']}
    try:
        for name in running:native.stop_service(name)
        if active():raise RuntimeError('任务状态已变化；未开始备份，请稍后重试')
        counts={table:db.query('SELECT count(*) AS n FROM '+table,one=True)['n'] for table in ['users','scripts','jobs','collections','items','dataset_files']}
        with tempfile.TemporaryDirectory() as temporary:
            temporary=Path(temporary);dump=temporary/'database.dump'
            with dump.open('wb') as out:
                subprocess.run([str(native.PG/'pg_dump'),'-Fc','--no-owner','--no-acl'],env=env,stdout=out,check=True)
            files={str(path.relative_to(native.ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in (native.ROOT/'data').rglob('*') if path.is_file() and not path.is_symlink()}
            metadata={'format':'private-gee-native-v1','counts':counts,'files':files,'database_sha256':hashlib.sha256(dump.read_bytes()).hexdigest()}
            (temporary/'native-backup.json').write_text(json.dumps(metadata,indent=2))
            with tarfile.open(str(target)+'.part','w:gz') as archive:
                archive.add(dump,arcname='database.dump');archive.add(temporary/'native-backup.json',arcname='native-backup.json')
                for name in ['data','.native/config.json','.native/engine-lock.json','.native/engine-requirements.lock','deploy/native-login.txt','deploy/native-lock.json','upstream-lock.json','requirements.lock','web/dist']:
                    path=native.ROOT/name
                    if path.exists():archive.add(path,arcname=name)
            Path(str(target)+'.part').rename(target);target.chmod(0o600)
    finally:
        if running:native.start()
    print(target)


if __name__=='__main__':main()
