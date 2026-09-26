"""Compare uses real QML controls, both themes/languages and a single slider."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene, right_click
from test_tag_qml import find, click, descendants


@pytest.mark.parametrize('theme, language', [('dark', 'zh-CN'), ('light', 'zh-CN'), ('dark', 'en-US'), ('light', 'en-US')])
def test_compare_picker_layout_shared_slider_and_tools(sidebar_scene, tmp_path, theme, language):
    window, app, records, warnings = sidebar_scene
    window.resize(1000, 600)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.settingsController.setValue('appearance', 'language', language)
    panel = app.panelController
    uid, other = (r.series_instance_uid for r in records[:2])
    panel.selectSeries(uid)
    right_click(window, find(window, 'series-' + uid))
    action = find(window, 'seriesContextAction-compare2d')
    assert action.property('text') == ('序列 2D 对比' if language == 'zh-CN' else '2D series comparison')
    click(window, action)
    candidate = find(window, 'compareCandidate-' + other)
    assert not find(window, 'confirmCompare').isEnabled()
    click(window, candidate)
    assert find(window, 'confirmCompare').isEnabled()
    assert window.grabWindow().save(str(tmp_path / f'compare-picker-{theme}-{language}.png'))
    click(window, find(window, 'confirmCompare'))
    registry = app.workspaceController
    wait_until(lambda: registry.activeLoadState and registry.activeLoadState.status == 'ready')
    tab = registry.activeTab
    assert find(window, 'tabType-' + tab.tab_config.tab_id).property('text') == '2D Compare'
    assert registry.activeTabType == 'compare2d'
    left, right = tab.viewports_by_id.values()
    canvases = [find(window, 'imageViewport-' + v.viewportId) for v in (left, right)]
    frames = [find(window, 'viewportFrame-' + v.viewportId) for v in (left, right)]
    assert canvases[0].width() > 100 and canvases[1].width() > 100
    assert canvases[0].mapToScene(QPointF()).x() + canvases[0].width() < canvases[1].mapToScene(QPointF()).x()
    slider = find(window, 'compareSliceSlider')
    assert slider.mapToScene(QPointF()).y() == frames[0].mapToScene(QPointF()).y()
    assert slider.height() == frames[0].height()
    maximum = next(i for i in descendants(slider) if i.objectName() == 'sliceMaximum')
    assert maximum.property('text') == str(tab.sliceCount)
    assert not any(i.isVisible() and i.property('text') in (
        '相对进度翻页 · 不代表解剖位置配准',
        'Relative slice progress · not anatomical registration')
        for i in descendants(window.contentItem()))
    visible_sliders = [i for i in descendants(window.contentItem())
                       if i.isVisible() and i.inherits('QQuickSlider')]
    assert len(visible_sliders) == 1
    # Dragging the QML shared control really navigates both decoded stacks.
    control = next(i for i in descendants(slider) if i.isVisible() and i.inherits('QQuickSlider'))
    point = control.mapToScene(QPointF(control.width() / 2, 12)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    wait_until(lambda: left._frame_meta.slice_index == 2 and right._frame_meta.slice_index == 2)
    click(window, canvases[1])
    assert tab.activeViewport is right
    assert not frames[0].property('active') and frames[1].property('active')
    click(window, find(window, 'primaryTool-viewport-settings'))
    for operation in tab.syncOperations:
        checkbox = find(window, 'compareSync-' + operation)
        assert checkbox.property('checked')
        label = checkbox.property('text')
        assert not label.startswith('compare.')
    click(window, find(window, 'compareSync-zoom'))
    assert not tab.syncOperations['zoom']
    right.setZoom(3)
    assert left.zoom == 1
    click(window, find(window, 'compareSync-zoom'))
    assert left.zoom == 3
    assert window.grabWindow().save(str(tmp_path / f'compare-{theme}-{language}.png'))
    assert not warnings, warnings


def test_compare_pair_context_menu_in_collapsed_sidebar(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    uid, other = [r.series_instance_uid for r in records[:2]]
    app.panelController.selectSeries(uid)
    app.panelController.selectSeriesWithModifiers(other, True)
    click(window, find(window, 'sidebarToggle'))
    # Compact rail delegates have their own mouse handling and the same menu.
    rail = next(i for i in descendants(window.contentItem()) if i.objectName() == 'compactSeriesRail')
    entries = [i for i in descendants(rail) if i.objectName().endswith(uid) and i.isVisible()]
    assert entries
    right_click(window, entries[0])
    click(window, find(window, 'seriesContextAction-compare2d'))
    wait_until(lambda: app.workspaceController.activeTabType == 'compare2d')
    assert not app.panelController.compareController.dialogOpen
    assert not warnings, warnings


def test_compare_detach_preserves_pair_and_window_local_tools(sidebar_scene):
    from test_tab_windows import detached
    from test_workspace_persistence import draw_length
    window, app, records, warnings = sidebar_scene
    registry = app.workspaceController
    registry.createCompareTab(*(r.series_instance_uid for r in records[:2]))
    wait_until(lambda: registry.activeLoadState.status == 'ready')
    tab = registry.activeTab
    views = list(tab.viewports_by_id.values())
    mid = draw_length(views[1])
    tab.historyController.capture()
    tab.setSyncOperation('zoom', False)
    views[1].setZoom(2)
    registry.createTab(records[2].series_instance_uid, 'Another series', '2d')
    single = registry.activeTab
    wait_until(lambda: registry.activeLoadState.status == 'ready')
    session, other = detached(app, tab)
    other.resize(720, 600)
    for view in views:
        assert find(other, 'imageViewport-' + view.viewportId).width() > 100
    click(other, find(other, 'primaryTool-pan'))
    assert tab.toolController.activeTool == 'pan'
    assert single.toolController.activeTool == 'window'
    registry.createCompareTab(*(r.series_instance_uid for r in reversed(records[:2])))
    assert app.windowManager.owner(tab.tab_config.tab_id) is session
    assert len(registry._tab_dict) == 2
    app.windowManager.moveToMain(tab.tab_config.tab_id)
    wait_until(lambda: len(app.windowManager.sessions) == 1)
    assert list(tab.viewports_by_id.values()) == views
    assert views[1].zoom == 2 and not tab.syncOperations['zoom']
    assert mid in views[1]._measure_controller._measurements
    assert tab.historyController.canUndo
    assert not warnings, warnings


def test_picker_stays_above_native_3d_window(sidebar_scene, tmp_path):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickWindow
    if QGuiApplication.platformName() == 'offscreen':
        pytest.skip('Requires a native desktop and VTK window')
    window, app, records, warnings = sidebar_scene
    registry = app.workspaceController
    uid, other_uid = [r.series_instance_uid for r in records[:2]]
    registry.createTab(uid, 'Synthetic CT', '3d')
    wait_until(lambda: registry.activeLoadState.status == 'ready', timeout=20000)
    app.panelController.compareController.request(uid)

    def native_picker():
        return next((w for w in QGuiApplication.topLevelWindows()
                     if w is not window and isinstance(w, QQuickWindow) and w.isVisible()
                     and any(i.objectName() == 'confirmCompare' for i in descendants(w.contentItem()))), None)

    wait_until(lambda: native_picker() is not None)
    popup = native_picker()
    wait_until(popup.isExposed)
    QTest.qWait(100)
    assert not popup.flags() & Qt.FramelessWindowHint
    assert not any(i.objectName() == 'compareSeriesDialogClose' and i.isVisible()
                   for i in descendants(popup.contentItem()))
    from qt_pointer import move_pointer
    candidate = find(popup, 'compareCandidate-' + other_uid)
    assert (popup.width(), popup.height()) == (680, 540)
    assert popup.grabWindow().save(str(tmp_path / 'compare-picker-over-3d.png'))
    move_pointer(popup, candidate.mapToScene(QPointF(candidate.width() / 2, candidate.height() / 2)).toPoint())
    click(popup, candidate)
    assert app.panelController.compareController.canConfirm, (app.panelController.compareController.dialogOpen, app.panelController.compareController.partnerUid)
    button = find(popup, 'confirmCompare')
    move_pointer(popup, button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint())
    click(popup, button)
    wait_until(lambda: registry.activeTabType == 'compare2d' and registry.activeLoadState.status == 'ready')
    assert not app.panelController.compareController.dialogOpen
    assert not warnings, warnings
