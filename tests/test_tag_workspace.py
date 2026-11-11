"""Restore the visible metadata browser without loading image pixels."""
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from voxplane.core.workspace_document import FORMAT, validate_document
from test_dicom_tags import qt_app, rows, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, descendants, find, type_text


def test_reopen_and_load_workspace_restore_tag_browser(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    ws, doc = app.workspaceController, app.workspaceDocumentController
    requests = []
    ws.renderRequested.connect(requests.append)
    app.panelController.openSeriesView(records[0].series_instance_uid, 'tag')
    tags = ws.activeTab.tagController
    wait_until(lambda: not tags.loading)
    tags.setPage(2)
    wait_until(lambda: not tags.loading)
    sequence = 'dataset/0040A043'
    tags.toggleNode(sequence)
    type_text(window, find(window, 'tagSearch'), '0')
    view = find(window, 'tagList')
    view.setProperty('contentY', 420)
    QTest.qWait(50)
    visible_row = next(item for item in descendants(view) if item.objectName().startswith('tagRow-')
                       and 0 < item.mapToItem(view, QPointF(0, item.height() / 2)).y() < view.height())
    click(window, visible_row)
    selected = visible_row.property('nodeId')
    assert tags.selectedNodeId == selected
    assert tags.scrollPosition == pytest.approx(420)
    path = tmp_path / 'metadata.voxworkspace'
    assert doc.save_to(path)
    wait_until(lambda: not doc.busy)
    assert not doc.isError, doc.message

    assert ws.closeTab(ws.activeTabId)
    assert doc.closedTabCount == 1
    for operation, restore in [('reopen', doc.reopenLastClosed), ('load', lambda: doc.restore_from(path))]:
        assert restore()
        wait_until(lambda: not doc.busy)
        assert not doc.isError, doc.message
        tags = ws.activeTab.tagController
        assert not tags.loading and tags.currentPage == 2
        assert find(window, 'tagSearch').property('text') == '0'
        wait_until(lambda: abs(find(window, 'tagList').property('contentY') - 420) < 1)
        assert find(window, 'tagRow-' + selected).property('selected')
        assert window.grabWindow().save(str(tmp_path / f'tag-{operation}.png'))
        tags.setSearchText('')
        assert any(r['nodeId'] == sequence and r['expanded'] for r in rows(tags.tagModel))
    assert not requests and not warnings, warnings


def test_failed_saved_instance_read_keeps_tag_in_closed_history(sidebar_scene):
    _, app, records, _ = sidebar_scene
    ws, doc = app.workspaceController, app.workspaceDocumentController
    app.panelController.openSeriesView(records[0].series_instance_uid, 'tag')
    tags = ws.activeTab.tagController
    wait_until(lambda: not tags.loading)
    tags.setPage(2)
    wait_until(lambda: not tags.loading)
    path = Path(tags.filePath)
    contents = path.read_bytes()
    assert ws.closeTab(ws.activeTabId)
    path.unlink()
    assert doc.reopenLastClosed()
    wait_until(lambda: not doc.busy)
    assert doc.isError and doc.closedTabCount == 1
    path.write_bytes(contents)
    assert doc.reopenLastClosed()
    wait_until(lambda: not doc.busy)
    assert not doc.isError and doc.closedTabCount == 0
    assert ws.activeTab.tagController.currentPage == 2


@pytest.mark.parametrize('version', [1, 2])
def test_tag_snapshot_schema_accepts_old_workspaces_and_rejects_invalid_state(version):
    tab = {'type': 'tag', 'label': 'Tags', 'series': ['s']}
    manifest = {'format': FORMAT, 'version': version, 'tabs': [tab],
                'series': [{'uid': 's', 'sources': [{'path': 'a', 'relative': 'a'}],
                            'instances': [{'sop_instance_uid': 's.1'}]}]}
    assert validate_document(manifest)['tabs'] == [tab]
    for bad in [None, {'page': True}, {'page': -1}, {'page': 2}, {'query': []}, {'scroll': float('nan')},
                {'scroll': -1}, {'selected': False}, {'expanded': 'id'}, {'expanded': [2]}]:
        with pytest.raises(ValueError):
            validate_document(dict(manifest, tabs=[dict(tab, tag=bad)]))
