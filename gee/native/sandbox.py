"""Fail-closed macOS Seatbelt profiles. No VM/container or Python-only sandbox."""
import json
import os
import sys
from pathlib import Path


def quoted(path):
    return json.dumps(str(Path(path).resolve()))


def profile(*, reads=(), writes=(), api_port=None, spark=False):
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise RuntimeError('macOS sandbox-exec is required; unsandboxed execution is disabled')
    rules = ['(version 1)', '(deny default)', '(allow process-exec process-fork)',
             '(allow signal (target self) (target children))', '(allow sysctl-read)',
             '(allow mach-lookup)', '(allow ipc-posix-shm)',
             '(allow file-read-metadata)',
             '(allow file-read* (literal "/") (subpath "/System") (subpath "/usr/lib") (subpath "/usr/share")',
             ' (subpath "/Library/Apple") (subpath "/private/var/db/dyld")',
             ' (subpath "/private/var/db/timezone") (literal "/private/etc/localtime")',
             ' (literal "/private/etc/hosts") (literal "/private/etc/resolv.conf")',
             ' (literal "/private/etc/ssl/openssl.cnf")',
             ' (literal "/dev/null") (literal "/dev/random") (literal "/dev/urandom") (subpath "/dev/fd"))',
             '(allow file-write* (literal "/dev/null") (subpath "/dev/fd"))']
    for path in reads:
        resolved = Path(path).resolve()
        scope = 'literal' if resolved.is_file() else 'subpath'
        rules.append(f'(allow file-read* ({scope} {quoted(resolved)}))')
    for path in writes:
        rules.append(f'(allow file-read* file-write* (subpath {quoted(path)}))')
    if api_port is not None:
        if type(api_port) is not int or not 1024 <= api_port <= 65535:
            raise ValueError('Invalid API port')
        rules.append(f'(allow network-outbound (remote tcp "localhost:{api_port}"))')
    if spark:
        # Spark's driver, executors and Py4J communicate only over loopback.
        rules += ['(allow network-inbound (local tcp "localhost:*"))',
                  '(allow network-outbound (remote tcp "localhost:*"))',
                  '(allow network-bind (local ip "localhost:*"))']
    return '\n'.join(rules) + '\n'


def runtime_reads(root, python, node=None, engine=False):
    root = Path(root)
    paths = [root / '.venv', Path(python).resolve().parents[1], root / 'gee']
    if node:
        paths.extend([Path(node).resolve().parents[1], root / '.native/eejs'])
    if engine:
        paths.extend([root / '.native/engine', root / '.native/jars', root / 'engine',
                      Path(os.environ['JAVA_HOME']).resolve(), Path('/opt/homebrew/Cellar')])
        paths.extend([root / '.native/engine-lock.json', root / 'deploy/smile-rf-lock.json',
                      root / 'scripts/build_smile_rf_adapter.py'])
    # C extensions may link Homebrew libraries. Cellar contains packages, not user state.
    paths.append(Path('/opt/homebrew/Cellar'))
    return [p for p in paths if p.exists()]
