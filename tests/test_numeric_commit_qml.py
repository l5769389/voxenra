"""Numeric text drafts commit once and stay attached to their original target."""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_pet_fusion import paired_series
from test_pet_volume import fusion_scene
from test_standalone_pet_volume import pet_volume, ready as ready_pet_volume
from test_tag_qml import find, click, type_text


@pytest.fixture
def number_scene(qt_app, tmp_path):
    components = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/components'
    source = tmp_path / 'Numbers.qml'
    source.write_text('''import QtQuick
import "''' + components.as_uri() + '''" as Components
Rectangle {
    id: root
    function notifySameContext() { number.editContext = [root, "unitA"] }
    width: 300; height: 200
    property real value: 40
    property int commits: 0
    Components.AppNumberField {
        id: number
        editContext: [root, "unitA"]
        objectName: "number"; x: 10; y: 10; width: 150
        numberValue: parent.value; minimum: -1000; maximum: 1000; decimals: 2
        onEdited: value => { parent.value = value; parent.commits += 1 }
    }
    Components.AppTextField { objectName: "other"; x: 10; y: 70; width: 150 }
}''')
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    QTest.qWait(40)
    try:
        yield view, view.rootObject(), warnings
    finally:
        view.hide()
        delete(view)


def test_number_enter_and_focus_loss_commit_once(number_scene):
    view, root, warnings = number_scene
    field = find(view, 'number')
    type_text(view, field, '125')
    assert root.property('value') == 40
    assert root.property('commits') == 0
    QTest.keyClick(view, Qt.Key_Return)
    assert root.property('value') == 125
    assert root.property('commits') == 1
    click(view, find(view, 'other'))
    assert root.property('commits') == 1
    type_text(view, field, '250')
    assert root.property('value') == 125
    click(view, find(view, 'other'))
    assert root.property('value') == 250
    assert root.property('commits') == 2
    assert not warnings


def test_number_escape_invalid_and_model_change_discard_draft(number_scene):
    view, root, warnings = number_scene
    field = find(view, 'number')
    type_text(view, field, '125')
    QTest.keyClick(view, Qt.Key_Escape)
    assert field.property('text') == '40'
    click(view, find(view, 'other'))
    assert root.property('commits') == 0
    type_text(view, field, '-')
    click(view, find(view, 'other'))
    assert field.property('text') == '40'
    assert root.property('commits') == 0
    type_text(view, field, '125')
    root.setProperty('value', 60)
    assert field.property('text') == '60'
    click(view, find(view, 'other'))
    assert root.property('commits') == 0
    assert not warnings


def test_window_draft_does_not_follow_other_tab(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT A', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    a = ws.activeTab
    ws.createTab(records[1].series_instance_uid, 'CT B', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    b = ws.activeTab
    click(window, find(window, 'primaryTool-window'))
    type_text(window, find(window, 'windowWidthInput'), '1234')
    assert b.activeViewport.windowWidth == 400
    click(window, find(window, 'workspaceTab-' + a.tab_config.tab_id))
    field = find(window, 'windowWidthInput')
    assert field.property('text') == '400'
    assert window.grabWindow().save(str(tmp_path / 'window-draft-switched.png'))
    click(window, find(window, 'applyWindowValues'))
    assert a.activeViewport.windowWidth == 400
    assert b.activeViewport.windowWidth == 400
    assert not warnings, warnings


def test_number_equal_value_context_change_discards_draft(number_scene):
    view, root, warnings = number_scene
    field = find(view, 'number')
    type_text(view, field, '125')
    field.setProperty('editContext', 'another viewport with value 40')
    assert field.property('text') == '40'
    click(view, find(view, 'other'))
    assert root.property('commits') == 0
    assert not warnings


def test_window_equal_values_loading_transition_discards_draft(qt_app, tmp_path):
    panels = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/sections/right/panels'
    source = tmp_path / 'Window.qml'
    source.write_text('''import QtQuick
import "''' + panels.as_uri() + '''" as Panels
Rectangle {
    width: 320; height: 400
    property bool loaded: true
    property int target: 1
    Panels.WindowLevelToolPanel {
        objectName: "windowPanel"; width: parent.width
        presets: []; currentCenter: 40; currentWidth: 400
        contextReady: parent.loaded; editContext: parent.target
    }
}''')
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    QTest.qWait(40)
    try:
        root = view.rootObject()
        field = find(view, 'windowWidthInput')
        type_text(view, field, '1234')
        root.setProperty('loaded', False)
        assert field.property('text') == '400'
        root.setProperty('loaded', True)
        assert field.property('text') == '400'
        type_text(view, field, '1234')
        root.setProperty('target', 2)
        assert field.property('text') == '400'
        type_text(view, field, '1234')
        QTest.keyClick(view, Qt.Key_Escape)
        assert field.property('text') == '400'
        assert not warnings, warnings
    finally:
        view.hide()
        delete(view)


@pytest.fixture
def pet_numeric_panel(qt_app):
    views = []
    def create(controller, name):
        view = QQuickView()
        from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
        view.engine().addImageProvider('navigation', SvgIconProvider())
        view.resize(320, 600)
        warnings = []
        view.engine().warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        view.setInitialProperties({'controller': controller})
        source = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/sections/right/panels' / name
        view.setSource(QUrl.fromLocalFile(str(source)))
        assert view.status() == QQuickView.Ready, view.errors()
        view.show()
        QTest.qWait(40)
        views.append(view)
        return view, warnings
    yield create
    for view in views:
        view.hide()
        delete(view)


@pytest.mark.parametrize('name, draft', [('pet3dUpper', '123'), ('pet3dThreshold', '2')])
def test_real_standalone_pet_volume_drops_draft_during_unit_load(pet_volume, pet_numeric_panel, name, draft, tmp_path):
    controller = ready_pet_volume(pet_volume)
    workspace, _, requests, worker, _ = pet_volume
    view, warnings = pet_numeric_panel(controller, 'StandalonePetVolumePanel.qml')
    field = find(view, name)
    original = controller.petUpper, controller.petThreshold
    type_text(view, field, draft)
    assert (controller.petUpper, controller.petThreshold) == original
    controller.setPetUnit('kbqml')
    assert controller.loadState == 'loading'
    assert not field.isEnabled()
    assert field.property('text') != draft
    QTest.keyClick(view, Qt.Key_Return)
    assert (controller.petUpper, controller.petThreshold) == original
    assert view.grabWindow().save(str(tmp_path / (name + '-loading.png')))
    worker.handleRenderRequest(requests[-1])
    assert controller.loadState == 'ready' and controller.petUnitId == 'kbqml'
    assert field.isEnabled()
    assert field.property('text') == str(round(controller.petUpper if name == 'pet3dUpper' else controller.petThreshold, 6)).removesuffix('.0')
    assert not warnings, warnings


def test_real_fusion_volume_load_and_equal_range_unit_change_drop_draft(fusion_scene, pet_numeric_panel):
    workspace, source, renderer, requests = fusion_scene
    source.openVolumeView()
    controller = workspace.activeViewport
    view, warnings = pet_numeric_panel(controller, 'PetVolumePanel.qml')
    field = find(view, 'fusionVolumePetThreshold')
    original = controller.petUpper, controller.petThreshold
    type_text(view, field, '2')
    controller._set_status('loading')
    assert not field.isEnabled()
    assert field.property('text') != '2'
    QTest.keyClick(view, Qt.Key_Return)
    assert (controller.petUpper, controller.petThreshold) == original
    controller._set_status('ready')
    type_text(view, field, '2')
    source.petController.setPetUnit('kbqml')
    source.petController.setPetDisplayUpper(original[0])
    source.handleRenderResult(renderer.render(requests[-1]))
    assert controller.petUnitId == 'kbqml'
    assert (controller.petUpper, controller.petThreshold) == pytest.approx(original)
    assert field.property('text') == str(round(original[1], 3)).removesuffix('.0')
    assert not warnings, warnings


@pytest.mark.parametrize('property_name', ['enabled', 'visible'])
def test_number_becoming_unavailable_discards_instead_of_committing(number_scene, property_name):
    view, root, warnings = number_scene
    field = find(view, 'number')
    type_text(view, field, '125')
    field.setProperty(property_name, False)
    assert root.property('value') == 40
    assert root.property('commits') == 0
    assert field.property('text') == '40'
    field.setProperty(property_name, True)
    assert root.property('value') == 40
    assert not warnings, warnings


def test_number_equivalent_context_array_notification_preserves_draft(number_scene):
    from PySide6.QtCore import QMetaObject
    view, root, warnings = number_scene
    field = find(view, 'number')
    type_text(view, field, '125')
    QMetaObject.invokeMethod(root, 'notifySameContext')
    assert field.property('text') == '125'
    assert root.property('value') == 40 and root.property('commits') == 0
    QTest.keyClick(view, Qt.Key_Return)
    assert root.property('value') == 125 and root.property('commits') == 1
    assert not warnings, warnings
