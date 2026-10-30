import pytest
from test_cpr_controller import cpr, qt_app, draw, wait_until
from test_cpr_persistence import cpr_app


def test_done_edit_new_cancel_preserve_result_state(cpr):
    reference = draw(cpr)
    cross = cpr.viewForRole('cross')
    cpr.setPositionMm(5)
    wait_until(lambda: cpr.ready)
    before = cross.viewport_state
    assert cpr.finishEditing()
    assert cpr.resultView and cpr.activeViewport.viewportRole == 'curved'
    assert not cpr.pathEditing
    cpr.setPathEditing(True)
    assert not cpr.resultView and cpr.pathEditing
    assert cpr.activeViewport.viewportRole.startswith('reference')
    assert reference.cprFinish()
    assert cpr.resultView and cross.viewport_state == before
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
    assert not cpr.resultView
    cpr._fail_cpr(cpr._generation, 'test failure')
    wait_until(lambda: not cpr.busy)
    assert not cpr.resultView
    assert cpr.finishEditing()
    wait_until(lambda: cpr.resultView)


def test_result_layout_roundtrip_and_legacy_session(cpr):
    from qt_dicom_viewer.core.cpr_session import validate_cpr_session
    draw(cpr)
    cpr.finishEditing()
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
    other = cpr.viewForRole('reference-b')
    cpr.activateViewport(other.viewportId)
    cpr.toolController.activateTool('measure')
    wait_until(lambda: cpr.ready)
    assert not cpr.resultView
    assert cpr.activeViewport is other


def test_configurable_creation_and_edit_shortcuts_are_cpr_scoped(cpr, tmp_path):
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    from qt_dicom_viewer.ui.controller.shortcut_controller import ShortcutController
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
    wait_until(lambda: cpr.resultView)
    assert shortcuts.activate('cpr-edit', cpr.toolController, cpr)
    assert cpr.pathEditing and not cpr.resultView
    cpr.toolController.activateTool('measure')
    assert not cpr.pathEditing
    assert not shortcuts.activate('cpr-new', cpr.toolController, object())


def test_existing_shortcut_letters_survive_upgrade(qt_app):
    from qt_dicom_viewer.settings.preferences import normalize_settings
    from qt_dicom_viewer.settings.shortcuts import validate_bindings
    raw = {'pan': 'N', 'zoom': 'R'}
    bindings = normalize_settings({'shortcuts': {'bindings': raw}})['shortcuts']['bindings']
    assert bindings['pan'] == 'N' and bindings['zoom'] == 'R'
    assert bindings['cpr-new'] == bindings['cpr-edit'] == ''
    with pytest.raises(ValueError):
        validate_bindings(dict(raw, **{'cpr-new': 'N'}))


@pytest.mark.parametrize('results', [False, True])
def test_workspace_snapshot_preserves_active_and_focused_result(cpr, results):
    from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot
    draw(cpr)
    if results:
        cpr.finishEditing()
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
    tab.finishEditing()
    cross = tab.viewForRole('cross')
    tab.activateViewport(cross.viewportId)
    tab.focusSingleViewport(cross.viewportId)
    path = tmp_path/'results.voxworkspace'
    save(app, path)
    doc = app.workspaceDocumentController
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy, timeout=10000)
    assert not doc.isError, doc.message
    restored = app.workspaceController.activeTab
    ref = restored.viewForRole('reference-a')
    wait_until(lambda: ref.historicalPlane)
    assert restored.resultView
    assert restored.activeViewport.viewportRole == 'cross'
    assert restored.focusedViewportId == restored.activeViewport.viewportId
    restored.navigate_measurement(ref, source)
    assert not restored.resultView and restored.activeViewport is ref
    assert not restored.focusedViewportId
