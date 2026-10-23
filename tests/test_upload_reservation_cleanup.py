"""Storage lifetime around known rollback and uncertain commit results."""
from types import SimpleNamespace
import pytest
from gee.services import dataset_files as files


@pytest.fixture
def storage(monkeypatch, tmp_path):
    root = tmp_path / 'uploads'
    root.mkdir()
    monkeypatch.setenv('UPLOAD_ROOT', str(root))
    monkeypatch.setattr(files, 'actor_check', lambda *_: None)
    monkeypatch.setattr(files, 'audit', lambda *_: None)
    monkeypatch.setattr(files.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10*1024**3))
    return root


def connection(monkeypatch, *, failure=None, existing=None):
    class Connection:
        def __enter__(self): return self
        def __exit__(self, kind, *_):
            if kind is None and failure == 'commit': raise OSError('uncertain commit')
        def execute(self, sql, params=()):
            if sql.startswith('INSERT'):
                if failure == 'insert': raise ValueError('synthetic insert rollback')
                fid,cid,actor,name,size,digest=params
                value=dict(id=fid,collection_id=cid,filename=name,size=size,sha256=digest,status='uploading')
            elif 'SELECT * FROM dataset_files' in sql: value=existing
            elif 'SELECT id FROM collections' in sql: value={'id':'synthetic'}
            else: value={'n':0}
            return SimpleNamespace(fetchone=lambda:value)
    monkeypatch.setattr(files.db, 'connect', Connection)


def payload(name='影像🌍.tif'):
    return dict(filename=name,size=10,sha256='a'*64)


@pytest.mark.parametrize('failure', ['insert','audit','file'])
def test_known_precommit_failure_removes_only_new_reservation(storage, monkeypatch, failure):
    keep=storage/'existing';keep.mkdir();(keep/'content').write_bytes(b'keep')
    connection(monkeypatch,failure=failure)
    if failure == 'audit':
        def fail(*_): raise ValueError('synthetic audit rollback')
        monkeypatch.setattr(files,'audit',fail)
    if failure == 'file':
        original=files.Path.open
        def opened(path,*args,**kwargs):
            if path.name=='content.part': raise OSError('synthetic storage failure')
            return original(path,*args,**kwargs)
        monkeypatch.setattr(files.Path,'open',opened)
    with pytest.raises((ValueError,OSError)):
        files.create('synthetic-admin','synthetic',payload())
    assert list(storage.iterdir())==[keep]
    assert (keep/'content').read_bytes()==b'keep'


def test_unicode_filename_and_reservation_remain_valid(storage, monkeypatch):
    connection(monkeypatch)
    row=files.create('synthetic-admin','synthetic',payload())
    assert row['filename']=='影像🌍.tif'
    assert (storage/row['id']/'content.part').is_file()


def test_uncertain_commit_preserves_possible_durable_reservation(storage, monkeypatch):
    connection(monkeypatch,failure='commit')
    with pytest.raises(OSError,match='uncertain commit'):
        files.create('synthetic-admin','synthetic',payload())
    assert len(list(storage.glob('*/content.part')))==1


def test_deduplicated_reservation_is_preserved(storage, monkeypatch):
    existing=dict(id='existing',filename='原件.tif',status='stored')
    folder=storage/'existing';folder.mkdir();(folder/'content').write_bytes(b'keep')
    connection(monkeypatch,existing=existing)
    assert files.create('synthetic-admin','synthetic',payload())['id']=='existing'
    assert (folder/'content').read_bytes()==b'keep'
