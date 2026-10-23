"""Install pinned native arm64 Node/JDK artifacts without changing global runtimes."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gee.native.toolchains import digest


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith('https://'): raise ValueError('HTTPS downgrade refused')
        request = super().redirect_request(req, fp, code, msg, headers, newurl)
        request.remove_header('Authorization')
        return request


def download(item, destination):
    headers = {}
    if item['url'].startswith('https://ghcr.io/v2/homebrew/core/openjdk/21/blobs/'):
        # Anonymous public package read token; no user account credentials are used.
        url = 'https://ghcr.io/token?'+urllib.parse.urlencode(dict(
            service='ghcr.io', scope='repository:homebrew/core/openjdk/21:pull'))
        with urllib.request.urlopen(url, timeout=30) as response:
            headers['Authorization'] = 'Bearer '+json.loads(response.read(65536))['token']
    opener = urllib.request.build_opener(PublicRedirect())
    started = time.monotonic(); size = 0
    with opener.open(urllib.request.Request(item['url'], headers=headers), timeout=30) as response, destination.open('wb') as stream:
        for chunk in iter(lambda: response.read(1024**2), b''):
            size += len(chunk)
            if size > item['size'] or time.monotonic()-started > 600:
                raise RuntimeError('Native runtime download exceeds locked budget')
            stream.write(chunk)


def relocate_jdk(home):
    """Apply Homebrew's native Mach-O placeholders inside this project-owned bottle."""
    changed = []
    for path in sorted((home/'lib').rglob('*.dylib')):
        lines = subprocess.check_output(['/usr/bin/otool', '-L', str(path)], text=True).splitlines()[1:]
        arguments = []
        for line in lines:
            old = line.strip().split(' (', 1)[0]
            if '@@HOMEBREW_PREFIX@@' not in old: continue
            internal = '@@HOMEBREW_PREFIX@@/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home'
            new = old.replace(internal, str(home)).replace('@@HOMEBREW_PREFIX@@', '/opt/homebrew')
            if old.endswith('/'+path.name) and old.startswith(internal):
                arguments += ['-id', new]
            else:
                arguments += ['-change', old, new]
        if arguments:
            subprocess.run(['/usr/bin/install_name_tool', *arguments, str(path)], check=True, capture_output=True)
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(path)], check=True, capture_output=True)
            changed.append(str(path.relative_to(home)))
    return changed


def install(archives=None):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This profile requires native Apple Silicon macOS')
    os.umask(0o077)
    profile_path = ROOT/'engine/native-toolchains.json'
    profile = json.loads(profile_path.read_text())
    base = ROOT/'.native/toolchains'; base.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = ROOT/'.native/toolchain-lock.json'
    previous = json.loads(lock.read_text()).get('artifacts', {}) if lock.is_file() else {}
    records = {}
    for item in profile['artifacts']:
        home = base/item['directory']
        if home.exists():
            record = previous.get(item['kind'], {})
            hashes = record.get('critical_files', {})
            if (record.get('archive_sha256') != item['sha256'] or not hashes
                    or home != home.resolve()
                    or any(not (home/name).is_file() or digest(home/name) != expected for name, expected in hashes.items())):
                raise RuntimeError('Existing runtime preserved; integrity reconciliation required: '+item['kind'])
            records[item['kind']] = record
            continue
        with tempfile.TemporaryDirectory(prefix='.install-', dir=base) as temporary:
            temporary = Path(temporary); archive = temporary/item['file']
            candidates = list(Path(archives).rglob('*')) if archives else []
            local = next((p for p in candidates if p.is_file() and p.stat().st_size == item['size'] and digest(p) == item['sha256']), None)
            if local: shutil.copyfile(local, archive)
            else: download(item, archive)
            if archive.stat().st_size != item['size'] or digest(archive) != item['sha256']:
                raise RuntimeError('Native archive checksum mismatch: '+item['kind'])
            unpacked = temporary/'unpacked'; unpacked.mkdir()
            with tarfile.open(archive) as source: source.extractall(unpacked, filter='data')
            relative = Path(item['directory']); top = relative.parts[0]
            # Publish the full native bundle, including licenses, before Mach-O paths change.
            if (base/top).exists(): raise RuntimeError('Existing native bundle preserved')
            shutil.move(unpacked/top, base/top)
        changed = relocate_jdk(home) if item['kind'] == 'java' else []
        output = subprocess.run([str(home/item['executable']), '-version' if item['kind']=='java' else '--version'],
                                check=True, capture_output=True, text=True, timeout=15)
        if item['version'] not in output.stdout+output.stderr: raise RuntimeError('Native runtime version mismatch')
        critical = ['bin/node'] if item['kind']=='node' else [
            'bin/java', 'bin/javac', 'lib/server/libjvm.dylib', 'lib/security/blocked.certs', *changed]
        records[item['kind']] = dict(archive_sha256=item['sha256'], version=item['version'],
                                    critical_files={name:digest(home/name) for name in sorted(set(critical))},
                                    relocated_native_libraries=changed)
    pending = lock.with_suffix('.pending')
    pending.write_text(json.dumps(dict(profile_sha256=digest(profile_path), artifacts=records), indent=2)+'\n')
    pending.replace(lock)
    print('Installed verified project Node/JDK runtimes; global runtimes preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives-dir', type=Path)
    install(parser.parse_args().archives_dir)
