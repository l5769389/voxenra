import sys
import threading
import time
import pytest


def test_external_process_unicode_path_and_events(tmp_path):
    from qt_dicom_viewer.infrastructure.local_inference_process import run_process
    script=tmp_path/'有 空格.py'
    script.write_text('print(\'VOXENRA_EVENT {"event":"stage","stage":"running"}\')\n')
    events=[]
    run_process([sys.executable,str(script)],tmp_path/'run.log',threading.Event(),events.append)
    assert events==[{'event':'stage','stage':'running'}]


def test_cancel_terminates_child_and_timeout(tmp_path):
    from qt_dicom_viewer.infrastructure.local_inference_process import run_process
    cancel=threading.Event()
    t=threading.Timer(.3,cancel.set);t.start()
    with pytest.raises(InterruptedError):
        run_process([sys.executable,'-c','import time; time.sleep(30)'],tmp_path/'run.log',cancel)
    t.join()
    with pytest.raises(TimeoutError):
        run_process([sys.executable,'-c','import time; time.sleep(30)'],tmp_path/'run.log',threading.Event(),timeout=.2)


def test_nonzero_exit_is_failure(tmp_path):
    from qt_dicom_viewer.infrastructure.local_inference_process import run_process
    with pytest.raises(RuntimeError):
        run_process([sys.executable,'-c','raise SystemExit(3)'],tmp_path/'run.log',threading.Event())


def test_cancel_terminates_real_descendant(tmp_path):
    from qt_dicom_viewer.infrastructure.local_inference_process import run_process
    pidfile=tmp_path/'child.pid'
    heartbeat=tmp_path/'heartbeat'
    child=f'import pathlib,time; p=pathlib.Path({str(heartbeat)!r});\nwhile True: p.write_text(str(time.monotonic()));time.sleep(.03)'
    parent=f'import subprocess,sys,pathlib,time; p=subprocess.Popen([sys.executable,"-c",{child!r}]);pathlib.Path({str(pidfile)!r}).write_text(str(p.pid));time.sleep(30)'
    cancel=threading.Event()
    def stop():
        deadline=time.monotonic()+5
        while not heartbeat.exists() and time.monotonic()<deadline:time.sleep(.03)
        cancel.set()
    t=threading.Thread(target=stop);t.start()
    with pytest.raises(InterruptedError):run_process([sys.executable,'-c',parent],tmp_path/'run.log',cancel)
    t.join();assert heartbeat.exists()
    stamp=heartbeat.read_text();time.sleep(.15)
    assert heartbeat.read_text()==stamp


def test_windows_parent_exit_still_closes_owned_job(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from qt_dicom_viewer.infrastructure import local_inference_process as runner
    from qt_dicom_viewer.infrastructure import windows_inference_job
    events=[]
    class Job:
        def __init__(self):events.append('create')
        def attach_and_resume(self,pid):events.append(('attach',pid))
        def close(self):events.append('close')
    class Process:
        pid=123
        def poll(self):return 0
        def wait(self,timeout=None):events.append('wait');return 0
        def kill(self):events.append('kill')
    def popen(*args,**kwargs):
        assert kwargs['creationflags'] & 4 # CREATE_SUSPENDED before ownership
        return Process()
    monkeypatch.setattr(runner,'os',SimpleNamespace(name='nt',environ={}))
    monkeypatch.setattr(runner.subprocess,'CREATE_NEW_PROCESS_GROUP',512,raising=False)
    monkeypatch.setattr(runner.subprocess,'CREATE_NO_WINDOW',0x08000000,raising=False)
    monkeypatch.setattr(runner.subprocess,'Popen',popen)
    monkeypatch.setattr(windows_inference_job,'WindowsInferenceJob',Job)
    runner.run_process(['python','bridge'],tmp_path/'run.log',threading.Event())
    assert events==['create',('attach',123),'close','wait']
