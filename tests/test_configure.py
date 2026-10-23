"""Exercise the deployment CLI in a disposable checkout with synthetic secrets."""
import io
import os
from pathlib import Path
import runpy
import shutil
import stat

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/configure.py'


def deployment(tmp_path):
    root = tmp_path / 'deployment'
    (root / 'scripts').mkdir(parents=True)
    script = root / 'scripts/configure.py'
    shutil.copyfile(SOURCE, script)
    return root, script


@pytest.mark.parametrize('mask', [0o022, 0o000, 0o777])
def test_password_is_private_before_first_write(tmp_path, monkeypatch, capsys, mask):
    root, script = deployment(tmp_path)
    (root / 'data/assets').mkdir(parents=True)
    marker = root / 'data/assets/keep'
    marker.write_text('synthetic existing data')
    observed = []
    original = io.open

    class Writer:
        def __init__(self, stream): self.stream = stream
        def fileno(self): return self.stream.fileno()
        def __enter__(self): return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def write(self, value):
            observed.append(stat.S_IMODE(os.fstat(self.stream.fileno()).st_mode))
            return self.stream.write(value)

    def opened(file, mode='r', *args, **kwargs):
        stream = original(file, mode, *args, **kwargs)
        return Writer(stream) if 'w' in mode and (isinstance(file, int) or Path(file).name == '.env') else stream

    monkeypatch.setattr(io, 'open', opened)
    monkeypatch.setattr('secrets.token_urlsafe', lambda size: 'synthetic-password')
    previous = os.umask(mask)
    try:
        runpy.run_path(str(script), run_name='__main__')
    finally:
        os.umask(previous)
        # The restrictive-umask case also creates mode000 test directories.
        for name in ['jobs', 'raw', 'catalog']:
            directory = root / 'data' / name
            if directory.is_dir(): directory.chmod(0o700)
    assert observed and all(mode == 0o600 for mode in observed)
    assert stat.S_IMODE((root / '.env').stat().st_mode) == 0o600
    assert 'DB_PASSWORD=synthetic-password\n' in (root / '.env').read_text()
    assert all((root / 'data' / name).is_dir() for name in ['assets', 'jobs', 'raw', 'catalog'])
    assert marker.read_text() == 'synthetic existing data'
    assert 'synthetic-password' not in capsys.readouterr().out


@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink', 'dangling'])
def test_existing_destination_is_never_changed(tmp_path, capsys, kind):
    root, script = deployment(tmp_path)
    destination = root / '.env'
    target = root / 'target'
    if kind == 'directory': destination.mkdir()
    elif kind in {'symlink', 'dangling'}:
        if kind == 'symlink': target.write_text('keep target')
        destination.symlink_to(target)
    else: destination.write_text('keep file')
    before = destination.lstat()
    with pytest.raises(SystemExit, match='Existing .env preserved'):
        runpy.run_path(str(script), run_name='__main__')
    after = destination.lstat()
    assert (before.st_ino, before.st_mode) == (after.st_ino, after.st_mode)
    if kind == 'file': assert destination.read_text() == 'keep file'
    if kind == 'symlink': assert target.read_text() == 'keep target'
    if kind == 'dangling': assert not target.exists()
    assert not (root / 'data').exists()
    assert 'Created' not in capsys.readouterr().out


def test_competing_creator_is_preserved(tmp_path, monkeypatch):
    root, script = deployment(tmp_path)
    original = os.open

    def competing(file, flags, mode=0o777, **kwargs):
        if Path(file) == root / '.env':
            (root / '.env').write_text('created concurrently')
        return original(file, flags, mode, **kwargs)

    monkeypatch.setattr(os, 'open', competing)
    with pytest.raises(SystemExit, match='Existing .env preserved'):
        runpy.run_path(str(script), run_name='__main__')
    assert (root / '.env').read_text() == 'created concurrently'
    assert not (root / 'data').exists()
