"""Opt-in full QML/picker audit of each public sample; never downloads data.

Set VOXPLANE_COMPRESSED_SAMPLE_DIR to the folder containing manifest.json.
Use QT_QPA_PLATFORM=cocoa on macOS for native-window verification.
"""
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
from pydicom import dcmread
from pydicom.pixels import pixel_array
from PySide6.QtGui import QImage
from PySide6.QtCore import QItemSelectionModel, QPoint, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from voxplane.ui.dialogs.local_import_dialog import LocalImportDialog
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import click, descendants, find

ROOT = Path(os.environ['VOXPLANE_COMPRESSED_SAMPLE_DIR']) if os.environ.get('VOXPLANE_COMPRESSED_SAMPLE_DIR') else None
CASES = json.loads((ROOT / 'manifest.json').read_text()) if ROOT else []
pytestmark = pytest.mark.skipif(ROOT is None, reason='Set VOXPLANE_COMPRESSED_SAMPLE_DIR')


def settle(milliseconds=180):
    end = time.monotonic() + milliseconds / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(.005)


def visible_text(window):
    return [str(item.property('text')) for item in descendants(window.contentItem())
            if item.isVisible() and item.property('text') is not None]


def save_window(window, path):
    settle()
    assert window.grabWindow().save(str(path))


def image_digest(app, viewport):
    image = app._image_provider._images[viewport.viewportId]
    assert not image.isNull()
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


@pytest.mark.parametrize('case', CASES, ids=[Path(c['file']).name for c in CASES])
def test_public_sample_local_picker_and_view(scene, case):
    window, app, warnings = scene
    window.resize(1400, 900)
    panel, workspace = app.panelController, app.workspaceController
    path = ROOT / case['file']
    output = Path(os.environ.get('VOXPLANE_SAMPLE_QA_OUTPUT', 'build/public-compressed-qa'))
    output.mkdir(parents=True, exist_ok=True)
    panel._last_import_directory = str(path.parent)
    errors = []

    def choose_file():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, LocalImportDialog)
            wait_until(lambda: dialog.model.index(str(path)).isValid())
            dialog.view.selectionModel().select(
                dialog.model.index(str(path)),
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
            )
            assert dialog.open_button.isEnabled()
            QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        except BaseException as error:
            errors.append(error)
            if dialog:
                dialog.reject()

    QTimer.singleShot(150, choose_file)
    click(window, find(window, 'homeOpenImport'))
    assert not errors, errors
    wait_until(lambda: not panel.scanning, 15000)
    result = dict(file=case['file'], syntax=case['syntax_name'],
                  import_message=panel.statusMessage, import_error=panel.importError,
                  import_dialog_open=panel.importTaskOpen, series_count=len(panel.seriesItems))
    if path.name == 'JPEGLSNearLossless_16.dcm':
        assert not panel.seriesItems and panel.importError and panel.importTaskOpen
        assert '未找到可用的 DICOM' in panel.statusMessage
        settle()
        popup = next(w for w in QApplication.topLevelWindows()
                     if w.isVisible() and hasattr(w, 'contentItem')
                     and any(i.objectName() == 'importTaskMessage' for i in descendants(w.contentItem())))
        assert panel.statusMessage in visible_text(popup)
        save_window(popup, output / (path.stem + '.png'))
        close = find(popup, 'importTaskClose')
        click(popup, close)
        assert not panel.importTaskOpen
        result['outcome'] = 'missing_metadata_rejected'
    else:
        assert len(panel.seriesItems) == 1 and not panel.importError
        assert not panel.importTaskOpen
        uid = panel.seriesItems[0]['seriesInstanceUid']
        click(window, find(window, 'series-' + uid))
        assert panel.activeSeriesUid == uid
        view_button = find(window, 'openView-2d')
        result['view_error'] = panel.seriesViewError(uid, '2d')
        if path.name.startswith('emri_small'):
            assert view_button.isEnabled()
            assert 'Enhanced MR 帧信息不完整' in result['view_error']
            # The sidebar double-click must create a visible error tab.
            row = find(window, 'series-' + uid)
            point = row.mapToScene(QPointF(row.width() * .7, row.height() / 2)).toPoint()
            QTest.mouseDClick(window, Qt.LeftButton, pos=point)
            wait_until(lambda: workspace.activeLoadState is not None and workspace.activeLoadState.status == 'error')
            settle()
            assert any(result['view_error'] in text for text in visible_text(window))
            assert not app.exportController.canExportPng
            assert not any(i.objectName() == 'retryWorkspaceLoad' and i.isVisible() for i in descendants(window.contentItem()))
            save_window(window, output / (path.stem + '-reason.png'))
            workspace.activeTab.toolController.activateTool('export')
            assert not find(window, 'exportPng').isEnabled()
            failed_tab = workspace.activeTabId
            click(window, find(window, 'cancelWorkspaceLoad'))
            assert failed_tab not in workspace._tab_dict
            result['outcome'] = 'incomplete_enhanced_mr_error_tab'
        else:
            assert view_button.isEnabled()
            click(window, view_button)
            wait_until(lambda: workspace.activeViewport is not None and
                       workspace.activeViewport.loadState in ('ready', 'error'), 15000)
            view = workspace.activeViewport
            result.update(state=view.loadState, error=view.errorMessage, slice_count=view.sliceCount)
            expected_error = '12 位精度' if path.name == 'JPEG-lossy.dcm' else ''
            if expected_error:
                assert view.loadState == 'error' and expected_error in view.errorMessage
                assert not view.imageSource and not view.render_pending
                assert not app.exportController.canExportPng
                assert '或导出 PNG' not in view.errorMessage
                settle()
                assert any(expected_error in text for text in visible_text(window))
                workspace.activeTab.toolController.activateTool('export')
                assert not find(window, 'exportPng').isEnabled()
                result['outcome'] = 'unsupported_precision'
            else:
                assert view.loadState == 'ready', view.errorMessage
                assert view.sliceCount == 1 and view.imageSource
                image = app._image_provider._images[view.viewportId]
                assert (image.height(), image.width()) == (case['rows'], case['columns'])
                before = image_digest(app, view)
                save_window(window, output / (path.stem + '-default.png'))
                if case['photometric'] == 'RGB':
                    rgb = image.convertToFormat(QImage.Format_RGB888)
                    rows = np.frombuffer(rgb.constBits(), dtype=np.uint8).reshape(rgb.height(), rgb.bytesPerLine())
                    displayed = rows[:, :3 * rgb.width()].reshape(rgb.height(), rgb.width(), 3)
                    np.testing.assert_array_equal(displayed, pixel_array(dcmread(path)))
                    result.update(outcome='ready_rgb', verified_rgb_pixels=True)
                else:
                    original = view.current_window
                    view.applyWindowPreset(original.center, max(original.width * .8, .001))
                    wait_until(lambda: not view.render_pending, 10000)
                    assert before != image_digest(app, view)
                    result.update(outcome='ready', window_changed=True)
                result['image_size'] = [image.width(), image.height()]
            assert not workspace.activeTab.playbackAvailable
            workspace.activeTab.setPlaying(True)
            assert not workspace.activeTab.playing
            save_window(window, output / (path.stem + '.png'))
        click(window, find(window, 'openView-tag'))
        wait_until(lambda: workspace.activeTab is not None and workspace.activeTab.tagController is not None)
        tag = workspace.activeTab.tagController
        wait_until(lambda: not tag.loading, 10000)
        assert not tag.errorMessage and tag.tagModel.rowCount() > 0
        find(window, 'tagList')
        result.update(tag_error=tag.errorMessage, tag_rows=tag.tagModel.rowCount())
        save_window(window, output / (path.stem + '-tag.png'))
    assert not warnings, warnings
    result['qml_warnings'] = warnings
    result['hash_unchanged'] = hashlib.sha256(path.read_bytes()).hexdigest() == case['sha256']
    assert result['hash_unchanged']
    (output / (path.stem + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
