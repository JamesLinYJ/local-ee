"""Select only the installed project toolchains matching the public security profile."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selected(root):
    root = Path(root).resolve()
    profile_path = root/'engine/native-toolchains.json'
    lock_path = root/'.native/toolchain-lock.json'
    if not lock_path.is_file():
        raise RuntimeError('Install locked native runtimes: .venv/bin/python scripts/install_native_toolchains.py')
    lock = json.loads(lock_path.read_text())
    profile = json.loads(profile_path.read_text())
    if lock.get('profile_sha256') != digest(profile_path):
        raise RuntimeError('Native toolchain profile changed; reinstall its verified artifacts')
    result = {}
    base = root/'.native/toolchains'
    for item in profile['artifacts']:
        record = lock['artifacts'][item['kind']]
        home = base/item['directory']
        if record['archive_sha256'] != item['sha256'] or home != home.resolve():
            raise RuntimeError('Native toolchain provenance mismatch')
        for name, expected in record['critical_files'].items():
            path = home/name
            if not path.is_file() or digest(path) != expected:
                raise RuntimeError('Native runtime integrity check failed: '+item['kind'])
        result[item['kind']] = home
    return dict(java_home=str(result['java']), node=str(result['node']/'bin/node'))
