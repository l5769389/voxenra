"""File-manager dispatch uses local paths and never opens an export as a document."""
from types import SimpleNamespace
from pathlib import Path

import pytest

from voxplane.ui import file_location
from voxplane.ui.controller.export_controller import ExportController
from voxplane.ui.controller.measurement_report_controller import MeasurementReportController
from test_dicom_tags import qt_app


@pytest.mark.parametrize('platform', ['darwin', 'win32', 'linux'])
def test_reveal_file_and_folder_with_spaces_unicode_and_metacharacters(qt_app, tmp_path, monkeypatch, platform):
    target = tmp_path / '结果 空格, & $(test).csv'
    target.write_text('result')
    calls, urls = [], []
    monkeypatch.setattr(file_location, 'sys', SimpleNamespace(platform=platform))
    monkeypatch.setattr(file_location.QDir, 'toNativeSeparators', lambda path: path.replace('/', '\\'))
    monkeypatch.setattr(file_location.QProcess, 'startDetached', lambda program, args: (calls.append((program, args)) or True, 123))
    monkeypatch.setattr(file_location.QDesktopServices, 'openUrl', lambda url: urls.append(Path(url.toLocalFile())) or True)
    assert file_location.reveal_path(str(target))
    if platform == 'darwin':
        assert calls == [('/usr/bin/open', ['-R', str(target)])]
    elif platform == 'win32':
        assert calls == [('explorer.exe', ['/select,', str(target).replace('/', '\\')])]
    else:
        assert not calls and urls == [tmp_path]
    calls.clear(); urls.clear()
    assert file_location.reveal_path(str(tmp_path))
    assert not calls and urls == [tmp_path]
    urls.clear()
    assert not file_location.reveal_path('')
    assert not file_location.reveal_path(str(tmp_path / 'missing'))
    assert not calls and not urls


@pytest.mark.parametrize('kind', [ExportController, MeasurementReportController])
def test_result_link_lifecycle_and_missing_file_feedback(qt_app, tmp_path, monkeypatch, kind):
    module = __import__(kind.__module__, fromlist=['reveal_path'])
    calls = []
    monkeypatch.setattr(module, 'reveal_path', lambda path: calls.append(path) or True)
    controller = kind(None, None)
    path = str(tmp_path / 'result.png')
    try:
        controller._finish('完成', False, path)
        assert controller.resultPath == path
        assert controller.openResultLocation() and calls == [path]
        monkeypatch.setattr(module, 'reveal_path', lambda path: False)
        assert not controller.openResultLocation()
        assert controller.isError and '移动或删除' in controller.message
        controller._finish('失败', True, path)
        assert controller.resultPath == ''
        controller._finish('已取消', False)
        assert controller.resultPath == ''
    finally:
        controller.shutdown()


def test_native_reveal_failure_returns_false(qt_app, tmp_path, monkeypatch):
    target = tmp_path / 'result.png'
    target.touch()
    monkeypatch.setattr(file_location, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(file_location.QProcess, 'startDetached', lambda *args: (False, 0))
    assert not file_location.reveal_path(str(target))
