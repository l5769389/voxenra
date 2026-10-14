from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import QObject
from test_mpr_voi_controller import setup_voi
from test_measurement_qml import qt_app
from qt_dicom_viewer.model import PixelValueMeta
from qt_dicom_viewer.core.segmentation_masks import mask_record
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController

@pytest.fixture
def integrated(setup_voi,tmp_path):
    from qt_dicom_viewer.ui.controller.local_segmentation_controller import LocalSegmentationController
    voi,view,tools=setup_voi
    volume=replace(view._voi_volume,pixel_value_meta=PixelValueMeta(unit='HU'),fingerprint='source')
    view._voi_volume=volume;voi.set_source(volume)
    tab=QObject();tab.activeViewport=view;tab._voi_controller=voi
    tab.tab_config=SimpleNamespace(tab_type='mpr')
    series=SimpleNamespace(modality='CT',series_description='CT example',instances=(),phases=())
    settings=SettingsController(path=tmp_path/'settings.json')
    controller=LocalSegmentationController(settings,SimpleNamespace(get_series=lambda uid:series),cache=tmp_path/'jobs')
    yield controller,tab,voi,volume,settings
    controller.shutdown()


def payload(c,v):
    m=np.ones((2,3,4),bool)
    r,e=mask_record(v,m,(0,0,0),name='liver')
    return [r],{r['id']:e},[]


def test_pending_phase_and_edit_do_not_import_until_original_target_ready(integrated):
    c,tab,voi,v,_=integrated
    assert c.prepare(tab)
    c._pending=payload(c,v);c._state='pending'
    voi.set_phase(1);c._poll_target();assert not voi.records and c.busy
    voi.set_phase(None);voi.set_source(v)
    voi._draft={'test':True};c._poll_target();assert not voi.records
    voi._draft=None;c._poll_target()
    assert len(voi.records)==1 and c.state=='done', c.message


def test_changed_volume_never_accepts_pending_result(integrated):
    c,tab,voi,v,_=integrated
    assert c.prepare(tab)
    c._pending=payload(c,v);c._state='pending'
    voi.set_source(replace(v,fingerprint='different'))
    c._poll_target()
    assert not voi.records and c.state=='error'


def test_settings_roundtrip_and_invalid_options(integrated):
    c,tab,voi,v,s=integrated
    s.setValue('services','segmentationPython','/tmp/有 空格/python')
    s.setValue('services','segmentationOrgans',['liver','spleen'])
    restored=SettingsController(path=s._path)
    assert restored.values['services']['segmentationPython']=='/tmp/有 空格/python'
    assert restored.values['services']['segmentationOrgans']==['liver','spleen']
    assert not s.setValue('services','segmentationDevice','invalid')


def test_pending_cancel_and_closed_target_never_mutate(integrated):
    c,tab,voi,v,_=integrated
    c.prepare(tab);c._pending=payload(c,v);c._state='pending'
    c.cancel();c._poll_target()
    assert not voi.records and c.state=='cancelled'
    c.prepare(tab);c._pending=payload(c,v);c._state='pending';voi._closed=True
    c._poll_target()
    assert not voi.records and c.state=='error'


def test_batch_import_one_undo_and_original_mask_preserved(integrated):
    from qt_dicom_viewer.ui.controller.edit_history_controller import EditHistoryController
    from PySide6.QtTest import QTest
    c,tab,voi,v,_=integrated
    tab.viewports_by_id={}
    history=EditHistoryController(tab)
    original=payload(c,v);voi.add_masks(original[0],original[1]);history.capture()
    original_id=voi.records[0]['id']
    c.prepare(tab);a=payload(c,v);b=payload(c,v)
    c._pending=(a[0]+b[0],dict(a[1],**b[1]),[]);c._state='pending';c._poll_target();history.capture()
    assert len(voi.records)==3 and len({r['color'] for r in voi.records})==3
    history.undo();assert [r['id'] for r in voi.records]==[original_id]
    history.redo();assert len(voi.records)==3
    history.dispose()


def test_changed_configuration_rejects_inflight_probe(integrated):
    c,tab,voi,v,s=integrated
    c._checked_config=c._configuration()
    c._state='checking'
    s.setValue('services','segmentationWeights','/tmp/other weights')
    c._receive((c._epoch,'probe',{'protocol':1,'model_ready':True,'organs':['liver'],'devices':['cpu']},None,''))
    assert not c.ready and c.state=='error'


def test_destroyed_target_releases_volume(integrated):
    from PySide6.QtCore import QCoreApplication,QEvent
    c,tab,voi,v,s=integrated
    assert c.prepare(tab)
    tab.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    assert c._target is None


def test_diagnostic_write_failure_still_cleans_source_files(integrated,monkeypatch):
    import time
    from pathlib import Path
    from PySide6.QtTest import QTest
    import qt_dicom_viewer.ui.controller.local_segmentation_controller as module
    c,tab,voi,v,s=integrated
    c.prepare(tab)
    def fake_run(command,log,cancel,*args,**kwargs):
        log.write_text('failed inference')
        raise RuntimeError('inference failed')
    original=Path.write_text
    def no_log(path,*args,**kwargs):
        if path.name=='last-run.log':raise OSError('disk full')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(module,'run_process',fake_run)
    monkeypatch.setattr(Path,'write_text',no_log)
    c._start('prepare','run',{},'python')
    deadline=time.monotonic()+5
    while c.busy and time.monotonic()<deadline:QTest.qWait(20)
    assert not list(c._cache.glob('job-*'))
    assert c.state=='error' and 'inference failed' in c.message


def test_missing_environment_and_incomplete_model_are_actionable(integrated):
    c,tab,voi,v,s=integrated
    s.setValue('services','segmentationPython','/no/such/python')
    c.checkEnvironment();assert c.state=='error' and not c.ready
    c._checked_config=c._configuration()
    c._receive((c._epoch,'probe',{'protocol':1,'model_ready':False,'organs':['liver'],'devices':['cpu'],'version':'2.18.0'},None,''))
    assert not c.ready and c.state=='error' and c.environment['version']=='2.18.0'


def test_bridge_dependency_error_reaches_user(integrated,monkeypatch):
    import time
    from PySide6.QtTest import QTest
    import qt_dicom_viewer.ui.controller.local_segmentation_controller as module
    c,tab,voi,v,s=integrated
    def fake_run(command,log,cancel,receive,**kwargs):
        receive({'event':'error','reason':"No module named 'torch'"})
        raise RuntimeError('Process exited with code 1')
    monkeypatch.setattr(module,'run_process',fake_run)
    c._start('checking','probe',{},'python')
    deadline=time.monotonic()+5
    while c.busy and time.monotonic()<deadline:QTest.qWait(20)
    assert 'torch' in c.message


def test_startup_cleanup_never_removes_running_old_job(integrated):
    import os,time
    from PySide6.QtCore import QLockFile
    c,tab,voi,v,s=integrated
    root=c._cache/'job-active';root.mkdir()
    lock=QLockFile(str(root/'owner.lock'));assert lock.tryLock(0)
    try:
        (root/'source.nrrd').write_text('active input')
        os.utime(root/'owner.lock',(time.time()-600,time.time()-600))
        c._cleanup_stale()
        assert (root/'source.nrrd').exists()
    finally:
        lock.unlock()


def test_duplicate_start_and_stale_completion_are_ignored(integrated,monkeypatch):
    import time
    from PySide6.QtTest import QTest
    import qt_dicom_viewer.ui.controller.local_segmentation_controller as module
    c,tab,voi,v,s=integrated
    c.prepare(tab);c._checked_config=c._configuration()
    c._environment={'model_ready':True,'devices':['cpu'],'organs':['liver']}
    s.setValue('services','segmentationOrgans',['liver'])
    def blocked(command,log,cancel,*args,**kwargs):
        cancel.wait(5)
        raise InterruptedError()
    monkeypatch.setattr(module,'run_process',blocked)
    c.start();epoch=c._epoch;c.start()
    assert c._epoch==epoch
    c._receive((epoch-1,'run',payload(c,v),None,''))
    assert not voi.records
    c.cancel()
    deadline=time.monotonic()+5
    while c.busy and time.monotonic()<deadline:QTest.qWait(20)
    assert c.state=='cancelled' and not voi.records


def test_unavailable_saved_device_is_preserved_and_explicit(integrated):
    c,tab,voi,v,s=integrated
    c._checked_config=c._configuration()
    c._environment={'model_ready':True,'devices':['cpu'],'organs':['liver']}
    s.setValue('services','segmentationDevice','gpu')
    assert 'gpu' in c.devices
    assert not c.deviceAvailable
    assert s.values['services']['segmentationDevice']=='gpu'


def test_inference_cancel_does_not_change_environment_status(integrated):
    c,tab,voi,v,s=integrated
    c._checked_config=c._configuration()
    c._receive((c._epoch,'probe',{'protocol':1,'model_ready':True,'organs':['liver'],'devices':['cpu'],'version':'2.18.0'},None,''))
    status=c.environmentMessage
    c._state='pending';c.cancel()
    assert c.environmentMessage==status and c.environmentState=='ready'
    s.setValue('services','segmentationWeights','/new/path')
    assert c.environmentState=='idle' and not c.ready


def test_explicit_missing_python_never_falls_back_to_discovery(integrated):
    c,tab,voi,v,s=integrated
    s.setValue('services','segmentationPython','/missing/explicit/python')
    assert c._configuration()[0]=='/missing/explicit/python'
    c.checkEnvironment()
    assert c.environmentState=='error' and not c.ready


def test_python_picker_preserves_virtual_environment_symlink(integrated,monkeypatch,tmp_path):
    import qt_dicom_viewer.ui.controller.local_segmentation_controller as module
    from PySide6.QtWidgets import QFileDialog
    c,tab,voi,v,s=integrated
    actual=tmp_path/'base-python';actual.touch()
    link=tmp_path/'venv/bin/python';link.parent.mkdir(parents=True);link.symlink_to(actual)
    def picker(*args,**kwargs):
        # Model Qt's path resolution contract; the native GUI is also checked separately.
        path=link if kwargs.get('options',QFileDialog.Option(0)) & QFileDialog.DontResolveSymlinks else link.resolve()
        return str(path),''
    monkeypatch.setattr(module.QFileDialog,'getOpenFileName',picker)
    c.choosePython()
    assert s.values['services']['segmentationPython']==str(link)


def probe_result(**changes):
    return dict(protocol=1, model_ready=True, organs=['liver'], devices=['cpu'],
                version='2.18.0', model_issues=[]) | changes


@pytest.mark.parametrize('result', [
    None, [], 'ready', {},
    probe_result(protocol=True), probe_result(protocol='1'),
    probe_result(model_ready='false'), probe_result(model_ready=None),
    probe_result(organs='liver'), probe_result(organs=[{}]), probe_result(organs=['']),
    probe_result(organs=['liver', 'liver']), probe_result(organs=[]),
    probe_result(devices='cpu'), probe_result(devices=[{}]), probe_result(devices=['unknown']),
    probe_result(devices=[]), probe_result(version=[]), probe_result(model_issues='missing'),
])
def test_malformed_probe_is_terminal_and_clears_stale_readiness(integrated, result):
    c, tab, voi, volume, settings = integrated
    c._checked_config = c._configuration()
    c._environment = probe_result()
    c._state = c._environment_state = 'checking'
    c._receive((c._epoch, 'probe', result, None, 'probe diagnostics'))
    assert c.state == c.environmentState == 'error'
    assert not c.busy and not c.ready and c.environment == {}
    assert c.message and c.environmentMessage and c.logs == 'probe diagnostics'
    assert c.organs == [] and c.devices == ['auto']


@pytest.mark.parametrize('event', [None, [], {}, {'event': []},
    {'event': 'stage'}, {'event': 'stage', 'stage': []},
    {'event': 'error', 'reason': {}}, {'event': 'error', 'reason': ''}])
def test_malformed_bridge_event_is_actionable_and_environment_retry_succeeds(integrated, monkeypatch, event):
    import json
    import sys
    from pathlib import Path
    from test_dicom_tags import wait_until
    import qt_dicom_viewer.ui.controller.local_segmentation_controller as module
    c, tab, voi, volume, settings = integrated
    settings.setValue('services', 'segmentationPython', sys.executable)
    response = {'event': event}
    def bridge(command, log, cancel, receive, **kwargs):
        if 'event' in response:
            receive(response['event'])
        (Path(command[-1]) / 'result.json').write_text(json.dumps(probe_result()))
    monkeypatch.setattr(module, 'run_process', bridge)
    c.checkEnvironment()
    wait_until(lambda: not c.busy)
    assert c.state == c.environmentState == 'error' and not c.ready
    assert c.message and c.environmentMessage
    assert not list(c._cache.glob('job-*'))
    response.clear()
    c.checkEnvironment()
    wait_until(lambda: not c.busy)
    assert c.state == c.environmentState == 'ready' and c.ready
    assert c.organs[0]['id'] == 'liver' and c.devices == ['auto', 'cpu']


def test_malformed_probe_ignores_stale_epoch_and_cancel_wins(integrated):
    c, tab, voi, volume, settings = integrated
    c._checked_config = c._configuration()
    c._state = c._environment_state = 'checking'
    c._receive((c._epoch - 1, 'probe', None, None, 'stale'))
    assert c.state == 'checking' and c.logs == ''
    c.cancel()
    c._receive((c._epoch, 'probe', [], None, 'cancelled'))
    assert c.state == 'cancelled' and c.environmentState == 'idle' and not c.busy


@pytest.mark.parametrize('response', [
    {'result': []}, {'result': None},
    {'event': [], 'result': probe_result()},
    {'event': {'event': 'stage'}, 'result': probe_result()},
    {'event': {'event': 'error', 'reason': 'service failure'}, 'result': probe_result()},
])
def test_external_probe_failure_is_terminal_and_retry_recovers(integrated, monkeypatch, tmp_path, response):
    import json
    import sys
    from test_dicom_tags import wait_until
    import qt_dicom_viewer.ui.controller.local_segmentation_controller as module
    c, tab, voi, volume, settings = integrated
    script = tmp_path / 'fake_bridge.py'
    script.write_text("""import json, sys
from pathlib import Path
root = Path(sys.argv[1])
response = json.loads(Path(sys.argv[2]).read_text())
if 'event' in response:
    print('VOXENRA_EVENT ' + json.dumps(response['event']), flush=True)
(root / 'result.json').write_text(json.dumps(response['result']))
""")
    control = tmp_path / 'response.json'
    control.write_text(json.dumps(response))
    real_run = module.run_process
    def external_probe(command, log, cancel, receive, **kwargs):
        return real_run([sys.executable, str(script), command[-1], str(control)], log, cancel, receive, **kwargs)
    monkeypatch.setattr(module, 'run_process', external_probe)
    settings.setValue('services', 'segmentationPython', sys.executable)
    c.checkEnvironment()
    wait_until(lambda: not c.busy)
    assert c.state == c.environmentState == 'error' and not c.ready
    assert c.message and c.environmentMessage
    event = response.get('event')
    if isinstance(event, dict) and event.get('event') == 'error':
        assert 'service failure' in c.message
    assert not list(c._cache.glob('job-*'))
    control.write_text(json.dumps({'result': probe_result()}))
    c.checkEnvironment()
    wait_until(lambda: not c.busy)
    assert c.state == c.environmentState == 'ready' and c.ready
