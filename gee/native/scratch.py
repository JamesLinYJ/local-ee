"""Two persistent capacity leases for fixed-size native script filesystems."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import tempfile
from uuid import UUID

import psutil

CAPACITY_MIB = 512
SLOTS = 2
RESERVE_BYTES = 1024**3


def save(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.lease-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def identity(pid=None):
    process = psutil.Process(pid)
    return dict(pid=process.pid, created=process.create_time())


def alive(value):
    if not value: return False
    try:
        process = psutil.Process(value['pid'])
        return abs(process.create_time()-value['created']) < .01 and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


@contextmanager
def locked(base):
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if base.is_symlink(): raise RuntimeError('Invalid scratch control directory')
    fd = os.open(base/'capacity.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def read(path):
    if path.is_symlink() or not path.is_file(): raise RuntimeError('Missing scratch lease')
    value = json.loads(path.read_text())
    jid = str(UUID(value['job_id']))
    mount = Path(value['mount'])
    if (jid != value['job_id'] or mount.name != 'tmp' or mount.parent.name != jid
            or mount.parent.parent.name != 'jobs' or mount != mount.resolve()
            or path.parent.name not in {'0','1'}):
        raise RuntimeError('Invalid scratch lease')
    return value


def run(*args):
    result = subprocess.run(['/usr/bin/hdiutil', *map(str,args)], capture_output=True, timeout=60)
    if result.returncode: raise RuntimeError('Native scratch filesystem operation failed')
    return result.stdout


def attachments(image):
    info = plistlib.loads(run('info','-plist'))
    return [row for row in info.get('images',[]) if row.get('image-path') == str(image)]


def reserve(root, jid, mount):
    base = Path(root)/'.native/run/scratch'
    with locked(base):
        occupied = sum((base/str(index)).exists() for index in range(SLOTS))
        required = RESERVE_BYTES+(occupied+1)*CAPACITY_MIB*1024**2
        if shutil.disk_usage(base).free < required: raise RuntimeError('Native scratch free-space reserve unavailable')
        for index in range(SLOTS):
            slot = base/str(index)
            try: slot.mkdir(mode=0o700)
            except FileExistsError: continue
            path = slot/'lease.json'
            save(path,dict(job_id=str(jid),mount=str(Path(mount).resolve()),phase='reserved',owner=identity()))
            read(path)
            return path
    raise RuntimeError('Native scratch capacity occupied; retained leases require cleanup')


def prepare(path):
    path=Path(path)
    with locked(path.parent.parent):
        value=read(path)
        mount=Path(value['mount']); image=path.parent/'scratch.dmg'
        if value['phase']!='reserved' or image.exists() or mount.is_symlink() or any(mount.iterdir()):
            raise RuntimeError('Scratch is not a new empty directory')
        value.update(owner=identity(),phase='preparing');save(path,value)
        run('create','-size',f'{CAPACITY_MIB}m','-type','UDIF','-fs','HFS+',
            '-layout','NONE','-volname','local-ee-scratch','-nospotlight',image)
        if image.is_symlink() or not image.is_file() or image.stat().st_size>CAPACITY_MIB*1024**2:
            raise RuntimeError('Invalid scratch backing image')
        value['image_inode']=image.stat().st_ino;save(path,value)
        run('attach','-nobrowse','-noautoopen','-owners','on','-mountpoint',mount,'-plist',image)
        matches=attachments(image)
        mounts=[entry.get('mount-point') for row in matches for entry in row.get('system-entities',[]) if entry.get('mount-point')]
        if len(matches)!=1 or mounts!=[str(mount)] or not os.path.ismount(mount):
            raise RuntimeError('Scratch mount identity mismatch')
        value['phase']='mounted';save(path,value)


def started(path, pid):
    path=Path(path)
    with locked(path.parent.parent):
        value=read(path)
        value.update(child=identity(pid),phase='running');save(path,value)


def release(path, *, recovering=False):
    path=Path(path)
    if not path.exists(): return
    with locked(path.parent.parent):
        value=read(path)
        if recovering and alive(value.get('owner')): return
        if recovering and value['phase'] in {'preparing','releasing'}:
            raise RuntimeError('Interrupted scratch provisioning requires operator reconciliation')
        child=value.get('child')
        if alive(child):
            if not recovering: raise RuntimeError('Script is still running; scratch retained')
            if os.getpgid(child['pid'])!=child['pid']: raise RuntimeError('Script identity changed')
            os.killpg(child['pid'],signal.SIGKILL)
            try: psutil.Process(child['pid']).wait(timeout=5)
            except psutil.NoSuchProcess: pass
            if alive(child): raise RuntimeError('Script did not terminate; scratch retained')
        mount=Path(value['mount']);image=path.parent/'scratch.dmg'
        if image.exists() or image.is_symlink():
            if image.is_symlink() or not image.is_file() or image.stat().st_ino!=value.get('image_inode'):
                raise RuntimeError('Scratch backing identity changed; retained')
        matches=attachments(image)
        mounts=[entry.get('mount-point') for row in matches for entry in row.get('system-entities',[]) if entry.get('mount-point')]
        if (len(matches)>1 or (matches and mounts!=[str(mount)])
                or (os.path.ismount(mount) and not matches)):
            raise RuntimeError('Scratch attachment identity changed; retained')
        value['phase']='releasing';save(path,value)
        try:
            if matches: run('detach',mount)
            if attachments(image) or os.path.ismount(mount): raise RuntimeError('Scratch detach incomplete')
            if image.exists():
                if image.is_symlink() or not image.is_file() or image.stat().st_ino!=value.get('image_inode'):
                    raise RuntimeError('Scratch backing identity changed; retained')
                image.unlink()
            path.unlink()
            path.parent.rmdir()
        except BaseException:
            value['phase']='cleanup_failed';save(path,value)
            raise


def recover(root):
    base=Path(root)/'.native/run/scratch'
    for index in range(SLOTS):
        path=base/str(index)/'lease.json'
        if path.exists():
            try: release(path,recovering=True)
            except (OSError,RuntimeError,ValueError,psutil.Error,subprocess.SubprocessError):
                # Dirty slots stay occupied; they never authorize replacement capacity.
                pass
