"""Drawing commands follow the active document across ordinary UI focus changes."""
import pytest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, descendants, find, settled_point
from test_workspace_dialog_layout import workspace_dialog


def start_draft(scene, kind, key=Qt.Key_Escape):
    window, app, records, _ = scene
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'Drawing', kind)
    tab = workspace.activeTab
    wait_until(lambda: tab.referencesReady if kind == 'cpr'
               else workspace.activeLoadState.status == 'ready')
    window.requestActivate()
    wait_until(lambda: window.isActive())
    if kind == 'cpr':
        reference = find(window, 'cprViewport-reference-a')
        reference.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_N)
        pixels = next(item for item in descendants(reference)
                      if item.objectName() == 'dicomPixelLayer')
    else:
        click(window, find(window, 'viewportInteractionLayer'))
        QTest.keyClick(window, Qt.Key_M)
        QTest.keyClick(window, Qt.Key_V)
        assert tab.activeViewport.activeInteraction == 'measure:curve'
        pixels = find(window, 'dicomPixelLayer')
    points = [(35, 40), (65, 55)]
    # Curves require three points to finish; CPR accepts two. Keep the audited
    # two-point measurement fixture for Escape, which cancels incomplete drafts.
    if kind == '2d' and key != Qt.Key_Escape:
        points.append((75, 70))
    for x, y in points:
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                         settled_point(pixels, QPointF(x + .5, y + .5)))
    wait_until(lambda: draft_points(tab, kind) == len(points))
    assert_draft_visible(window, tab, kind)
    return window, workspace, tab


def draft_points(tab, kind):
    if kind == 'cpr':
        return len(tab.session_state()['draft'])
    return len(tab.activeViewport.measurementController.activeTransaction.get('points', []))


def assert_draft_visible(window, tab, kind):
    if kind == 'cpr':
        assert tab.drawing and find(window, 'cprPathOverlay').isVisible()
        assert '2' in find(window, 'cprPathStatus').property('text')
    else:
        wait_until(lambda: any(item.objectName() == 'measurementItem' and item.isVisible()
                               and item.property('isDraft')
                               for item in descendants(window.contentItem())))


def assert_finished(window, tab, kind, key):
    assert draft_points(tab, kind) == 0
    expected = 0 if key == Qt.Key_Escape else 1
    if kind == 'cpr':
        assert not tab.drawing
        assert len(tab.paths) == expected
        if expected:
            wait_until(lambda: tab.ready)
            assert len(tab.current_path.control_points) == 2
        wait_until(lambda: not any(item.isVisible() and item.objectName() in
                                  ('cprFinishPath', 'cprCancelPath')
                                  for item in descendants(window.contentItem())))
        assert not find(window, 'cprPathOverlay').property('drawing')
    else:
        measure = tab.activeViewport.measurementController
        assert not measure.has_active_transaction
        assert len(measure.committed_measurements) == expected
        if expected:
            assert len(measure.measurementItems[0]['points']) == 3
        wait_until(lambda: not any(item.objectName() == 'measurementItem' and item.isVisible()
                                   and item.property('isDraft')
                                   for item in descendants(window.contentItem())))
        wait_until(lambda: sum(item.objectName() == 'measurementItem' and item.isVisible()
                               for item in descendants(window.contentItem())) == expected)


@pytest.mark.parametrize('kind', ['cpr', '2d'])
@pytest.mark.parametrize('key', [Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter])
def test_drawing_command_after_tab_round_trip_targets_only_active_tab(sidebar_scene, kind, key):
    # Removing window routing strands this draft on the focused tab button.
    window, workspace, tab = start_draft(sidebar_scene, kind, key)
    points = 3 if kind == '2d' and key != Qt.Key_Escape else 2
    workspace.createTab(sidebar_scene[2][1].series_instance_uid, 'Other', 'mpr')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    other = workspace.activeTab
    click(window, find(window, 'workspaceTab-' + other.tab_config.tab_id))
    for isolated_key in (Qt.Key_Return, Qt.Key_Escape):
        QTest.keyClick(window, isolated_key)
        assert draft_points(tab, kind) == points
    click(window, find(window, 'workspaceTab-' + tab.tab_config.tab_id))
    assert workspace.activeTab is tab
    assert_draft_visible(window, tab, kind)
    QTest.keyClick(window, key)
    assert_finished(window, tab, kind, key)
    assert not other.activeViewport.measurementController.committed_measurements
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('kind', ['cpr', '2d'])
@pytest.mark.parametrize('key', [Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter])
def test_workspace_popup_closes_before_drawing_command_resumes(sidebar_scene, kind, key):
    # Popup Escape must not also cancel; subsequent commands must reach the draft.
    window, _, tab = start_draft(sidebar_scene, kind, key)
    points = 3 if kind == '2d' and key != Qt.Key_Escape else 2
    dialog, surface = workspace_dialog(window)
    assert window.property('shortcutPopupOpen')
    QTest.keyClick(surface, Qt.Key_Escape)
    wait_until(lambda: not dialog.property('visible'))
    assert draft_points(tab, kind) == points
    window.requestActivate()
    wait_until(lambda: window.property('standardShortcutsAllowed'))
    assert_draft_visible(window, tab, kind)
    QTest.keyClick(window, key)
    assert_finished(window, tab, kind, key)
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('kind', ['cpr', '2d'])
@pytest.mark.parametrize('key', [Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter])
def test_focused_image_drawing_command_commits_once_or_cancels(sidebar_scene, kind, key):
    # Adding a window route must preserve the canvas's existing keyboard path.
    window, _, tab = start_draft(sidebar_scene, kind, key)
    QTest.keyClick(window, key)
    assert_finished(window, tab, kind, key)
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('kind', ['cpr', '2d'])
def test_text_input_keeps_drawing_commands_local(sidebar_scene, kind):
    # Window routing without the editingText guard would finish/cancel here.
    window, _, tab = start_draft(sidebar_scene, kind, Qt.Key_Return)
    points = 2 if kind == 'cpr' else 3
    field = find(window, 'sidebarPatientSearch')
    click(window, field)
    assert field.hasActiveFocus()
    for key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
        QTest.keyClick(window, key)
        assert draft_points(tab, kind) == points
    assert_draft_visible(window, tab, kind)
    assert not sidebar_scene[3], sidebar_scene[3]
