import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_cpr_controller import cpr, qt_app, draw, wait_until
from test_cpr_qml import cpr_page, named_item, double_click
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click


@pytest.mark.parametrize('action', ['new', 'edit', 'finish', 'cancel'])
@pytest.mark.parametrize('button_name', ['cprAdvanced', 'primaryTool-cpr-path'])
def test_path_shortcuts_work_after_clicking_panel_button(sidebar_scene, action, button_name):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    tab.finishEditing()
    if action in ('finish', 'cancel'):
        tab.setPathEditing(True)
    window.requestActivate()
    QTest.qWait(80)
    button = find(window, button_name)
    click(window, button)
    if button_name == 'primaryTool-cpr-path':
        # Toolbar buttons intentionally retain viewport focus on a mouse click;
        # exercise the keyboard-focus route separately (TabFocus policy).
        button.forceActiveFocus(Qt.TabFocusReason)
    assert button.hasActiveFocus()
    key = {'new': Qt.Key_N, 'edit': Qt.Key_R, 'finish': Qt.Key_Return, 'cancel': Qt.Key_Escape}[action]
    QTest.keyClick(window, key)
    QTest.qWait(60)
    if action == 'new':
        assert tab.drawing and not tab.resultView
        tab.cancel_operation()
        assert app.shortcutController.assign('cpr-new', 'Shift+N')
        QTest.qWait(40)
        click(window, button)
        if button_name == 'primaryTool-cpr-path':
            button.forceActiveFocus(Qt.TabFocusReason)
        QTest.keyClick(window, Qt.Key_N)
        assert not tab.drawing
        QTest.keyClick(window, Qt.Key_N, Qt.ShiftModifier)
        assert tab.drawing
    elif action == 'edit':
        assert tab.pathEditing and not tab.resultView
    else:
        assert not tab.pathEditing and tab.resultView
    assert not warnings, warnings


def test_cpr_panel_commands_leave_text_and_popups_alone(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    tab.finishEditing()
    tab.setPathEditing(True)
    window.requestActivate()
    QTest.qWait(80)
    click(window, find(window, 'cprDetails'))
    name = find(window, 'cprPathName')
    click(window, name)
    for key in (Qt.Key_N, Qt.Key_R, Qt.Key_Escape, Qt.Key_Return):
        QTest.keyClick(window, key)
        assert tab.pathEditing and not tab.drawing and not tab.resultView
    assert name.hasActiveFocus()
    app.feedbackController.show()
    QTest.qWait(50)
    assert window.property('shortcutPopupOpen')
    for key in (Qt.Key_N, Qt.Key_R, Qt.Key_Return):
        QTest.keyClick(window, key)
        assert tab.pathEditing and not tab.drawing
    assert not warnings, warnings


def test_delete_and_backspace_from_panel_button_remove_only_draft_points(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    window.requestActivate()
    QTest.qWait(80)
    click(window, find(window, 'cprNewPath'))
    ref = tab.viewForRole('reference-a')
    for x in (35, 45, 65):
        ref.cprTap(x, 48, .4)
    click(window, find(window, 'cprDetails'))
    QTest.keyClick(window, Qt.Key_Delete)
    assert len(tab.controlPoints) == 2
    QTest.keyClick(window, Qt.Key_Backspace)
    assert len(tab.controlPoints) == 1 and not tab.paths
    QTest.keyClick(window, Qt.Key_Escape)
    assert not tab.drawing and not tab.paths
    assert not warnings, warnings


def test_result_split_legacy_defaults_validation_and_export_revision(cpr):
    from qt_dicom_viewer.core.cpr_session import validate_cpr_session
    draw(cpr)
    legacy = cpr.session_state()
    del legacy['resultSplitRatio']
    assert validate_cpr_session(legacy)['resultSplitRatio'] == pytest.approx(2/3)
    revision = cpr.export_revision()
    cpr.setResultSplitRatio(.55)
    assert cpr.export_revision() != revision
    state = cpr.session_state()
    for invalid in (float('nan'), float('inf'), 0, 1, 'wide', True):
        with pytest.raises(ValueError):
            validate_cpr_session(dict(state, resultSplitRatio=invalid))


def test_exit_editing_returns_to_results_and_repeated_edit_keeps_active_reference(cpr):
    draw(cpr)
    cpr.finishEditing()
    cpr.setPathEditing(True)
    other = cpr.viewForRole('reference-b')
    cpr.activateViewport(other.viewportId)
    cpr.setPathEditing(True)
    assert cpr.activeViewport is other
    assert cpr.cancel_operation()
    assert cpr.resultView and not cpr.pathEditing


def test_drag_result_split_clamps_and_survives_layout_changes(cpr_page, tmp_path):
    from qt_dicom_viewer.model import WindowLevel
    from qt_dicom_viewer.model.interaction import WindowLevelChange
    window, tab = cpr_page
    tab.viewForRole('cross').apply_window_level(WindowLevelChange(WindowLevel(2200, 4400), False))
    tab.finishEditing()
    QTest.qWait(60)
    root = window.rootObject()
    handle = named_item(root, 'cprResultSplitHandle')
    curved = named_item(root, 'cprViewport-curved')
    cross = named_item(root, 'cprViewport-cross')
    assert handle.isVisible()
    assert handle.property('cursorShape') == Qt.SizeHorCursor

    def drag(delta):
        start = handle.mapToScene(QPointF(handle.width()/2, handle.height()/2)).toPoint()
        end = start + QPointF(delta, 0).toPoint()
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(window, end, 20)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
        QTest.qWait(40)

    before = curved.width()
    drag(-130)
    assert curved.width() == pytest.approx(before-130, abs=2)
    assert window.grabWindow().save(str(tmp_path/'split-adjusted.png'))
    saved = tab.session_state()
    ratio = tab.resultSplitRatio
    tab.setPathEditing(True)
    QTest.qWait(40)
    assert not handle.isVisible()
    tab.finishEditing()
    QTest.qWait(40)
    assert curved.width() == pytest.approx(before-130, abs=2)
    double_click(window, cross)
    assert not handle.isVisible()
    QTest.qWait(500)
    double_click(window, cross)
    assert handle.isVisible() and tab.resultSplitRatio == ratio
    drag(-1000)
    assert curved.width() >= 276 and curved.width() <= 278  # 280 px cell minus borders.
    assert window.grabWindow().save(str(tmp_path/'split-left-minimum.png'))
    drag(2000)
    assert 276 <= cross.width() <= 278
    assert window.grabWindow().save(str(tmp_path/'split-right-minimum.png'))
    tab.restore_session(saved)
    wait_until(lambda: tab.ready)
    QTest.qWait(40)
    assert tab.resultSplitRatio == ratio
    window.resize(600, 700)
    QTest.qWait(40)
    assert not handle.isVisible() and curved.width() > 590
    window.resize(1000, 700)
    QTest.qWait(40)
    assert handle.isVisible() and curved.width() == pytest.approx(before-130, abs=2)
