import pytest
from test_cpr_controller import cpr, qt_app, draw, wait_until
from test_cpr_persistence import cpr_app


def test_done_edit_new_cancel_preserve_result_state(cpr):
    reference = draw(cpr)
    cross = cpr.viewForRole('cross')
    cpr.setPositionMm(5)
    wait_until(lambda: cpr.ready)
    before = cross.viewport_state
    cpr.setReferenceBrowsing(False)
    assert cpr.resultView and cpr.activeViewport.viewportRole == 'curved'
    assert not cpr.pathEditing
    cpr.setPathEditing(True)
    assert not cpr.resultView and cpr.pathEditing
    assert cpr.activeViewport.viewportRole.startswith('reference')
    assert reference.cprFinish()
    assert not cpr.resultView and cross.viewport_state == before
    cpr.setReferenceBrowsing(False)
    original = cpr.current_path
    cpr.startPath()
    assert not cpr.resultView and cpr.drawing
    reference.cprTap(5, 10, .4)
    cpr.startPath()  # Repeated creation must not discard a draft.
    assert len(cpr.controlPoints) == 1
    assert cpr.cancel_operation()
    assert cpr.resultView and cpr.current_path == original


def test_done_waits_for_new_result_and_failure_does_not_switch(cpr):
    cpr.startPath()
    assert not cpr.finishEditing()
    assert cpr.drawing and not cpr.resultView
    ref = cpr.viewForRole('reference-a')
    ref.cprTap(5, 10, .4)
    ref.cprTap(15, 10, .4)
    assert cpr.finishEditing()
    cpr.setReferenceBrowsing(False)
    assert not cpr.resultView
    cpr._fail_cpr(cpr._generation, 'test failure')
    wait_until(lambda: not cpr.busy)
    assert not cpr.resultView
    cpr.setReferenceBrowsing(False)
    wait_until(lambda: cpr.resultView)


def test_result_layout_roundtrip_and_legacy_session(cpr):
    from voxplane.core.cpr_session import validate_cpr_session
    draw(cpr)
    cpr.setReferenceBrowsing(False)
    state = cpr.session_state()
    assert state['resultView']
    cpr.setPathEditing(True)
    cpr.restore_session(state)
    wait_until(lambda: cpr.ready)
    assert cpr.resultView
    legacy = dict(state)
    del legacy['resultView']
    assert not validate_cpr_session(legacy)['resultView']
    with pytest.raises(ValueError):
        validate_cpr_session(dict(state, resultView='yes'))


def test_switching_tools_cancels_pending_result_transition(cpr):
    cpr.startPath()
    ref = cpr.viewForRole('reference-a')
    ref.cprTap(5, 10, .4)
    ref.cprTap(15, 10, .4)
    assert cpr.finishEditing() and not cpr.resultView
    cpr.setReferenceBrowsing(False)
    other = cpr.viewForRole('reference-b')
    cpr.activateViewport(other.viewportId)
    cpr.toolController.activateTool('measure')
    wait_until(lambda: cpr.ready)
    assert not cpr.resultView
    assert cpr.activeViewport is other


def test_configurable_creation_and_edit_shortcuts_are_cpr_scoped(cpr, tmp_path):
    from voxplane.ui.controller.settings_controller import SettingsController
    from voxplane.ui.controller.shortcut_controller import ShortcutController
    shortcuts = ShortcutController(SettingsController(path=tmp_path/'settings.json'))
    assert shortcuts.hint('cpr-new') == 'N'
    assert shortcuts.assign('cpr-new', 'Shift+N')
    assert shortcuts.activate('cpr-new', cpr.toolController, cpr)
    ref = cpr.viewForRole('reference-a')
    ref.cprTap(5, 10, .4)
    assert shortcuts.activate('cpr-new', cpr.toolController, cpr)
    assert len(cpr.controlPoints) == 1
    ref.cprTap(15, 10, .4)
    cpr.finishEditing()
    wait_until(lambda: cpr.ready)
    assert not cpr.resultView
    assert shortcuts.activate('cpr-edit', cpr.toolController, cpr)
    assert cpr.pathEditing and not cpr.resultView
    cpr.toolController.activateTool('measure')
    assert not cpr.pathEditing
    assert not shortcuts.activate('cpr-new', cpr.toolController, cpr)
    assert not shortcuts.activate('cpr-edit', cpr.toolController, cpr)
    assert cpr.toolController.activeTool == 'measure'


def test_existing_shortcut_letters_survive_upgrade(qt_app):
    from voxplane.settings.preferences import normalize_settings
    from voxplane.settings.shortcuts import validate_bindings
    raw = {'pan': 'N', 'zoom': 'R'}
    bindings = normalize_settings({'shortcuts': {'bindings': raw}})['shortcuts']['bindings']
    assert bindings['pan'] == 'N' and bindings['zoom'] == 'R'
    assert bindings['cpr-new'] == bindings['cpr-edit'] == ''
    assert validate_bindings(dict(raw, **{'cpr-new': 'N'}))['cpr-new'] == 'N'
    with pytest.raises(ValueError):
        validate_bindings({'cpr-new': 'R', 'cpr-edit': 'R'})


@pytest.mark.parametrize('results', [False, True])
def test_workspace_snapshot_preserves_active_and_focused_result(cpr, results):
    from voxplane.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot
    draw(cpr)
    if results:
        cpr.setReferenceBrowsing(False)
    cross = cpr.viewForRole('cross')
    cpr.activateViewport(cross.viewportId)
    cpr.focusSingleViewport(cross.viewportId)
    state = tab_snapshot(cpr)
    apply_tab_snapshot(cpr, state)
    wait_until(lambda: cpr.ready)
    assert cpr.resultView == results
    assert cpr.activeViewport is cross
    assert cpr.focusedViewportId == cross.viewportId


def test_hidden_reference_history_restores_without_leaving_results(cpr_app, tmp_path):
    from test_cpr_persistence import save
    from test_workspace_persistence import draw_length
    app, tab, _ = cpr_app
    ref = tab.viewForRole('reference-a')
    measurement = draw_length(ref)
    source = ref._measure_controller._sources[measurement]
    tab.setReferencePlane(0, 'coronal')
    wait_until(lambda: tab.ready and not tab.busy)
    tab.navigate_measurement(ref, source)
    wait_until(lambda: ref.historicalPlane)
    tab.setReferenceBrowsing(False)
    cross = tab.viewForRole('cross')
    tab.activateViewport(cross.viewportId)
    tab.focusSingleViewport(cross.viewportId)
    path = tmp_path/'results.voxworkspace'
    tab.setResultSplitRatio(.58)
    save(app, path)
    doc = app.workspaceDocumentController
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy, timeout=10000)
    assert not doc.isError, doc.message
    restored = app.workspaceController.activeTab
    ref = restored.viewForRole('reference-a')
    wait_until(lambda: ref.historicalPlane)
    assert restored.resultView
    assert restored.resultSplitRatio == .58
    assert restored.activeViewport.viewportRole == 'cross'
    assert restored.focusedViewportId == restored.activeViewport.viewportId
    restored.navigate_measurement(ref, source)
    assert not restored.resultView and restored.activeViewport is ref
    assert not restored.focusedViewportId


def test_range_marks_preserve_historical_section_and_undo(cpr_app):
    from test_workspace_persistence import draw_length
    _, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    uid = draw_length(cross)
    source = cross.measurementController._sources[uid]
    tab.setPositionMm(20)
    wait_until(lambda: tab.ready)
    tab.navigate_measurement(cross, source)
    wait_until(lambda: cross.historicalPlane)
    generation, image = tab._generation, cross.imageSource
    history = tab._edit_history
    history.capture()
    tab.setParameter('rangeStart', 10)
    assert tab.parameters['rangeStart'] == tab.parameters['rangeEnd'] == 10
    history.capture()
    tab.setParameter('rangeEnd', 20)
    history.capture()
    for action, end in [(history.undo, 10), (history.redo, 20)]:
        action()
        assert tab.parameters['rangeEnd'] == end
        assert tab._generation == generation and cross.historicalPlane and cross.imageSource == image
    assert not cross.cprGuides
    assert tab.viewForRole('curved').cprGuides['startColumn'] == pytest.approx(10 / tab._result.curve.centerline.spacing_mm)


def test_clear_cpr_clears_scalar_display(cpr):
    cross = cpr.viewForRole('cross')
    cross.enable_scalar_display()
    draw(cpr)
    assert cross.scalarDisplay
    cross.clear_cpr()
    assert not cross.scalarDisplay and not cross.imageSource
