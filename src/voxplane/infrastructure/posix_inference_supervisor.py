"""Standalone stdlib ownership guard, executed by the configured external Python.

The GUI alone holds the lifetime pipe's writer. EOF also arrives after SIGKILL.
A separate job anchor stays alive until cleanup, reserving its process-group ID
even when the bridge exits. Only that group is signalled; no PID scans or reuse
prone owner-PID checks are needed. Neither role imports the packaged application.
"""
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import traceback


def anchor(status_fd, command):
    # A caught (rather than ignored) signal resets to default in the exec'd bridge.
    signal.signal(signal.SIGTERM, lambda signum, frame: None)
    try:
        code = subprocess.Popen(command, close_fds=True).wait()
    except BaseException:
        traceback.print_exc()
        code = 125
    os.write(status_fd, (str(code) + '\n').encode('ascii'))
    os.close(status_fd)
    # Keep the PGID reserved until the supervisor finishes signalling the tree.
    while True:
        signal.pause()


def adopt_orphans():
    if sys.platform.startswith('linux'):
        # The dedicated supervisor can reap grandchildren after the anchor dies.
        # macOS reparents them to launchd, which performs that reaping itself.
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), 'Cannot own inference descendants')


def stop_job(job):
    # Never poll/wait before signalling: an unreaped anchor pins the PGID even
    # after an unexpected anchor failure, so no unrelated group can reuse it.
    try:
        os.killpg(job.pid, signal.SIGTERM)
        time.sleep(.5)
        os.killpg(job.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    job.wait(timeout=5)
    deadline = time.monotonic() + 2
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if not pid:
            if time.monotonic() >= deadline:
                return
            time.sleep(.01)


def supervise(lifetime_fd, command):
    adopt_orphans()
    os.set_inheritable(lifetime_fd, False)
    status_read, status_write = os.pipe()
    job = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(lifetime_fd, selectors.EVENT_READ, 'owner')
            # Avoid starting work if the owner already died during helper startup.
            if selector.select(timeout=0):
                return 0
            job = subprocess.Popen(
                [command[0], str(Path(__file__).resolve()), '--job', str(status_write), *command],
                start_new_session=True, pass_fds=(status_write,), close_fds=True)
            os.close(status_write)
            status_write = None
            selector.register(status_read, selectors.EVENT_READ, 'result')
            pending = b''
            while True:
                for key, _ in selector.select():
                    if key.data == 'owner':
                        return 0
                    chunk = os.read(status_read, 128)
                    if not chunk:
                        raise RuntimeError('Inference job anchor exited without a result')
                    pending += chunk
                    if b'\n' in pending:
                        return int(pending.split(b'\n', 1)[0])
    finally:
        try:
            if job is not None:
                stop_job(job)
        finally:
            os.close(status_read)
            if status_write is not None:
                os.close(status_write)
            os.close(lifetime_fd)


if __name__ == '__main__':
    if sys.argv[1] == '--job':
        anchor(int(sys.argv[2]), sys.argv[3:])
    else:
        exit_code = supervise(int(sys.argv[1]), sys.argv[2:])
        if exit_code < 0:
            # Preserve Popen's negative return code for a signal-killed bridge.
            os.kill(os.getpid(), -exit_code)
        raise SystemExit(exit_code)
