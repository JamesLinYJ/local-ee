"""Capacity, ownership and restart rules use disposable synthetic leases."""
import errno
import json
import os
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from gee.native import scratch


@pytest.fixture
def volume(monkeypatch, tmp_path):
    root=tmp_path/'project';root.mkdir()
    mounted={};faults=set()
    monkeypatch.setattr(scratch,'CAPACITY_MIB',32)
    monkeypatch.setattr(scratch.shutil,'disk_usage',lambda _:SimpleNamespace(free=10*1024**3))
    monkeypatch.setattr(scratch.os.path,'ismount',lambda p:str(p) in mounted.values())
    def run(*args):
        if args[0]=='create':
            with Path(args[-1]).open('wb') as out:out.truncate(32*1024**2)
        if args[0]=='attach':mounted[str(args[-1])]=str(args[args.index('-mountpoint')+1])
        if args[0]=='detach':
            if 'detach' in faults:raise RuntimeError('synthetic detach failure')
            for key in [key for key,value in mounted.items() if value==str(args[1])]:del mounted[key]
        return plistlib.dumps({'images':[{'image-path':key,'system-entities':[{'mount-point':value}]} for key,value in mounted.items()]})
    monkeypatch.setattr(scratch,'run',run)
    def reserve():
        jid=str(uuid4());mount=root/'data/jobs'/jid/'tmp';mount.mkdir(parents=True)
        return scratch.reserve(root,jid,mount)
    return root,reserve,mounted,faults


def test_two_persistent_slots_bound_capacity_and_cleanup(volume):
    root,reserve,_,_=volume
    first,second=reserve(),reserve()
    with pytest.raises(RuntimeError,match='capacity occupied'):reserve()
    scratch.prepare(first)
    scratch.release(first)
    assert not first.parent.exists()
    replacement=reserve()
    for lease in [second,replacement]:scratch.release(lease)


def test_failed_detach_keeps_image_and_capacity_lease(volume):
    root,reserve,mounted,faults=volume
    first=reserve();scratch.prepare(first);faults.add('detach')
    with pytest.raises(RuntimeError,match='detach failure'):scratch.release(first)
    assert first.exists() and first.with_name('scratch.dmg').is_file()
    assert scratch.read(first)['phase']=='cleanup_failed' and mounted
    second=reserve()
    with pytest.raises(RuntimeError,match='capacity occupied'):reserve()
    faults.clear();scratch.release(first);scratch.release(second)


def test_live_owner_is_not_reaped_and_stale_owner_can_be_recovered(volume):
    root,reserve,_,_=volume
    lease=reserve();scratch.prepare(lease)
    scratch.recover(root)
    assert lease.exists()
    value=scratch.read(lease);value['owner']={'pid':99999999,'created':0};scratch.save(lease,value)
    scratch.recover(root)
    assert not lease.parent.exists()


def test_interrupted_provisioning_is_not_guessed_safe(volume):
    root,reserve,_,_=volume
    lease=reserve();value=scratch.read(lease)
    value.update(owner={'pid':99999999,'created':0},phase='preparing');scratch.save(lease,value)
    scratch.recover(root)
    assert lease.exists()
    scratch.release(lease)


def test_backing_symlink_and_foreign_mount_are_preserved(volume, tmp_path):
    root,reserve,mounted,_=volume
    lease=reserve();image=lease.with_name('scratch.dmg')
    target=tmp_path/'keep';target.write_text('synthetic outside file');image.symlink_to(target)
    with pytest.raises(RuntimeError,match='identity changed'):scratch.release(lease)
    assert target.read_text()=='synthetic outside file' and lease.exists()
    image.unlink();mounted[str(image)]='/synthetic/foreign-mount'
    with pytest.raises(RuntimeError,match='identity changed'):scratch.release(lease)
    mounted.clear();scratch.release(lease)


def test_host_free_space_admission_precedes_allocation(volume, monkeypatch):
    root,reserve,_,_=volume
    monkeypatch.setattr(scratch.shutil,'disk_usage',lambda _:SimpleNamespace(free=scratch.RESERVE_BYTES))
    with pytest.raises(RuntimeError,match='free-space reserve'):reserve()
    assert not list((root/'.native/run/scratch').glob('*/lease.json'))


@pytest.mark.skipif(sys.platform!='darwin',reason='macOS fixed filesystem acceptance')
def test_real_fixed_filesystem_enforces_aggregate_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch,'CAPACITY_MIB',32)
    root=tmp_path/'project';root.mkdir()
    jid=str(uuid4());mount=root/'data/jobs'/jid/'tmp';mount.mkdir(parents=True)
    lease=scratch.reserve(root,jid,mount)
    try:
        scratch.prepare(lease)
        assert os.path.ismount(mount)
        (mount/'ordinary.txt').write_text('影像🌍')
        assert (mount/'ordinary.txt').read_text()=='影像🌍'
        with pytest.raises(OSError) as caught:
            for index in range(16):
                with (mount/f'file-{index}').open('wb') as out:out.write(b'x'*(4*1024**2))
        assert caught.value.errno==errno.ENOSPC
        assert lease.with_name('scratch.dmg').stat().st_size<=32*1024**2
    finally:
        scratch.release(lease)
    assert not os.path.ismount(mount) and not lease.parent.exists()
