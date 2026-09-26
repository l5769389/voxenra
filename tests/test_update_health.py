import json
from pathlib import Path

from test_dicom_tags import qt_app, wait_until
from qt_dicom_viewer.infrastructure import update_health


def manifest_at(tmp_path, executable, version='1.7.0'):
    manifest = tmp_path/'health.json'
    manifest.write_text(json.dumps(dict(token='a'*32, executable=str(executable), version=version)))
    return manifest


def test_confirmation_requires_matching_version_and_executable(qt_app, tmp_path):
    executable = tmp_path/'Voxenra'
    executable.touch()
    manifest = manifest_at(tmp_path, executable)
    assert not update_health.acknowledge_startup(manifest, executable=executable, version='1.6.0')
    assert not update_health.acknowledge_startup(manifest, executable=tmp_path/'other', version='1.7.0')
    assert not (tmp_path/'ready').exists()
    assert update_health.acknowledge_startup(manifest, executable=executable, version='1.7.0')
    assert (tmp_path/'ready').read_text() == 'a'*32


def test_confirmation_runs_only_after_visible_window_event_loop(qt_app, tmp_path, monkeypatch):
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    window=QQuickWindow()
    called=[]
    monkeypatch.setattr(update_health, 'STARTUP_STABILITY_MS', 20)
    monkeypatch.setattr(update_health, 'acknowledge_startup', lambda path: called.append(path))
    args=['Voxenra', update_health.CHECK_ARGUMENT, str(tmp_path/'health.json')]
    update_health.arm_startup_confirmation(window,args)
    QTest.qWait(40)
    assert not called
    window.show()
    wait_until(window.isExposed)
    update_health.arm_startup_confirmation(window,args)
    assert not called
    wait_until(lambda:bool(called))
    window.close()
    assert called == [args[-1]]
