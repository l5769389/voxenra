from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from test_cpr_controller import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_mpr_volume_tools_qml import item_window


def test_cpr_actions_stay_at_bottom_and_do_not_duplicate_completion(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    window.resize(1440, 720)
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    window.requestActivate()
    QTest.qWait(80)
    footer = find(window, 'toolResetBar')
    done, cancel = find(window, 'cprFinishPath'), find(window, 'cprCancelPath')
    actions = done.parentItem()
    assert actions.objectName() == 'cprBottomActions'
    assert done.mapToScene(QPointF()).y() >= footer.mapToScene(QPointF()).y()
    click(window, cancel)
    new = find(window, 'cprNewPath')
    click(window, new)
    assert done.isVisible() and cancel.isVisible() and not new.isVisible()
    assert not done.isEnabled()
    ref = tab.viewForRole('reference-a')
    ref.cprTap(35, 48, .4)
    ref.cprTap(65, 48, .4)
    click(window, done)
    wait_until(lambda: tab.ready)
    assert not tab.resultView
    browse = find(window, 'cprReferenceBrowse')
    assert browse.isVisible() and not new.isVisible()
    edit = find(window, 'cprEditPath')
    assert edit.isVisible() and find(window, 'cprAdditionalPath').isVisible()
    assert not tab.pathEditing and not tab.drawing
    assert not done.isVisible() and not cancel.isVisible()
    click(window, edit)
    assert tab.pathEditing and done.isVisible()
    assert not new.isVisible() and not edit.isVisible() and not cancel.isVisible()
    panel = find(window, 'cprPanel')
    panel.setProperty('advanced', True)
    panel.setProperty('details', True)
    panel.setProperty('interval', True)
    QTest.qWait(60)
    scroll = find(window, 'toolDetailFlickable')
    assert scroll.property('contentHeight') > scroll.height()
    before = done.mapToScene(QPointF())
    scroll.setProperty('contentY', scroll.property('contentHeight')-scroll.height())
    QTest.qWait(40)
    assert done.mapToScene(QPointF()) == before
    assert before.y() >= scroll.mapToScene(QPointF(0, scroll.height())).y()
    assert window.grabWindow().save(str(tmp_path/'editing-footer.png'))
    # Keyboard focus on the relocated footer has the same command scope.
    done.forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.qWait(40)
    assert not tab.resultView and not tab.pathEditing
    click(window, browse)
    browse.forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_N)
    QTest.qWait(30)
    assert tab.drawing and cancel.isVisible()
    click(window, cancel)
    assert tab.resultView
    assert window.grabWindow().save(str(tmp_path/'results-footer.png'))
    # Other tools retain their own footer actions.
    click(window, find(window, 'primaryTool-zoom'))
    assert not actions.isVisible()
    assert find(window, 'activeToolReset').isVisible()
    assert not warnings, warnings


def test_cpr_compact_flyout_keeps_fixed_actions(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    window.resize(1440, 720)
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    window.requestActivate()
    ref = tab.viewForRole('reference-a')
    assert ref.cprTap(35, 48, .4)
    click(window, find(window, 'toggleRightPanel'))
    popup = window.findChild(QObject, 'compactVolumePanel')

    def open_actions():
        if not popup.property('visible'):
            click(window, find(window, 'compactTool-cpr-path'))
        assert popup.property('visible')
        return item_window(popup.property('contentItem'))

    flyout = open_actions()
    assert tab.drawing and len(tab.controlPoints) == 1
    click(flyout, find(flyout, 'cprCancelPath'))
    assert not tab.drawing and not tab.selectedPathId
    click(flyout, find(flyout, 'cprNewPath'))
    ref.cprTap(35, 48, .4)
    ref.cprTap(65, 48, .4)
    flyout = open_actions()
    click(flyout, find(flyout, 'cprFinishPath'))
    wait_until(lambda: tab.ready)
    assert not tab.resultView
    flyout = open_actions()
    click(flyout, find(flyout, 'cprEditPath'))
    assert tab.pathEditing
    flyout = open_actions()
    done = find(flyout, 'cprFinishPath')
    panel = find(flyout, 'cprPanel')
    for section in ['advanced', 'details', 'interval']:
        panel.setProperty(section, True)
    QTest.qWait(50)
    scroll = find(flyout, 'compactToolDetailFlickable')
    assert scroll.property('contentHeight') > scroll.height()
    before = done.mapToScene(QPointF())
    scroll.setProperty('contentY', scroll.property('contentHeight') - scroll.height())
    QTest.qWait(30)
    assert done.mapToScene(QPointF()) == before
    assert before.y() >= scroll.mapToScene(QPointF(0, scroll.height())).y()
    assert flyout.grabWindow().save(str(tmp_path / 'compact-editing-footer.png'))
    click(flyout, done)
    assert not tab.pathEditing and not tab.resultView
    assert not warnings, warnings


def test_compact_cpr_flyout_accepts_scoped_interval_shortcuts(sidebar_scene):
    from test_cpr_controller import draw
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    click(window, find(window, 'toggleRightPanel'))
    click(window, find(window, 'compactTool-cpr-path'))
    popup = window.findChild(QObject, 'compactVolumePanel')
    flyout = item_window(popup.property('contentItem'))
    button = find(flyout, 'cprInterval')
    scroll = find(flyout, 'compactToolDetailFlickable')
    scroll.setProperty('contentY', scroll.property('contentHeight') - scroll.height())
    QTest.qWait(40)
    click(flyout, button)
    assert find(flyout, 'cprMarkStart').isVisible()
    QTest.keyClick(flyout, Qt.Key_S)
    wait_until(lambda: tab.hasInterval)
    assert tab.toolController.activePanel == 'cpr-path'
    click(flyout, find(flyout, 'compactVolumePanelClose'))
    wait_until(lambda: not popup.property('visible'))
    ref = find(window, 'cprViewport-reference-a')
    ref.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_N)
    QTest.keyClick(window, Qt.Key_R)
    assert not tab.drawing and not tab.pathEditing and not popup.property('visible')
    tab.startPath()
    for x in (35, 65):
        tab.viewForRole('reference-a').cprTap(x, 48, .4)
    for key in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Return, Qt.Key_Escape):
        QTest.keyClick(window, key)
        assert tab.drawing and len(tab.controlPoints) == 2
    QTest.keyClick(window, Qt.Key_S)
    wait_until(lambda: tab.toolController.activeTool == 'scroll')
    assert not warnings, warnings
