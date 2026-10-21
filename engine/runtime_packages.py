"""Collect Debian-owned shared libraries, never copy builder toolchains into runtime."""
from pathlib import Path
import re
import subprocess
paths = set()
for root in [Path('/usr/local'), Path('/tmp/jni')]:
    for f in root.rglob('*.so*'):
        if not f.is_file():
            continue
        out = subprocess.run(['ldd', str(f)], capture_output=True, text=True).stdout
        paths.update(re.findall(r'=> (/\S+)', out))
packages = set()
for path in sorted(paths):
    if path.startswith(('/usr/local/', '/opt/')):
        continue
    alternatives = [path, str(Path(path).resolve())]
    if path.startswith('/lib/'):
        alternatives.append('/usr' + path)
    found = False
    for p in alternatives:
        owner = subprocess.run(['dpkg-query', '-S', p], capture_output=True, text=True)
        if owner.returncode == 0:
            owners=[line.split(': ',1)[0] for line in owner.stdout.splitlines() if ': ' in line]
            owners=[name for name in owners if re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?',name)]
            if owners:
                packages.update(owners)
                found = True
                break
    if not found:
        raise RuntimeError('Unaccounted runtime library: ' + path)
for package in sorted(packages):
    print(subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package}=${Version}', package], text=True))
