"""Audit regressions: actual keyboard edits must preserve accepted CPR geometry."""
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete
from test_cpr_controller import cpr, qt_app, draw
from test_dicom_tags import wait_until
from test_tag_qml import find, click, type_text


@pytest.fixture
def parameter_scene(cpr, tmp_path):
    draw(cpr)
    panels = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/sections/right/panels'
    source = tmp_path / 'Parameter.qml'
    source.write_text('''import QtQuick
import "''' + panels.as_uri() + '''" as Panels
Rectangle {
    required property var controller
    width: 300; height: 150
    Panels.CprParameterField { width: parent.width; controller: parent.controller; parameter: "width" }
    Panels.CprParameterField { y: 70; width: parent.width; controller: parent.controller; parameter: "angle" }
}''')
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setInitialProperties(dict(controller=cpr))
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    QTest.qWait(40)
    try:
        yield view, cpr
    finally:
        view.hide()
        delete(view)


def test_two_decimal_parameter_survives_enter_blur_and_refocus(parameter_scene):
    view, tab = parameter_scene
    field = find(view, 'cprParameter-width')
    type_text(view, field, '12.34')
    QTest.keyClick(view, Qt.Key_Return)
    wait_until(lambda: tab.ready)
    assert tab.parameters['width'] == 12.34
    assert float(field.property('text')) == 12.34
    for _ in range(2):
        click(view, find(view, 'cprParameter-angle'))
        click(view, field)
    wait_until(lambda: tab.ready)
    assert tab.parameters['width'] == 12.34
    assert tab._result.curve.settings.width_mm == 12.34


def test_empty_parameter_blur_restores_actual_model(parameter_scene):
    view, tab = parameter_scene
    field = find(view, 'cprParameter-width')
    original = tab.parameters['width']
    type_text(view, field, '')
    QTest.keyClick(view, Qt.Key_Return)
    click(view, find(view, 'cprParameter-angle'))
    assert field.property('text') != ''
    assert float(field.property('text')) == original
    assert tab.parameters['width'] == original
    assert tab.ready


def test_export_progress_cancel_and_result_location_are_operable(qt_app, tmp_path):
    panels = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/sections/right/panels'
    source = tmp_path / 'Export.qml'
    source.write_text('''import QtQuick
import "''' + panels.as_uri() + '''" as Panels
Rectangle {
    id: root
    width: 320; height: 500
    property bool busy: true
    property real progress: 0.4
    property string message: "Exporting"
    property string resultPath: ""
    property bool isError: false
    property bool canExportPng: !busy
    property string exportScope: "combined"
    property int cancelled: 0
    property int revealed: 0
    function cancel() { cancelled++; busy = false }
    function openResultLocation() { revealed++ }
    Panels.CprExportPanel { width: parent.width; controller: root; exportController: root; exportItem: root }
}''')
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    QTest.qWait(400)
    try:
        progress = find(view, 'cprExportProgress')
        assert progress.isVisible() and progress.property('value') == .4
        click(view, find(view, 'cprExportCancel'))
        assert view.rootObject().property('cancelled') == 1
        assert not progress.isVisible()
        view.rootObject().setProperty('resultPath', '/tmp/example.png')
        link = find(view, 'cprExportResultPath')
        assert link.isVisible() and link.property('text') == '/tmp/example.png'
        click(view, link)
        assert view.rootObject().property('revealed') == 1
    finally:
        view.hide()
        delete(view)


def test_tab_insertion_clamps_stale_indices_on_list_shrink(qt_app, tmp_path):
    center = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/sections/center'
    source = tmp_path / 'Tabs.qml'
    source.write_text('''import QtQuick
import "''' + center.as_uri() + '''" as Center
Rectangle {
    width: 600; height: 100
    property var tabs: []
    property string activeTabId: ""
    property var windowManager: null
    signal activeTabChanged()
    Center.TabBarSection { id: bar; width: parent.width; workspaceController: parent }
    function staleOffset() { return bar.insertionOffset(15) }
    function emptyWidth() { return bar.widthForTab(undefined) }
}''')
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, view.errors()
    try:
        assert view.rootObject().staleOffset() == 0
        assert view.rootObject().emptyWidth() > 0
        assert not warnings
    finally:
        delete(view)

from test_series_sidebar import sidebar_scene
from test_pet_fusion import paired_series


@pytest.mark.parametrize("view_type", ["3d", "mpr"])
def test_fusion_picker_above_native_volume_cancel_and_confirm(sidebar_scene, paired_series, tmp_path, view_type):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtCore import QPointF
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from test_measurement_qml import _visual_children
    from qt_pointer import move_pointer
    if QGuiApplication.platformName() == 'offscreen':
        pytest.skip('Requires native VTK child windows')
    window, app, _, warnings = sidebar_scene
    _, ct, pet = paired_series
    snapshot = DicomFolderScanSnapshot(tmp_path, 2, 2, 0, [ct, pet])
    panel = app.panelController
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    registry = app.workspaceController
    registry.createTab(ct.series_instance_uid, 'Synthetic CT', view_type)
    wait_until(lambda: registry.activeLoadState.status == 'ready', timeout=20000)
    if view_type == 'mpr':
        registry.activeTab.mprLayout.setLayout('quad')
        wait_until(lambda: registry.activeTab.mprLayout.volumeViewport.loadState == 'ready', timeout=20000)
        assert registry.activeViewport.viewportType != 'volume'
    panel.selectSeries(ct.series_instance_uid)

    def popup_window():
        return next((w for w in QGuiApplication.topLevelWindows()
                     if w is not window and isinstance(w, QQuickWindow) and w.isVisible()
                     and any(i.objectName() == 'confirmFusion' for i in _visual_children(w.contentItem()))), None)

    def press(popup, name):
        item = find(popup, name)
        move_pointer(popup, item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint())
        click(popup, item)

    for confirm in (False, True):
        panel.requestFusionView()
        wait_until(lambda: popup_window() is not None)
        popup = popup_window()
        wait_until(popup.isExposed)
        QTest.qWait(100)
        assert not popup.flags() & Qt.FramelessWindowHint
        assert popup.height() == 640
        assert find(popup, "fusionCandidates").height() >= 100
        assert popup.grabWindow().save(str(tmp_path / f'fusion-over-3d-{confirm}.png'))
        # Screen capture includes the VTK native child and the picker's stacking.
        import subprocess, sys
        if sys.platform == 'darwin':
            subprocess.run(['/usr/sbin/screencapture', '-x', str(tmp_path / f'fusion-desktop-{confirm}.png')], check=True)
        if confirm:
            press(popup, 'fusionCandidate-' + pet.series_instance_uid)
            press(popup, 'confirmFusion')
            wait_until(lambda: registry.activeTabType == 'petctfusion' and registry.activeLoadState.status == 'ready', timeout=20000)
        else:
            press(popup, 'cancelFusion')
            assert registry.activeTabType == view_type
        assert not panel.fusionDialogOpen
    assert not warnings, warnings
