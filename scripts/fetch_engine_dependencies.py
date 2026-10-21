#!/usr/bin/env python3
"""Restore large JVM dependencies excluded from Git, checking pinned SHA-256.

Only an explicit invocation downloads anything. Existing mismatched files are
preserved and rejected. This helper does not start services or execute artifacts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def artifacts(root=ROOT):
    root = Path(root)
    sources = [('jars', json.loads((root / 'engine/jars-lock.json').read_text())),
               ('security-jars', json.loads((root / 'engine/security-downloads.json').read_text()))]
    security = {x['file']: x['sha256'] for x in
                json.loads((root / 'engine/security-jar-lock.json').read_text())}
    restored = {x['file']: x['sha256'] for x in sources[1][1]}
    if security != restored:
        raise ValueError('Security download manifest differs from the security JAR lock')
    return [(root / 'engine' / directory, item) for directory, rows in sources for item in rows]


def restore(directory, item, *, verify_only=False):
    directory = Path(directory)
    name = item['file']
    if Path(name).name != name or not name.endswith('.jar'):
        raise ValueError('Invalid artifact filename')
    if not item['url'].startswith('https://'):
        raise ValueError('Artifacts require HTTPS')
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError('Artifact directory cannot be a symbolic link')
    target = directory / name
    if target.is_symlink():
        raise ValueError('Artifact cannot be a symbolic link: ' + name)
    if target.exists():
        if not target.is_file() or digest(target) != item['sha256']:
            raise ValueError('Existing artifact differs from lock; preserved: ' + name)
        return 'verified'
    if verify_only:
        raise FileNotFoundError('Missing locked artifact: ' + name)
    directory.mkdir(parents=True, exist_ok=True)
    expected_size = item.get('size')
    limit = expected_size if expected_size is not None else 512 * 1024 * 1024
    descriptor, temporary = tempfile.mkstemp(prefix='.' + name + '.', dir=directory)
    temporary = Path(temporary)
    try:
        started = time.monotonic()
        with os.fdopen(descriptor, 'wb') as out:
            with urllib.request.urlopen(item['url'], timeout=30) as response:
                if not response.url.startswith('https://'):
                    raise ValueError('HTTPS downgrade refused')
                count = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    count += len(chunk)
                    if count > limit or time.monotonic() - started > 600:
                        raise ValueError('Artifact size or time limit exceeded: ' + name)
                    out.write(chunk)
        if expected_size is not None and count != expected_size:
            raise ValueError('Artifact byte count differs from lock: ' + name)
        if digest(temporary) != item['sha256']:
            raise ValueError('Artifact checksum differs from lock: ' + name)
        # Publish without clobbering a concurrent restoration or an existing file.
        os.link(temporary, target)
        return 'downloaded'
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    for directory, item in artifacts():
        print(restore(directory, item, verify_only=args.verify_only), item['file'], flush=True)
    print('All locked JVM artifacts verified. No services started.')


if __name__ == '__main__':
    main()
