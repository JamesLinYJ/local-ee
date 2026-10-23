"""Trusted detached task supervisor: resource monitoring survives scheduler restarts."""
import json
import os
import resource
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
import psutil


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def main(manifest):
    os.umask(0o077)
    config = json.loads(Path(manifest).read_text())
    state_path = Path(config['state'])
    state = {'status': 'starting', 'pid': os.getpid(),
             'create_time': psutil.Process().create_time(), 'exit_code': None, 'reason': None}
    save(state_path, state)
    child = None
    lease = config.get('scratch_lease')
    gate_read = gate_write = None
    stopped = False
    def terminate(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    logs = bytearray()
    token = config['env'].get('OPENEO_TOKEN')
    log_path = Path(config['log'])
    def persist_logs():
        value=bytes(logs[-200000:])
        if token: value=value.replace(token.encode(),b'[REDACTED]')
        log_path.write_bytes(value)
    user_processes=sum(bool(p.info['uids'] and p.info['uids'].real==os.getuid()) for p in psutil.process_iter(['uids'],ad_value=None))
    def limits():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (config['timeout'], config['timeout'] + 2))
        soft,hard=resource.getrlimit(resource.RLIMIT_NPROC)
        bounded=user_processes+64
        if hard!=resource.RLIM_INFINITY:bounded=min(bounded,hard)
        resource.setrlimit(resource.RLIMIT_NPROC,(bounded,bounded))
    try:
        command=config['command']
        extra={}
        if lease:
            from . import scratch
            scratch.prepare(lease)
            if stopped: raise InterruptedError('Task stopped during scratch provisioning')
            gate_read,gate_write=os.pipe()
            command=[sys.executable,'-m','gee.native.gate',str(gate_read),*command]
            extra['pass_fds']=(gate_read,)
        child = subprocess.Popen(command, cwd=config['cwd'], env=config['env'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=limits,**extra)
        state.update(status='running', child_pid=child.pid,child_create_time=psutil.Process(child.pid).create_time())
        save(state_path, state)
        if lease:
            scratch.started(lease,child.pid)
            if stopped: raise InterruptedError('Task stopped before script launch')
            os.close(gate_read);gate_read=None
            os.write(gate_write,b'1')
            os.close(gate_write);gate_write=None
        watcher = psutil.Process(child.pid)
        selector = selectors.DefaultSelector()
        os.set_blocking(child.stdout.fileno(), False)
        selector.register(child.stdout, selectors.EVENT_READ)
        started = time.monotonic()
        last_save = 0
        while child.poll() is None:
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if chunk:
                    logs.extend(chunk)
                    del logs[:-200000]
            reason = None
            if stopped:
                reason = 'stopped'
            elif time.monotonic() - started > config['timeout']:
                reason = 'timeout'
            else:
                try:
                    processes = [watcher, *watcher.children(recursive=True)]
                    rss=sum(p.memory_info().rss for p in processes if p.is_running())
                    state['peak_rss_bytes']=max(state.get('peak_rss_bytes',0),rss)
                    state['peak_processes']=max(state.get('peak_processes',0),len(processes))
                    if len(processes) > 64:
                        reason = 'process_limit'
                    elif rss > config['memory_bytes']:
                        reason = 'memory_limit'
                except psutil.Error:
                    pass
            if reason:
                state['reason'] = reason
                os.killpg(child.pid, signal.SIGKILL)
                break
            if time.monotonic() - last_save > 1:
                persist_logs()
                last_save = time.monotonic()
        child.wait()
        # Kill descendants before publication; no background writer survives the task.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        while True:
            try:
                chunk = os.read(child.stdout.fileno(), 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            logs.extend(chunk)
            del logs[:-200000]
        state.update(status='exited', exit_code=child.returncode)
    except BaseException as error:
        if child:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        logs.extend(str(error).encode()[-2000:])
        state.update(status='exited', exit_code=1, reason='stopped' if stopped else 'supervisor_error')
    finally:
        for fd in (gate_read,gate_write):
            if fd is not None:os.close(fd)
        if child and child.poll() is None:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait(timeout=5)
        if lease:
            try:
                from .scratch import release
                release(lease)
            except BaseException:
                state.update(status='exited',exit_code=1,reason='scratch_cleanup_failed')
                logs.extend(b'\nScratch cleanup failed; capacity lease retained.\n')
        persist_logs()
        # Secrets are needed only during launch. Never retain a completed task's token.
        config['env'].pop('OPENEO_TOKEN', None)
        save(Path(manifest), config)
        save(state_path, state)


if __name__ == '__main__':
    main(sys.argv[1])
