"""Exercise shortcut discoverability at real sidebar widths, then use the displayed keys."""
import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from qt_pointer import move_pointer
from test_dicom_tags import qt_app, wait_until
from test_input_settings_qml import reading_scene
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, descendants, find


def caption(button, name):
    return next(item for item in descendants(button) if item.objectName() == name)


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US', 'pt-BR'])
def test_wide_and_compact_captions_preserve_name_and_shortcut_scope(sidebar_scene, locale):
    window, app, tab = reading_scene(sidebar_scene)
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance', 'toolLabels', True)
    app.settingsController.setValue('layout', 'rightPanelWidth', 420)
    QTest.keyClick(window, Qt.Key_M)
    action = app.shortcutController
    angle = find(window, 'measureEntry-angle')
    label = caption(angle, 'toolActionLabel')
    name = angle.property('shortLabel')
    assert label.property('text') == name + ' (A)'
    assert label.property('lineCount') == 1 and not label.property('truncated')
    assert action.assign('measure:angle', 'P')
    pan = find(window, 'primaryTool-pan').parentItem()
    assert '(P)' not in pan.property('tooltipText')
    QTest.keyClick(window, Qt.Key_P)
    assert angle.property('checked') and tab.activeViewport.activeInteraction == 'measure:angle'
    click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_M)
    child = find(window, 'compactAction-measure:angle')
    short = child.parentItem().property('shortLabel')
    assert caption(child, 'toolbarLabel').property('text') == short
    assert not any(item.isVisible() and item.property('text') == '(P)' for item in descendants(child))
    assert child.parentItem().property('tooltipText').endswith('(P)')
    # The compact button omits its key: hover must actually expose it.
    rail = find(window, 'compactToolRail')
    # Shortcut activation scrolls the rail to the group on the next layout pass.
    wait_until(lambda: 0 <= child.mapToItem(rail, QPointF()).y() <= rail.height() - child.height())
    action_item = child.parentItem()
    move_pointer(window, child.mapToScene(QPointF(child.width() / 2, child.height() / 2)).toPoint())
    wait_until(lambda: action_item.property('tooltipVisible'))
    tip = action_item.findChild(QObject, 'toolbarTooltip')
    assert tip.property('contentItem').property('text') == action_item.property('tooltipText')
    move_pointer(window, QPointF(10, 10).toPoint())
    wait_until(lambda: not action_item.property('tooltipVisible'))
    click(window, find(window, 'compactTool-measure'))
    QTest.keyClick(window, Qt.Key_P)
    assert tab.activeViewport.activeInteraction == 'pan'
    assert find(window, 'compactTool-pan').parentItem().property('tooltipText').endswith('(P)')
    assert not sidebar_scene[3], sidebar_scene[3]


def test_long_cpr_sample_hint_is_all_or_nothing_when_resized(sidebar_scene):
    from test_cpr_controller import draw
    window, app, records, warnings = sidebar_scene
    app.languageController.selectLanguage('en-US')
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    app.settingsController.setValue('layout', 'rightPanelWidth', 420)
    assert app.shortcutController.assign('cpr-next', 'Ctrl+Shift+F10')
    button = find(window, 'cprNextSample')
    label = caption(button, 'buttonCaption')
    key = app.shortcutController.hint('cpr-next')
    wait_until(lambda: label.property('text') == button.property('text'))
    assert label.property('text').endswith(' (' + key + ')')
    app.settingsController.setValue('layout', 'rightPanelWidth', 240)
    wait_until(lambda: label.property('text') == button.property('shortcutTitle'))
    assert label.property('lineCount') == 1 and button.property('text').endswith(' (' + key + ')')
    before = tab.positionMm
    QTest.keyClick(window, Qt.Key_K)
    assert tab.positionMm == before
    QTest.keyClick(window, Qt.Key_F10, Qt.ControlModifier | Qt.ShiftModifier)
    assert tab.positionMm > before
    assert app.shortcutController.assign('cpr-next', '')
    assert button.property('text') == button.property('shortcutTitle')
    assert not warnings, warnings


def test_play_and_stop_share_the_actual_reassigned_hint(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    assert app.shortcutController.assign('play', 'F8')
    play = find(window, 'primaryTool-play').parentItem()
    assert play.property('tooltipText').endswith('(F8)')
    QTest.keyClick(window, Qt.Key_F8)
    assert tab.playing and play.property('tooltipText').endswith('(F8)')
    QTest.keyClick(window, Qt.Key_F8)
    assert not tab.playing
    assert not sidebar_scene[3], sidebar_scene[3]
