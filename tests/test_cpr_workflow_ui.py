import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from test_cpr_controller import cpr, qt_app, draw, wait_until
from test_cpr_qml import cpr_page, named_item, double_click
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click


@pytest.mark.parametrize('finish', ['enter', 'double'])
def test_sample_alignment_activation_and_substep_drag(sidebar_scene, tmp_path, finish):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    window.requestActivate()
    QTest.qWait(80)
    reference = find(window, 'cprViewport-reference-a')
    overlay = named_item(reference, 'cprPathOverlay')
    for col, row in ((30, 20), (65, 70)):
        point = overlay.mapToScene(overlay.pixel(col, row)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, pos=point)
        QTest.qWait(60)
    if finish == 'enter':
        QTest.keyClick(window, Qt.Key_Return)
    else:
        QTest.mouseDClick(window, Qt.LeftButton, pos=point)
        QTest.mouseRelease(window, Qt.LeftButton, pos=point)
    wait_until(lambda: tab.ready)
    QTest.qWait(80)
    refs = [tab.viewForRole(role) for role in ('reference-a', 'reference-b')]
    assert tab.positionMm == 0
    assert refs[1].sliceIndex == pytest.approx(20, abs=1)
    assert all(ref.cprGuides['samplingLine']['centerOnPlane'] for ref in refs)
    assert window.grabWindow().save(str(tmp_path/'after-path-completion.png'))
    initial_slices = [ref.sliceIndex for ref in refs]
    curved = tab.viewForRole('curved')
    curved_overlay = named_item(find(window, 'cprViewport-curved'), 'cprPathOverlay')
    sample = curved_overlay.mapToScene(curved_overlay.pixel(1, curved.imageRows/2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, pos=sample)
    wait_until(lambda: tab.ready)
    assert 0 < tab.positionMm < 2*tab.current_settings.step_mm
    assert all(abs(ref.sliceIndex-old) <= 1 for ref, old in zip(refs, initial_slices))
    assert window.grabWindow().save(str(tmp_path/'after-first-sample-move.png'))
    tab.setPositionMm(0)
    wait_until(lambda: tab.ready)
    # Manual browsing remains independent until an actual sampling request.
    refs[1].setSliceIndex(refs[1].sliceCount // 2)
    wait_until(lambda: tab.ready)
    before = [ref.sliceIndex for ref in refs]
    centers = tab.session_state()['referenceCenters']
    cross = tab.viewForRole('cross')
    item = find(window, 'cprViewport-cross')
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    assert window.grabWindow().save(str(tmp_path/'before-cross-click.png'))
    QTest.mouseClick(window, Qt.LeftButton, pos=point)
    QTest.qWait(80)
    assert tab.activeViewport is cross
    assert [ref.sliceIndex for ref in refs] == before
    assert tab.positionMm == 0
    assert window.grabWindow().save(str(tmp_path/'after-cross-click.png'))
    tab.toolController.activateTool('scroll')
    QTest.mousePress(window, Qt.LeftButton, pos=point)
    QTest.mouseMove(window, point+QPoint(0, 15), 20)
    QTest.mouseMove(window, point+QPoint(0, 20), 20)
    QTest.mouseRelease(window, Qt.LeftButton, pos=point+QPoint(0, 20))
    QTest.qWait(80)
    wait_until(lambda: tab.ready)
    assert tab.positionMm == 0
    assert tab.session_state()['referenceCenters'] == centers
    assert [ref.sliceIndex for ref in refs] == before
    assert window.grabWindow().save(str(tmp_path/'after-substep-drag.png'))
    cross.handleWheel(-120, 0, item.width()/2, item.height()/2, 0)
    wait_until(lambda: tab.ready)
    assert tab.positionMm > 0 and refs[1].sliceIndex != before[1]
    assert window.grabWindow().save(str(tmp_path/'after-real-navigation.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('action', ['new', 'edit', 'finish', 'cancel'])
@pytest.mark.parametrize('button_name', ['cprAdvanced', 'primaryTool-cpr-path'])
def test_path_shortcuts_work_after_clicking_panel_button(sidebar_scene, action, button_name):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    tab.setReferenceBrowsing(False)
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
        assert not tab.pathEditing and tab.resultView == (action == "cancel")
    assert not warnings, warnings


def test_cpr_panel_commands_leave_text_and_popups_alone(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    tab.setReferenceBrowsing(False)
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


@pytest.mark.parametrize('control_name,key', [
    ('cprPosition', Qt.Key_Return),
    ('cprPosition', Qt.Key_Escape),
    ('cprProjection', Qt.Key_Escape),
    ('cprFinishPath', Qt.Key_Return),
    ('cprFinishPath', Qt.Key_Escape),
])
def test_cpr_commands_work_from_non_text_panel_controls(sidebar_scene, control_name, key):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    tab.setReferenceBrowsing(False)
    tab.setPathEditing(True)
    window.requestActivate()
    QTest.qWait(80)
    control = find(window, control_name)
    control.forceActiveFocus(Qt.TabFocusReason)
    assert control.hasActiveFocus() and not window.property('shortcutPopupOpen')
    QTest.keyClick(window, key)
    QTest.qWait(40)
    assert tab.resultView == (key == Qt.Key_Escape) and not tab.pathEditing
    if control_name == 'cprFinishPath':
        assert not control.isVisible()
        curved = find(window, 'cprViewport-' + tab.activeViewport.viewportRole)
        try:
            wait_until(curved.hasActiveFocus)
        except AssertionError:
            focus = window.activeFocusItem()
            pytest.fail(f"CPR focus was {focus}, visible={curved.isVisible()}, "
                        f"active view={tab.activeViewport.viewportRole}, window active={window.isActive()}")
    assert not warnings, warnings


def test_async_completion_preserves_visible_parameter_input_focus(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    tab.setPathEditing(True)
    window.requestActivate()
    QTest.qWait(80)
    # Hold the actual worker result so typing reliably precedes its delivery.
    results = []
    tab._queue.finished.disconnect(tab._accept_cpr)
    tab._queue.finished.connect(results.append)
    try:
        tab.setParameter('angle', 10)
        assert tab.finishEditing()
        wait_until(lambda: bool(results))
        field = find(window, 'cprParameter-angle')
        click(window, field)
        assert field.hasActiveFocus() and not tab.finishing and not tab.resultView
        tab._accept_cpr(results[-1])
        QTest.qWait(40)
        assert not tab.resultView and field.isVisible()
        assert field.hasActiveFocus()
        assert not warnings, warnings
    finally:
        tab._queue.finished.disconnect(results.append)
        tab._queue.finished.connect(tab._accept_cpr)


def test_delete_and_backspace_from_panel_button_remove_only_draft_points(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    window.requestActivate()
    QTest.qWait(80)
    assert tab.drawing
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
    from voxplane.core.cpr_session import validate_cpr_session
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
    cpr.setReferenceBrowsing(False)
    cpr.setPathEditing(True)
    other = cpr.viewForRole('reference-b')
    cpr.activateViewport(other.viewportId)
    cpr.setPathEditing(True)
    assert cpr.activeViewport is other
    assert cpr.cancel_operation()
    assert cpr.resultView and not cpr.pathEditing


def test_drag_result_split_clamps_and_survives_layout_changes(cpr_page, tmp_path):
    from voxplane.model import WindowLevel
    from voxplane.model.interaction import WindowLevelChange
    window, tab = cpr_page
    tab.viewForRole('cross').apply_window_level(WindowLevelChange(WindowLevel(2200, 4400), False))
    tab.setReferenceBrowsing(False)
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

    grip = named_item(handle, "resizeGrip")
    QTest.mouseMove(window, curved.mapToScene(QPointF(30, 30)).toPoint())
    wait_until(lambda: not grip.isVisible())
    QTest.mouseMove(window, handle.mapToScene(QPointF(handle.width()/2, 30)).toPoint())
    wait_until(grip.isVisible)
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
    tab.setReferenceBrowsing(False)
    QTest.qWait(40)
    assert curved.width() == pytest.approx(before-130, abs=2)
    double_click(window, cross)
    assert not handle.isVisible()
    QTest.qWait(500)
    double_click(window, cross)
    assert handle.isVisible() and tab.resultSplitRatio == ratio
    drag(-1000)
    minimum = root.property('minimumResultWidth') - 4  # Cell minus viewport margins.
    assert curved.width() == pytest.approx(minimum, abs=1)
    assert window.grabWindow().save(str(tmp_path/'split-left-minimum.png'))
    drag(2000)
    assert cross.width() == pytest.approx(minimum, abs=1)
    assert window.grabWindow().save(str(tmp_path/'split-right-minimum.png'))
    tab.restore_session(saved)
    wait_until(lambda: tab.ready)
    QTest.qWait(40)
    assert tab.resultSplitRatio == ratio
    window.resize(600, 700)
    QTest.qWait(40)
    assert handle.isVisible() and curved.width() > 590
    assert handle.property('cursorShape') == Qt.SizeVerCursor
    before_height = curved.height()
    start = handle.mapToScene(QPointF(handle.width()/2, handle.height()/2)).toPoint()
    end = start + QPointF(0, 64).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 20)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(40)
    assert curved.height() == pytest.approx(before_height + 64, abs=2)
    assert window.grabWindow().save(str(tmp_path/'stacked-split-adjusted.png'))
    tab.setResultSplitRatio(ratio)
    window.resize(1000, 700)
    QTest.qWait(40)
    assert handle.isVisible() and curved.width() == pytest.approx(before-130, abs=2)


def test_new_cpr_first_click_places_a_point_without_choosing_a_tool(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    ref = find(window, 'cprViewport-reference-a')
    assert named_item(ref, 'viewportInteractionLayer').property('hoverCursorKind') == 'cpr-path'
    click(window, ref)
    wait_until(lambda: tab.drawing and len(tab.controlPoints) == 1)
    assert find(window, 'cprCancelPath').isEnabled()
    assert not find(window, 'cprFinishPath').isEnabled()
    assert not warnings, warnings


@pytest.mark.parametrize('edge', ['middle', 'curved-border', 'cross-border'])
def test_result_panes_follow_the_visible_boundary_in_main_window(sidebar_scene, edge):
    window, app, records, warnings = sidebar_scene
    window.resize(1440, 850)
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    tab.setReferenceBrowsing(False)
    curved = find(window, 'cprViewport-curved')
    cross = find(window, 'cprViewport-cross')
    handle = find(window, 'cprResultSplitHandle')
    QTest.qWait(100)
    for delta in (56, -96):
        right = curved.mapToScene(QPointF(curved.width(), curved.height() / 3))
        left = cross.mapToScene(QPointF(0, cross.height() / 3))
        # Users can grab either cell border as well as the center of the gutter.
        start = {'middle': (right + left) / 2, 'curved-border': right + QPointF(1, 0),
                 'cross-border': left - QPointF(1, 0)}[edge].toPoint()
        w1, w2 = curved.width(), cross.width()
        QTest.mouseMove(window, start)
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        try:
            assert handle.property('pressed')
            for step in range(1, 5):
                end = start + QPointF(delta * step / 4, 0).toPoint()
                QTest.mouseMove(window, end, 12)
                wait_until(lambda: abs(curved.width() - (w1 + delta * step / 4)) <= 2, timeout=1000)
                assert cross.width() == pytest.approx(w2 - delta * step / 4, abs=2)
        finally:
            QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, start + QPointF(delta, 0).toPoint())
    assert not warnings, warnings


def test_interval_shortcuts_labels_and_scope_in_main_window(sidebar_scene, monkeypatch):
    from threading import Event
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    uid = records[0].series_instance_uid
    ws.createTab(uid, 'CPR', 'cpr')
    tab = ws.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    ref = find(window, 'cprViewport-reference-a')
    window.requestActivate()
    ref.forceActiveFocus()
    assert '(' not in find(window, 'cprInterval').property('text')
    click(window, find(window, 'cprInterval'))
    start = find(window, 'cprMarkStart')
    assert start.property('text').endswith('(S)')
    tab.setPositionMm(6)
    wait_until(lambda: tab.ready)
    # K updates the selected sample immediately; S/E must not lose it while
    # the cross-section image for the same centerline is still being drawn.
    resume, compute = Event(), tab._queue._compute
    def slow_section(request):
        assert resume.wait(5)
        return compute(request)
    monkeypatch.setattr(tab._queue, '_compute', slow_section)
    try:
        QTest.keyClick(window, Qt.Key_K)
        first_mark = tab.positionMm
        assert tab.busy and not tab.ready
        QTest.keyClick(window, Qt.Key_S)
        assert tab.hasInterval and tab.interval_mm == (first_mark, first_mark)
        assert start.isEnabled()
        QTest.keyClick(window, Qt.Key_K)
        QTest.keyClick(window, Qt.Key_E)
        assert tab.positionMm > first_mark and tab.interval_mm == (first_mark, tab.positionMm)
    finally:
        resume.set()
    wait_until(lambda: tab.ready)
    interval = tab.interval_mm
    assert app.shortcutController.assign('cpr-start', 'Shift+T')
    wait_until(lambda: start.property('text').endswith('(' + app.shortcutController.hint('cpr-start') + ')'))
    QTest.keyClick(window, Qt.Key_T, Qt.ShiftModifier)
    assert tab.interval_mm == (interval[1], interval[1])
    click(window, find(window, 'cprPositionInput'))
    QTest.keyClick(window, Qt.Key_V)
    assert not tab.resultView
    ref.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_V)
    wait_until(lambda: tab.resultView)
    selected = tab.interval_mm
    click(window, find(window, 'primaryTool-measure'))
    find(window, 'cprViewport-curved').forceActiveFocus()
    for key in (Qt.Key_N, Qt.Key_R, Qt.Key_E, Qt.Key_V):
        QTest.keyClick(window, key)
    assert tab.toolController.activePanel == 'measure' and tab.resultView
    assert not tab.drawing and not tab.pathEditing and tab.interval_mm == selected
    QTest.keyClick(window, Qt.Key_S)
    wait_until(lambda: tab.toolController.activeTool == 'scroll')
    ws.createTab(uid, '2D', '2d')
    wait_until(lambda: ws.activeTabType == '2d' and ws.activeLoadState.status == 'ready')
    image = find(window, 'imageViewport-' + ws.activeViewport.viewportId)
    image.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_S)
    wait_until(lambda: ws.activeTab.toolController.activeTool == 'scroll')
    assert not warnings, warnings


def test_selecting_a_saved_path_in_the_panel_allows_delete(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 40), (65, 40)))
    first = tab.selectedPathId
    draw(tab, ((35, 56), (65, 56)))
    second = tab.selectedPathId
    combo = find(window, 'cprPathSelector')
    combo.forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_Up)
    wait_until(lambda: tab.selectedPathId == first)
    assert not tab.pathEditing
    QTest.keyClick(window, Qt.Key_Backspace)
    wait_until(lambda: [p['pathId'] for p in tab.paths] == [second])
    QTest.keyClick(window, Qt.Key_Delete)
    assert len(tab.paths) == 1 and not warnings
