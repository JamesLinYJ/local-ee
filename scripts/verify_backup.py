"""Restore a native backup into a new disposable PostgreSQL database, verify, remove it."""
import argparse,hashlib,json,os,subprocess,tarfile,tempfile,uuid
from pathlib import Path
import native


def main():
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--report',required=True,type=Path);args=p.parse_args()
    if args.report.exists():raise SystemExit('Report already exists; preserve historical evidence')
    os.umask(0o077);os.environ.update(native.environment())
    c=native.config();env={**os.environ,'PGHOST':str(native.RUN/'pg'),'PGPORT':'55432','PGUSER':'gee','PGPASSWORD':c['database_password']}
    name='gee_restore_'+uuid.uuid4().hex
    with tempfile.TemporaryDirectory() as temporary:
        dump=Path(temporary)/'database.dump'
        with tarfile.open(args.archive) as tar:
            for member in tar.getmembers():
                if member.issym() or member.islnk() or member.name.startswith('/') or '..' in Path(member.name).parts:raise ValueError('Unsafe backup member')
            metadata=json.load(tar.extractfile('native-backup.json'))
            with dump.open('wb') as out:
                import shutil
                shutil.copyfileobj(tar.extractfile('database.dump'),out)
            if hashlib.sha256(dump.read_bytes()).hexdigest()!=metadata['database_sha256']:raise ValueError('Database checksum mismatch')
            for path,expected in metadata['files'].items():
                stream=tar.extractfile(path);h=hashlib.sha256()
                while chunk:=stream.read(1024*1024):h.update(chunk)
                if h.hexdigest()!=expected:raise ValueError('Artifact checksum mismatch: '+path)
        subprocess.run([str(native.PG/'createdb'),name],env=env,check=True)
        try:
            subprocess.run([str(native.PG/'pg_restore'),'--dbname',name,'--no-owner','--no-acl','--exit-on-error',str(dump)],env=env,check=True)
            import psycopg
            from psycopg.conninfo import conninfo_to_dict
            values=conninfo_to_dict(os.environ['DATABASE_URL']);values['dbname']=name
            with psycopg.connect(**values) as connection:
                counts={table:connection.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['users','scripts','jobs','collections','items','dataset_files']}
            report={'archive':str(args.archive),'separate_database_restore':True,'counts':counts,'counts_match':counts==metadata['counts'],'files_verified':len(metadata['files']),'all_file_checksums_match':True,'independent_backup_device':False}
            args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
            assert report['counts_match'],report
            print(json.dumps(report,indent=2))
        finally:subprocess.run([str(native.PG/'dropdb'),name],env=env,check=True)


if __name__=='__main__':main()
