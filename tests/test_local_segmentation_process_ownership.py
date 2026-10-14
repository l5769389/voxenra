"""Real, bounded POSIX trees catch loss of ownership after GUI-owner death."""
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX ownership protocol')


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    assert predicate(), 'Synthetic process did not reach the expected state'


def synthetic_tree(tmp_path, mode):
    """Two descendant generations ignore TERM; every process has a hard limit."""
    script = tmp_path / 'synthetic tree.py'
    script.write_text('''import json, os, pathlib, signal, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
role = int(sys.argv[2])
mode = sys.argv[3]
signal.signal(signal.SIGTERM, signal.SIG_IGN)
(root / (str(role) + '.pid')).write_text(json.dumps([os.getpid(), os.getpgrp()]))
child = subprocess.Popen([sys.executable, __file__, str(root), str(role + 1), mode]) if role < 2 else None
deadline = time.monotonic() + 12
while time.monotonic() < deadline:
    (root / (str(role) + '.beat')).write_text(str(time.monotonic()))
    if role == 0 and mode in ('success', 'nonzero') and (root / '2.beat').exists():
        raise SystemExit(0 if mode == 'success' else 7)
    time.sleep(.03)
''')
    return [sys.executable, str(script), str(tmp_path), '0', mode]


def assert_tree_stopped(tmp_path):
    # Allow the supervisor's bounded TERM/KILL grace period, then require stability.
    time.sleep(1.5)
    stamps = [(tmp_path / (str(role) + '.beat')).read_text() for role in range(3)]
    time.sleep(.2)
    assert [(tmp_path / (str(role) + '.beat')).read_text() for role in range(3)] == stamps


def cleanup_synthetic_tree(tmp_path):
    # Only kill a group while one of our bounded workers still anchors it.
    for path in tmp_path.glob('*.pid'):
        pid, group = json.loads(path.read_text())
        try:
            if os.getpgid(pid) == group:
                os.killpg(group, signal.SIGKILL)
                return
        except ProcessLookupError:
            pass


def test_sigkill_owner_stops_real_descendant_tree(tmp_path):
    command = synthetic_tree(tmp_path, 'crash')
    owner_script = tmp_path / 'owner.py'
    owner_script.write_text(
        'import sys, threading\n'
        f'sys.path.insert(0, {str(ROOT / "src")!r})\n'
        'from qt_dicom_viewer.infrastructure.local_inference_process import run_process\n'
        f'run_process({command!r}, {str(tmp_path / "run.log")!r}, threading.Event())\n')
    owner = subprocess.Popen([sys.executable, str(owner_script)])
    try:
        wait_for(lambda: (tmp_path / '2.beat').exists())
        owner.kill()
        assert owner.wait(timeout=5) == -signal.SIGKILL
        assert_tree_stopped(tmp_path)
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        cleanup_synthetic_tree(tmp_path)


@pytest.mark.parametrize('mode', ['cancel', 'timeout', 'success', 'nonzero'])
def test_normal_completion_stops_real_descendant_tree(tmp_path, mode):
    from qt_dicom_viewer.infrastructure.local_inference_process import run_process
    command = synthetic_tree(tmp_path, mode)
    cancel = threading.Event()
    timer = None
    if mode == 'cancel':
        def stop():
            wait_for(lambda: (tmp_path / '2.beat').exists())
            cancel.set()
        timer = threading.Thread(target=stop)
        timer.start()
    try:
        expected = {'cancel': InterruptedError, 'timeout': TimeoutError, 'nonzero': RuntimeError}.get(mode)
        if expected:
            with pytest.raises(expected):
                run_process(command, tmp_path / 'run.log', cancel, timeout=.8 if mode == 'timeout' else None)
        else:
            run_process(command, tmp_path / 'run.log', cancel)
        assert (tmp_path / '2.beat').exists()
        assert_tree_stopped(tmp_path)
    finally:
        if timer:
            timer.join(timeout=5)
        cleanup_synthetic_tree(tmp_path)


def test_packaged_ownership_helper_executes_with_external_python(tmp_path):
    hook = runpy.run_path(str(ROOT / 'packaging/hooks/hook-qt_dicom_viewer.py'))
    resources = [Path(source) for source, target in hook['datas']
                 if Path(source).name == 'posix_inference_supervisor.py'
                 and target == 'qt_dicom_viewer/infrastructure']
    assert len(resources) == 1, 'Ownership helper must be an external-Python bundle resource'
    # No application imports: execute the bundled script after moving it away from src.
    helper = tmp_path / resources[0].name
    helper.write_bytes(resources[0].read_bytes())
    read_fd, write_fd = os.pipe()
    try:
        process = subprocess.Popen([sys.executable, str(helper), str(read_fd),
                                    sys.executable, '-c', 'print("resource works")'],
                                   pass_fds=(read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate(timeout=5)
        assert process.returncode == 0, err.decode()
        assert out == b'resource works\n'
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_configured_interpreter_works_with_frozen_gui_environment(tmp_path, monkeypatch):
    from qt_dicom_viewer.infrastructure.local_inference_process import run_process
    external_python = sys.executable
    polluted = ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH')
    for key in polluted:
        monkeypatch.setenv(key, str(tmp_path / 'bundled GUI runtime'))
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'frozen GUI executable'))
    events = []
    script = ('import json, os; print("VOXENRA_EVENT " + json.dumps('
              '{"event": "environment", "pollution": {key: os.environ[key] '
              f'for key in {polluted!r} if key in os.environ}}}}))')
    run_process([external_python, '-c', script], tmp_path / 'run.log', threading.Event(), events.append)
    assert events == [{'event': 'environment', 'pollution': {}}]
