"""Cancellable process-tree execution, with bounded diagnostics and structured events."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def terminate_tree(process):
    if os.name == 'nt':
        if process.poll() is None:
            subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        # Children may outlive an already exited parent.
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_process(command, log_path, cancel, on_event=lambda event: None, *, timeout=None):
    if cancel.is_set():
        raise InterruptedError()
    options = ({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 4}
               if os.name == 'nt' else {'start_new_session':True})
    environment=os.environ.copy()
    # A packaged Qt application may set these to its own Python/Qt runtime.
    for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH'):
        environment.pop(key,None)
    environment.update(PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8')
    started=time.monotonic()
    with open(log_path,'w',encoding='utf-8') as log:
        job = None
        lifetime_read = lifetime_write = None
        if os.name == 'nt':
            from .windows_inference_job import WindowsInferenceJob
            job = WindowsInferenceJob()
        else:
            helper = Path(__file__).with_name('posix_inference_supervisor.py')
            if not helper.is_file():
                raise FileNotFoundError('Inference process ownership resource is missing')
            lifetime_read, lifetime_write = os.pipe()
            options['pass_fds'] = (lifetime_read,)
            # sys.executable can be the frozen GUI; command[0] is external Python.
            command = [command[0], str(helper), str(lifetime_read), *command]
        try:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=environment,**options)
        except BaseException:
            if job:job.close()
            if lifetime_write is not None:os.close(lifetime_write)
            raise
        finally:
            if lifetime_read is not None:os.close(lifetime_read)
        pending=''
        try:
            if job:job.attach_and_resume(process.pid)
            with open(log_path,encoding='utf-8',errors='replace') as reader:
                while True:
                    chunk=reader.read(65536)
                    pending+=chunk
                    lines=pending.split('\n');pending=lines.pop()[-65536:]
                    for line in lines:
                        if line.startswith('VOXENRA_EVENT '):
                            try: on_event(json.loads(line[14:]))
                            except (ValueError,TypeError): pass
                    if cancel.is_set():
                        raise InterruptedError()
                    if timeout is not None and time.monotonic()-started > timeout:
                        raise TimeoutError('Environment check timed out')
                    code=process.poll()
                    if code is not None:
                        # Drain any final complete lines on the next pass.
                        remainder=reader.read()
                        for line in (pending+remainder).splitlines():
                            if line.startswith('VOXENRA_EVENT '):
                                try:on_event(json.loads(line[14:]))
                                except (ValueError,TypeError):pass
                        if code:
                            raise RuntimeError(f'Process exited with code {code}')
                        return
                    cancel.wait(.1)
        finally:
            if job:
                job.close()  # Kills descendants even after the bridge has exited.
                if process.poll() is None:process.kill()  # Also covers failed assignment.
                process.wait()
            else:
                # EOF is observed independently of the GUI's lifetime. The
                # supervisor owns signalling/reaping its anchored job group.
                os.close(lifetime_write)
                process.wait(timeout=10)
