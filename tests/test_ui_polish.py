"""Regression coverage for narrow panels and compact settings, using real QML."""
import time
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
import pytest

from test_display_tools_qml import display_panel, _find, _click
from test_measurement_qml import qt_app, _visual_children
from test_pacs_qml import scene
from test_tag_qml import find, click, descendants
from test_dicom_tags import wait_until


def inside_width(item, container):
    pos = item.mapToItem(container, QPointF())
    assert pos.x() >= -0.5, (item.objectName(), pos.x())
    assert pos.x() + item.width() <= container.width() + 0.5, (
        item.objectName(), item.property("text"), pos.x(), item.width(), container.width())


@pytest.mark.parametrize('width', [220, 250, 280])
def test_annotation_controls_fit_narrow_pane_and_long_text(display_panel, tmp_path, width):
    view, controller, warnings = display_panel
    view.resize(width, 600)
    _click(view, _find(view.rootObject(), 'primaryTool-annotate'))
    _click(view, _find(view.rootObject(), 'annotateTextMode'))
    controller.textAnnotationController.setAnnotationText('这是一段用于检查换行和滚动的很长标注。' * 20)
    QTest.qWait(100)
    panel = _find(view.rootObject(), 'annotatePanel')
    inside_width(panel, view.rootObject())
    names = ['annotateArrowMode', 'annotateTextMode', 'annotationTextEditor',
             'annotationFontSize', 'annotationLineWidth', 'annotationArrowSize', 'deleteSelectedAnnotation']
    controls = [_find(panel, name) for name in names]
    swatches = [i for i in _visual_children(panel) if i.objectName().startswith('annotationColor-')]
    assert len(swatches) == 7
    for item in controls + swatches:
        inside_width(item, panel)
    assert all(item.width() >= 24 for item in swatches)
    assert len({round(item.mapToItem(panel, QPointF()).y()) for item in swatches}) == 1
    slider = _find(panel, 'annotationFontSize')
    slider.forceActiveFocus()
    previous = controller.textAnnotationController.annotationFontSize
    QTest.keyClick(view, Qt.Key_Right)
    assert controller.textAnnotationController.annotationFontSize > previous
    assert view.grabWindow().save(str(tmp_path / f'annotations-{width}.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('category', ['sources', 'colormap', 'window', 'crosshair', 'corners', 'scale', 'measurement', 'roi', 'services'])
def test_compact_settings_fit_and_navigation_is_reachable(scene, category, tmp_path):
    window, app, warnings = scene
    window.resize(1280, 720)
    app.workspaceController.openSettings()
    QTest.qWait(60)
    button = reveal_settings_category(window, category)
    click(window, button)
    assert app.settingsController.activeCategory == category
    assert button.property('checked')
    QTest.qWait(60)
    page = find(window, 'settingsPage')
    for item in descendants(page):
        if not item.isVisible():
            continue
        if item.objectName().startswith(('setting-', 'crosshairPreview-', 'colorMap-', 'windowTemplate', 'saveWindow')):
            inside_width(item, page)
    assert window.grabWindow().save(str(tmp_path / f'settings-{category}-1280.png'))
    assert not warnings, warnings


def reveal_settings_category(window, category):
    """Reach a clipped category with real wheel input before clicking it."""
    scroll = find(window, 'settingsCategoryScroll')
    flick = scroll.property('contentItem')
    button = find(window, 'settingsCategory-' + category)
    for _ in range(30):
        position = button.mapToItem(scroll, QPointF())
        if 0 <= position.y() and position.y() + button.height() <= scroll.height():
            wait_until(lambda: not flick.property('moving'))
            position = button.mapToItem(scroll, QPointF())
            if not 0 <= position.y() or position.y() + button.height() > scroll.height():
                continue
            inside_width(button, scroll)
            return button
        delta = 120 if position.y() < 0 else -120
        point = scroll.mapToScene(QPointF(scroll.width() / 2, scroll.height() / 2))
        event = QWheelEvent(point, QPointF(window.mapToGlobal(point.toPoint())),
                            QPoint(), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        event.setTimestamp(int(time.monotonic() * 1000))
        QCoreApplication.sendEvent(window, event)
        QTest.qWait(80)
    pytest.fail(f'Settings category {category} remained clipped after scrolling')


def test_compact_settings_all_categories_scroll_and_activate(scene):
    window, app, warnings = scene
    window.resize(1280, 720)
    app.workspaceController.openSettings()
    QTest.qWait(100)
    # The navigation is intentionally scrollable. Every destination must become
    # fully visible and respond to actual input, including entries at the end.
    categories = ['appearance', 'toolbar', 'input', 'privacy', 'workspace', 'updates',
                  'sources', 'export', 'colormap', 'window', 'crosshair', 'corners',
                  'scale', 'measurement', 'roi', 'services', 'ai']
    for index, category in enumerate(categories):
        button = reveal_settings_category(window, category)
        if index % 2:
            button.forceActiveFocus(Qt.TabFocusReason)
            QTest.keyClick(window, Qt.Key_Space)
        else:
            click(window, button)
        wait_until(lambda: app.settingsController.activeCategory == category)
        assert button.property('checked')
    # Scrolling back to the first destination must work after visiting the last.
    first = reveal_settings_category(window, 'appearance')
    click(window, first)
    assert app.settingsController.activeCategory == 'appearance'
    assert not warnings, warnings


def test_compact_combo_keyboard_selection_updates_settings(scene):
    window, app, warnings = scene
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('corners')
    QTest.qWait(60)
    combo = find(window, 'setting-corners-colorMode')
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Space)
    QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    assert app.settingsController.values['corners']['colorMode'] == 'custom'
    assert not warnings, warnings


@pytest.mark.parametrize('width', [220, 250, 280])
def test_tool_detail_text_and_controls_stay_inside_pane(display_panel, width):
    view, controller, warnings = display_panel
    view.resize(width, 600)
    for tool in ['window', 'measure', 'rotate', 'pseudocolor', 'viewport-settings', 'service']:
        controller._tool_controller.activateTool(tool)
        if tool == 'service':
            controller._tool_controller.selectService('service:qa')
        QTest.qWait(50)
        flick = _find(view.rootObject(), 'toolDetailFlickable')
        for item in _visual_children(flick):
            if item.isVisible() and (item.metaObject().className().startswith('QQuickText')
                                     or item.objectName().startswith(('waterQaSetting-', 'colorMap-'))):
                inside_width(item, flick)
    assert not warnings, warnings


def test_full_workspace_icon_navigation_and_annotation_preview(scene, tmp_path):
    from test_series_sidebar import phantom_series
    from test_dicom_tags import wait_until
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    window, app, warnings = scene
    series = phantom_series(tmp_path, 1, 'DEMO-A', '1.2.3.901', '20260906')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None
               and bool(app.workspaceController.activeViewport.imageSource))
    window.resize(1400, 900)
    view = app.workspaceController.activeViewport
    view._tool_controller.activateTool('annotate')
    view.textAnnotationController.setAnnotationText('示例标注')
    view.textAnnotationController.addAnnotation(55, 50, 70, 67)
    QTest.qWait(80)
    two_d = find(window, 'openView-2d')
    four_d = find(window, 'openView-4d')
    file = find(window, 'sidebarOpenFolder')
    glyph = lambda button: next(i for i in descendants(button) if i.objectName() == 'toolbarGlyph')
    assert glyph(two_d).property('iconColor') == glyph(four_d).property('iconColor')
    assert glyph(file).property('iconColor') != glyph(two_d).property('iconColor')
    assert not four_d.isEnabled()
    QTest.mouseMove(window, four_d.mapToScene(QPointF(four_d.width()/2, four_d.height()/2)).toPoint())
    QTest.qWait(500)
    assert four_d.parentItem().property('tooltipVisible')
    assert '4D' in four_d.parentItem().property('tooltipText')
    QTest.mouseMove(window, window.contentItem().mapToScene(QPointF(900, 850)).toPoint())
    QTest.qWait(50)
    for scrollbar in descendants(window.contentItem()):
        if scrollbar.objectName() == 'appScrollBar':
            if scrollbar.property('size') >= 1:
                assert not scrollbar.isVisible()
            elif scrollbar.isVisible():
                assert scrollbar.height() > 30
                assert scrollbar.x() + scrollbar.width() == pytest.approx(scrollbar.parentItem().width())
    assert window.grabWindow().save(str(tmp_path / 'workspace-annotation.png'))
    assert not warnings, warnings
