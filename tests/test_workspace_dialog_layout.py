"""Stable native workspace controls, contextual history and readable hover windows."""
import os
import sys

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_workspace_persistence import draw_length
from qt_pointer import move_pointer


def workspace_dialog(window):
    QTest.qWait(80)
    click(window, find(window, 'sidebarWorkspace'))
    dialog = window.findChild(QObject, 'workspaceDocumentDialog')
    wait_until(lambda: dialog.property('visible'))
    native = dialog.findChild(QObject, 'workspaceDocumentMessage').window()
    return dialog, native


def geometry(item):
    p = item.mapToScene(QPointF())
    return p.x(), p.y(), item.width(), item.height()


def test_compact_workspace_save_and_manual_preserve_work(sidebar_scene, tmp_path, monkeypatch):
    window, app, records, warnings = sidebar_scene
    window.resize(1000, 600)
    ws, manager = app.workspaceController, app.workspaceDocumentController
    manager._autosave.stop()
    ws.createTab(records[0].series_instance_uid, '2D', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    draw_length(tab.activeViewport)
    dialog, native = workspace_dialog(window)
    QTest.qWait(80)
    child = lambda name: dialog.findChild(QObject, name)
    save, save_as, open_button = [child(name) for name in ('saveWorkspace', 'saveWorkspaceAs', 'openWorkspace')]
    assert dialog.property('width') == 460 and dialog.property('height') == 300
    assert save.isVisible() and open_button.isVisible() and not save_as.isVisible()
    assert save.property('text') == '保存工作区…'
    for name in ('workspaceRecoveryLocation', 'workspaceManualLink', 'saveWorkspace', 'openWorkspace'):
        assert not child(name).property('contentItem').property('truncated'), name
    initial = native.geometry(), geometry(save), geometry(open_button)
    assert native.grabWindow().save(str(tmp_path / 'workspace-temporary.png'))
    target = tmp_path / '复查计划.voxworkspace'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.workspace_document_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(target), ''))
    click(native, save)
    wait_until(lambda: not manager.busy)
    QTest.qWait(80)
    assert target.is_file() and not manager.isError and not manager.dirty
    assert child('workspaceName').property('text') == '复查计划'
    assert child('workspaceSaveState').property('text') == '已保存'
    assert save.property('text') == '保存更改' and save_as.isVisible()
    assert (native.geometry(), geometry(save), geometry(open_button)) == initial
    assert native.grabWindow().save(str(tmp_path / 'workspace-saved.png'))
    click(native, child('workspaceManualLink'))
    wait_until(lambda: not dialog.property('visible') and ws.activeTabType == 'manual')
    assert ws.manualController.chapterId == 'workspace'
    ws.activateTabId(tab.tab_config.tab_id)
    wait_until(lambda: ws.activeTab is tab)
    assert len(tab.activeViewport._measure_controller._measurements) == 1
    assert manager.path == str(target)
    assert not warnings, warnings


@pytest.mark.parametrize('size', [(1000, 600), (1400, 900)])
def test_workspace_geometry_is_stable_across_progress_errors_and_recovery(sidebar_scene, tmp_path, size):
    window, app, _, warnings = sidebar_scene
    window.resize(*size)
    manager = app.workspaceDocumentController
    manager._autosave.stop()
    dialog, native = workspace_dialog(window)
    assert native is not window and not native.flags() & Qt.FramelessWindowHint
    assert dialog.findChild(QObject, 'workspaceDocumentDialogClose') is None
    assert dialog.findChild(QObject, 'undoWorkspaceEdit') is None
    assert dialog.findChild(QObject, 'redoWorkspaceEdit') is None
    objects = [dialog.findChild(QObject, name) for name in (
        'workspaceDocumentPath', 'workspaceRecoveryArea', 'workspaceDocumentMessageArea',
        'openWorkspace', 'saveWorkspaceAs', 'saveWorkspace')]
    QTest.qWait(80)
    def snapshot():
        return (native.geometry(), dialog.property('width'), dialog.property('height'), [geometry(i) for i in objects])
    initial = snapshot()
    previous = manager._recovery_path, manager._previous_recovery, manager._autosave_enabled
    manager._recovery_path = tmp_path / 'recovery.voxworkspace'
    manager._recovery_path.touch()
    manager._autosave_enabled = True
    try:
        scenarios = [
            (True, False, False, False, False, '正在保存…'),
            (False, False, False, False, False, '工作区已保存。'),
            (False, False, False, True, False, '发现恢复副本。'),
            (True, True, False, True, False, '正在恢复页签 12 / 100…'),
            (False, False, True, True, False, '读取失败：' + '长路径/错误说明/中文名字/' * 180),
            (False, False, False, True, True, '部分影像缺失或几何信息不一致。'),
        ]
        for busy, restoring, error, recovery, missing, message in scenarios:
            manager._busy, manager._restoring, manager._error = busy, restoring, error
            manager._previous_recovery = recovery
            manager._pending = {'missing': ['series']} if missing else None
            manager._path = '/很长的工作区目录/' * 60 + '复查.voxworkspace'
            manager._message = message
            manager.changed.emit()
            QTest.qWait(70)
            if restoring:
                # Recovery runs with the popup closed; hidden items may relayout.
                assert not dialog.property('visible')
                continue
            assert dialog.property('visible')
            assert snapshot() == initial
            assert not dialog.findChild(QObject, 'cancelWorkspaceRestore').isVisible()
            assert objects[-1].isEnabled() == (not busy)
            if busy:
                assert not native.close()
                QTest.keyClick(native, Qt.Key_Escape)
                assert dialog.property('visible')
        assert native.grabWindow().save(str(tmp_path / 'workspace-missing-sources.png'))
        manager._busy = manager._restoring = manager._error = False
        manager._pending = None
        manager._previous_recovery = False
        manager._path = ''
        manager._message = ''
        manager.changed.emit()
        QTest.qWait(80)
        assert native.grabWindow().save(str(tmp_path / 'workspace-clean-layout.png'))
        assert native.close()
        wait_until(lambda: not dialog.property('visible'))
        # Unrelated edits must not reopen a dismissed error on every changed signal.
        manager._error = True
        manager.changed.emit()
        wait_until(lambda: dialog.property('visible'))
        assert native.close()
        manager.mark_dirty()
        QTest.qWait(40)
        assert not dialog.property('visible')
    finally:
        manager._busy = manager._restoring = manager._error = False
        manager._pending = None
        manager._recovery_path, manager._previous_recovery, manager._autosave_enabled = previous
        manager.changed.emit()
        native.close()
    assert not warnings, warnings


def test_history_shortcuts_stay_in_image_and_do_not_edit_behind_workspace(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '2D', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    draw_length(tab.activeViewport)
    tab.historyController.capture()
    assert tab.historyController.canUndo
    dialog, native = workspace_dialog(window)
    QTest.keyClick(native, Qt.Key_Z, Qt.ControlModifier)
    assert len(tab.activeViewport._measure_controller._measurements) == 1
    assert native.close()
    wait_until(lambda: not dialog.property('visible'))
    window.requestActivate()
    # Popup.Window closes and restores its parent's focus asynchronously.
    # Send the shortcut only after that transition completes, also on offscreen QPA.
    wait_until(lambda: window.isActive() and window.activeFocusItem() is not None
               and not window.property('editingText'))
    QTest.keyClick(window, Qt.Key_Z, Qt.ControlModifier)
    wait_until(lambda: not tab.activeViewport._measure_controller._measurements)
    modifier = Qt.ControlModifier | Qt.ShiftModifier if sys.platform == 'darwin' else Qt.ControlModifier
    QTest.keyClick(window, Qt.Key_Z if sys.platform == 'darwin' else Qt.Key_Y, modifier)
    wait_until(lambda: len(tab.activeViewport._measure_controller._measurements) == 1)
    assert not warnings, warnings


@pytest.mark.parametrize('theme, foreground, surface', [
    ('dark', '#edf1f5', '#29333e'), ('light', '#142235', '#f8fbfd'),
])
def test_export_hover_is_opaque_high_contrast_and_wraps_long_paths(sidebar_scene, tmp_path, theme, foreground, surface):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    parent_flags = window.flags()
    window.resize(1000, 600)
    app.settingsController.setValue('layout', 'rightPanelWidth', 220)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '2D', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    ws.activeTab.toolController.activateTool('export')
    link = find(window, 'exportManualLink')
    wait_until(link.isVisible)
    QTest.qWait(80)
    tip = next(child for child in link.children() if child.metaObject().className().startswith('AppToolTip')
               and child.property('text') == link.property('tooltipText'))
    move_pointer(window, window.contentItem().mapToScene(QPointF(800, 30)).toPoint())
    for name, text in [('manual', link.property('tooltipText')),
                       ('long-path', '在文件资源管理器中显示\n' + '/很长的导出路径 &' * 20 + '/结果.csv')]:
        link.setProperty('tooltipText', text)
        point = link.mapToScene(QPointF(link.width()/2, link.height()/2)).toPoint()
        move_pointer(window, point)
        assert link.property('hovered'), (name, geometry(link), window.width(), window.height())
        wait_until(lambda: tip.property('visible'))
        QTest.qWait(80)
        label = tip.property('contentItem')
        background = tip.property('background')
        assert label.property('color').name() == foreground
        assert background.property('color').name() == surface
        assert background.property('color').alpha() == 255
        assert background.property('opacity') == 1
        assert tip.property('width') <= 360
        assert label.property('lineCount') >= (2 if name == 'long-path' else 1)
        assert label.property('height') <= tip.property('height') - 20
        popup = label.window()
        assert popup is not window
        assert popup.flags() & Qt.FramelessWindowHint
        assert popup.flags() & Qt.WindowDoesNotAcceptFocus
        assert popup.flags() & Qt.WindowTransparentForInput
        assert window.flags() == parent_flags
        assert popup.grabWindow().save(str(tmp_path / ('tooltip-' + name + '.png')))
        move_pointer(window, window.contentItem().mapToScene(QPointF(800, 30)).toPoint())
        wait_until(lambda: not tip.property('visible'))
        assert window.flags() == parent_flags
    assert not warnings, warnings


@pytest.mark.skipif(os.environ.get('VOXENRA_NATIVE_QA') != '1' or sys.platform not in ('darwin', 'win32'), reason='Requires native caption and VTK windows')
def test_workspace_native_close_and_save_stays_above_volume(sidebar_scene, tmp_path, monkeypatch):
    from test_import_dialog_chrome import caption_close
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '3D', '3d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    view = ws.activeViewport
    wait_until(lambda: view._host is not None and view._host.isVisible())
    dialog, native = workspace_dialog(window)
    close_caption = caption_close(native)
    assert native.transientParent() is window
    target = tmp_path / 'volume.voxworkspace'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.workspace_document_controller.QFileDialog.getSaveFileName', lambda *args: (str(target), ''))
    button = dialog.findChild(QObject, 'saveWorkspace')
    click(native, button)
    wait_until(lambda: not app.workspaceDocumentController.busy)
    assert target.is_file()
    assert native.grabWindow().save(str(tmp_path / 'native-workspace-volume.png'))
    close_caption()
    wait_until(lambda: not dialog.property('visible'))
    assert view._host.isVisible() and view.loadState == 'ready'
    assert not warnings, warnings


def test_workspace_dialog_theme_updates_without_reopening(sidebar_scene, tmp_path):
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtCore import QMetaObject
    window, app, _, warnings = sidebar_scene
    manager = app.workspaceDocumentController
    manager._autosave.stop()
    manager._message = '工作区说明与影像来源路径'
    dialog, native = workspace_dialog(window)
    message = dialog.findChild(QObject, 'workspaceDocumentMessage')
    for theme in ('light', 'dark', 'light'):
        app.settingsController.setValue('appearance', 'theme', theme)
        QTest.qWait(80)
        colors = app.appearanceController.colors
        assert native.grabWindow().save(str(tmp_path / f'workspace-{theme}.png'))
        assert dialog.property('visible')
        assert dialog.property('background').property('color') == QColor(colors['panelBackgroundStrong'])
        assert native.color() == QColor(colors['panelBackgroundStrong'])
        assert native in app._native_window_chromes
        assert not app._native_window_chromes[native]._custom_title
        if sys.platform == 'darwin' and QGuiApplication.platformName() == 'cocoa':
            import ctypes
            from test_window_chrome import _mac_send
            caption = _mac_send(int(native.winId()), 'window')
            assert not _mac_send(caption, 'titleVisibility')
            name = _mac_send(_mac_send(caption, 'effectiveAppearance'), 'name')
            assert (b'Dark' in ctypes.string_at(_mac_send(name, 'UTF8String'))) == (theme == 'dark')
        assert message.property('color') == QColor(colors['textMuted'])
        assert message.property('selectionColor') == QColor(colors['selectionBackground'])
        assert message.property('selectedTextColor') == QColor(colors['textPrimary'])
        QMetaObject.invokeMethod(message, 'selectAll')
    manager._error = True
    manager.changed.emit()
    QTest.qWait(30)
    assert message.property('color') == QColor(colors['dangerColor'])
    QMetaObject.invokeMethod(dialog, 'close')
    dialog, native = workspace_dialog(window)
    QTest.qWait(30)
    assert native.color() == QColor(colors['panelBackgroundStrong'])
    assert native in app._native_window_chromes
    assert not warnings, warnings
