"""Compact sidebar interaction and stability with real QML delegates."""
from dataclasses import replace
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from voxplane.model import DicomFolderScanSnapshot
from voxplane.service.thumbnail_service import ThumbnailRequest
from test_series_sidebar import sidebar_scene, right_click, drag_width
from test_tag_qml import find, click, descendants
from test_dicom_tags import qt_app, wait_until


def test_compact_context_keeps_selection_and_targets_clicked_series(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    panel, ws = app.panelController, app.workspaceController
    uids = [s.series_instance_uid for s in records]
    # Group folding should not make the compact rail lose those series.
    group = next(row for row in panel.sidebarItems if row['kind'] == 'patient')
    panel.toggleGroup(group['key'])
    click(window, find(window, 'sidebarToggle'))
    assert panel.compactSidebarModel.rowCount() == 3
    listing = find(window, 'compactSidebarSeriesList')
    for uid in uids:
        assert find(window, 'compactThumbnail-' + uid).property('paintedWidth') > 0
    first = find(window, 'compactSeries-' + uids[0])
    right_click(window, first)
    assert panel.selectedSeriesUids == [uids[0]]
    click(window, find(window, 'seriesContextAction-tag'))
    wait_until(lambda: ws.activeTabType == 'tag' and not ws.activeTab.tagController.loading)
    original_tab = ws.activeTab
    panel.selectSeriesWithModifiers(uids[2], True)
    panel.setPatientSearch('DEMO-A')
    QTest.qWait(50)
    assert listing.property('count') == 2
    target = find(window, 'compactSeries-' + uids[1])
    right_click(window, target)
    assert panel.selectedSeriesUids == [uids[0], uids[2]]
    click(window, find(window, 'seriesContextAction-tag'))
    wait_until(lambda: ws.activeTab is not original_tab and not ws.activeTab.tagController.loading)
    # Single-item actions use the context target even with another selection.
    assert len(ws.tabs) == 2
    right_click(window, target)
    assert window.grabWindow().save(str(tmp_path / 'compact-series-menu.png'))
    assert not any(i.objectName() == 'seriesContextAction-remove-selected' for i in descendants(window.contentItem()))
    click(window, find(window, 'seriesContextAction-remove'))
    assert [s['seriesInstanceUid'] for s in panel.seriesItems] == [uids[0], uids[2]]
    assert panel.selectedSeriesUids == [uids[0], uids[2]]
    assert len(ws.tabs) == 2 and all(s.first_file.exists() for s in records)
    click(window, find(window, 'sidebarClear'))
    assert panel.compactSidebarModel.rowCount() == 0
    assert find(window, 'compactSidebarImport').isEnabled()
    assert find(window, 'sidebarToggle').isVisible()
    assert not warnings, warnings


def test_compact_click_multiselect_double_click_and_restore(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    panel = app.panelController
    drag_width(window, 240)
    footer = find(window, 'sidebarSettingsFooter')
    center_y = footer.mapToScene(QPointF(0, footer.height()/2)).y()
    for name in ('sidebarExport', 'sidebarClear', 'sidebarManual', 'sidebarSettings', 'sidebarToggle'):
        button = find(window, name)
        assert button.mapToScene(QPointF(0, button.height()/2)).y() == pytest.approx(center_y)
    chevron = find(window, 'sidebarToggleChevron')
    assert chevron.mapToScene(QPointF(9, 9)).y() == pytest.approx(center_y)
    assert window.grabWindow().save(str(tmp_path / 'expanded-footer.png'))
    click(window, find(window, 'sidebarToggle'))
    first = find(window, 'compactSeries-' + records[0].series_instance_uid)
    second = find(window, 'compactSeries-' + records[1].series_instance_uid)
    click(window, first)
    pos = second.mapToScene(QPointF(second.width()/2, second.height()/2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.ControlModifier, pos)
    QTest.qWait(40)
    assert len(panel.selectedSeriesUids) == 2
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, pos)
    wait_until(lambda: app.workspaceController.activeTabType == '2d')
    wait_until(lambda: app.workspaceController.activeViewport.imageSource != '')
    assert window.grabWindow().save(str(tmp_path / 'compact-series-view.png'))
    footer_buttons = [find(window, name) for name in ('sidebarManual', 'sidebarSettings', 'sidebarToggle')]
    centers = [item.mapToScene(QPointF(item.width()/2, item.height()/2)) for item in footer_buttons]
    assert chevron.mapToScene(QPointF(9, 9)) == centers[2]
    assert centers[0].x() == centers[1].x() == centers[2].x()
    assert centers[1].y()-centers[0].y() == centers[2].y()-centers[1].y() == 36
    click(window, footer_buttons[0])
    wait_until(lambda: app.workspaceController.activeTabType == 'manual')
    click(window, footer_buttons[1])
    wait_until(lambda: app.workspaceController.activeTabType == 'settings')
    assert find(window, 'sidebarContainer').width() == 52
    click(window, find(window, 'compactSidebarPacs'))
    wait_until(lambda: app.workspaceController.activeTabType == 'pacs')
    click(window, find(window, 'sidebarToggle'))
    assert find(window, 'sidebarContainer').width() == 240
    assert not warnings, warnings


def test_compact_thumbnail_and_structure_updates_preserve_scroll(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    panel = app.panelController
    many = [replace(records[0], series_instance_uid=f'1.6.{i+1}', series_number=i+1,
                    patient_id=f'P{i//20}', study_instance_uid=f'1.7.{i//20}') for i in range(140)]
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 140, 140, 0, many))
    panel._thumbnail_timer.stop()
    click(window, find(window, 'sidebarToggle'))
    window.resize(1000, 600)
    QTest.qWait(40)
    listing = find(window, 'compactSidebarSeriesList')
    listing.setProperty('contentY', 1600)
    QTest.qWait(40)
    anchor = next(i for i in descendants(window.contentItem()) if i.objectName().startswith('compactSeries-')
                  and 0 <= i.mapToItem(listing, QPointF()).y() < listing.height()-46)
    name, y = anchor.objectName(), anchor.mapToItem(listing, QPointF()).y()
    toggle = find(window, 'sidebarToggle')
    footer_y = toggle.mapToScene(QPointF()).y()
    changed, resets = [], []
    panel.compactSidebarModel.dataChanged.connect(lambda *args: changed.append(args))
    panel.compactSidebarModel.modelReset.connect(lambda: resets.append(True))
    image = QImage(12,12,QImage.Format_Grayscale8)
    image.fill(180)
    for record in many[:30]:
        panel._accept_thumbnail(ThumbnailRequest(record.series_instance_uid, record.instances[1].path), image)
        QTest.qWait(3)
        assert find(window, name) is anchor
        assert anchor.mapToItem(listing, QPointF()).y() == pytest.approx(y, abs=1)
    assert len(changed) == 30 and not resets
    added = replace(records[0], patient_name='AAA', patient_id='first', series_instance_uid='1.9.9')
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 1, 1, 0, [added]))
    panel._thumbnail_timer.stop()
    QTest.qWait(40)
    assert find(window, name).mapToItem(listing, QPointF()).y() == pytest.approx(y, abs=1)
    assert toggle.mapToScene(QPointF()).y() == footer_y
    click(window, toggle)
    click(window, find(window, 'sidebarToggle'))
    assert find(window, name).mapToItem(listing, QPointF()).y() == pytest.approx(y, abs=1)
    panel.setPatientSearch('P0')
    QTest.qWait(40)
    assert listing.property('contentY') == listing.property('originY')
    assert not warnings, warnings
