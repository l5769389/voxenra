"""Regression scenarios for mixed keyboard/pointer use in the real reading window."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_input_settings_qml import reading_scene, visible_viewport
from test_series_sidebar import sidebar_scene
from test_sidebar_style_polish import reveal
from test_tag_qml import click, find


def test_reselect_measure_preserves_pending_angle_through_completion(sidebar_scene):
    window, _, tab = reading_scene(sidebar_scene)
    measure = tab.activeViewport.measurementController
    pixel = find(window, 'dicomPixelLayer')
    def point(x, y):
        QTest.mouseClick(window, Qt.LeftButton, pos=pixel.mapToScene(QPointF(x, y)).toPoint())
    QTest.keyClick(window, Qt.Key_M)
    QTest.keyClick(window, Qt.Key_A)
    point(30, 30)
    point(60, 30)
    wait_until(lambda: measure.activeTransaction.get('editTarget', {}).get('index') == 2)
    draft = measure.activeTransaction
    assert draft and not measure.measurementItems
    QTest.keyClick(window, Qt.Key_M)
    click(window, find(window, 'primaryTool-measure'))
    assert find(window, 'measureEntry-angle').property('checked')
    assert measure.activeTransaction == draft
    point(60, 60)
    wait_until(lambda: bool(measure.measurementItems))
    assert len(measure.measurementItems) == 1
    assert measure.measurementItems[0]['label'].endswith('°')
    assert not sidebar_scene[3], sidebar_scene[3]


def test_pending_angle_instruction_retranslates_without_showing_metrics_or_confirming_a_point(sidebar_scene):
    from qt_dicom_viewer.i18n import localize, message
    from test_tag_qml import descendants
    window, app, tab = reading_scene(sidebar_scene)
    measure = tab.activeViewport.measurementController
    QTest.keyClick(window, Qt.Key_M)
    QTest.keyClick(window, Qt.Key_A)
    pixel = find(window, 'dicomPixelLayer')
    QTest.mouseClick(window, Qt.LeftButton, pos=pixel.mapToScene(QPointF(30, 30)).toPoint())
    wait_until(lambda: bool(measure.activeTransaction))
    QTest.mouseMove(window, pixel.mapToScene(QPointF(60, 30)).toPoint())
    draft = measure.activeTransaction
    assert draft['label'] == '选择顶点'
    instruction = next(item for item in descendants(window.contentItem())
                       if item.objectName() == 'measurementInstruction' and item.isVisible())
    for locale in ('en-US', 'pt-BR', 'zh-CN'):
        app.languageController.selectLanguage(locale)
        QTest.qWait(30)
        assert instruction.property('text') == localize(message('text.0607'))
        assert not any(item.objectName() == 'measurementLabel' and item.isVisible()
                       for item in descendants(window.contentItem()))
        assert measure.activeTransaction['points'] == draft['points']
        assert measure.activeTransaction['editTarget'] == draft['editTarget']
        assert not measure.measurementItems
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('remapped', [False, True])
def test_zoom_slider_keeps_arrow_keys_but_allows_tool_shortcuts(sidebar_scene, remapped):
    window, app, tab = reading_scene(sidebar_scene)
    if remapped:
        assert app.shortcutController.assign('measure', 'F7')
    QTest.keyClick(window, Qt.Key_Z)
    slider = find(window, 'zoomSlider')
    click(window, slider)
    assert window.activeFocusItem() == slider and tab.activeViewport.zoom > 1
    before = tab.activeViewport.zoom
    QTest.keyClick(window, Qt.Key_Right)
    assert tab.activeViewport.zoom > before
    QTest.keyClick(window, Qt.Key_R)
    assert tab.activeViewport.zoom == 1
    QTest.keyClick(window, Qt.Key_Space)
    assert not tab.playing and tab.activeViewport.zoom == 1
    QTest.keyClick(window, Qt.Key_F7 if remapped else Qt.Key_M)
    assert window.property('activeReadingMenu') == 'measure'
    QTest.keyClick(window, Qt.Key_A)
    assert find(window, 'measureEntry-angle').property('checked')
    assert tab.activeViewport.activeInteraction == 'measure:angle'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_tool_tip_tracks_reassigned_key_in_both_toolbar_widths(sidebar_scene):
    window, app, _ = reading_scene(sidebar_scene)
    assert app.shortcutController.assign('measure', 'F7')
    for prefix in ('primaryTool-', 'compactTool-'):
        button = find(window, prefix + 'measure')
        assert button.parentItem().property('tooltipText').endswith('(F7)')
        if prefix == 'primaryTool-':
            click(window, find(window, 'toggleRightPanel'))
    assert app.shortcutController.assign('measure', '')
    assert 'F7' not in button.parentItem().property('tooltipText')
    assert not sidebar_scene[3], sidebar_scene[3]


def test_keyboard_opens_and_reopens_compact_group_without_reset(sidebar_scene):
    window, _, tab = reading_scene(sidebar_scene)
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    QTest.keyClick(window, Qt.Key_P)
    QTest.keyClick(window, Qt.Key_M)
    assert window.property('activeReadingMenu') == rail.property('expandedTool') == 'measure'
    QTest.keyClick(window, Qt.Key_A)
    QTest.keyClick(window, Qt.Key_M)
    assert find(window, 'compactAction-measure:angle').property('checked')
    reveal(window, rail, find(window, 'compactTool-measure'))
    assert window.property('activeReadingMenu') == ''
    QTest.keyClick(window, Qt.Key_E)
    assert tab.activeViewport.activeInteraction == 'measure:angle'
    QTest.keyClick(window, Qt.Key_M)
    assert find(window, 'compactAction-measure:angle').property('checked')
    QTest.keyClick(window, Qt.Key_E)
    assert tab.activeViewport.activeInteraction == 'measure:ellipse'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_compact_shortcut_reveals_group_when_rail_is_scrolled(sidebar_scene, monkeypatch):
    from test_window_sizing import fit_desktop
    window, app, _ = reading_scene(sidebar_scene)
    app.settingsController.setValue('appearance', 'toolLabels', True)
    fit_desktop(window, app, monkeypatch, (1280, 520))
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    rail.setProperty('contentY', rail.property('contentHeight') - rail.height())
    group = find(window, 'compactTool-measure')
    assert group.mapToItem(rail, QPointF()).y() < 0
    QTest.keyClick(window, Qt.Key_M)
    child = find(window, 'compactAction-measure:length')
    wait_until(lambda: 0 <= group.mapToItem(rail, QPointF()).y()
               and child.mapToItem(rail, QPointF(0, child.height())).y() <= rail.height())
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('tool,key', [('scroll', Qt.Key_S), ('zoom', Qt.Key_Z), ('window', Qt.Key_W)])
def test_expand_after_direct_tool_restores_its_scoped_controls(sidebar_scene, tool, key):
    window, _, tab = reading_scene(sidebar_scene)
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    reveal(window, rail, find(window, 'compactTool-' + tool))
    assert not window.property('activeReadingMenu')
    click(window, find(window, 'toggleRightPanel'))
    assert window.property('activeReadingMenu') == tool
    QTest.keyClick(window, key)
    assert find(window, 'primaryTool-' + tool).property('checked')
    if tool == 'scroll':
        QTest.keyClick(window, Qt.Key_K)
        assert tab.activeViewport.sliceIndex == 1
        assert find(window, 'scrollShortcut-prev').isEnabled()
    elif tool == 'zoom':
        QTest.keyClick(window, Qt.Key_2)
        assert tab.activeViewport.zoom == 2
        QTest.keyClick(window, Qt.Key_R)
        assert tab.activeViewport.zoom == 1
    else:
        assert find(window, 'activeToolReset').isEnabled()
    assert not sidebar_scene[3], sidebar_scene[3]


def test_collapse_and_expand_mpr_keeps_segmentation_and_its_mode(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'MPR', 'mpr')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    window.requestActivate()
    click(window, visible_viewport(window))
    click(window, find(window, 'primaryTool-segmentation'))
    QTest.keyClick(window, Qt.Key_E)
    tab = ws.activeTab
    assert tab.voiController.editMode == 'erase'
    click(window, find(window, 'toggleRightPanel'))
    assert tab.toolController.activeTool == 'segmentation'
    assert not window.property('activeReadingMenu')
    QTest.keyClick(window, Qt.Key_B)
    assert tab.voiController.editMode == 'erase'
    click(window, find(window, 'toggleRightPanel'))
    assert window.property('activeReadingMenu') == 'segmentation'
    QTest.keyClick(window, Qt.Key_B)
    assert tab.voiController.editMode == 'paint'
    assert not warnings, warnings
