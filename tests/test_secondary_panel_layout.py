"""Real QML controls remain inside the loaded panel at supported sidebar widths."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import descendants
from test_volume_panel_qml import panel as volume_panel
from test_volume_display import loaded_tab, volume
from test_four_d_qml import four_d_panel
from test_pet_fusion import paired_series


def check_controls(root, context):
    details = [i for i in descendants(root) if i.isVisible()
               and i.metaObject().indexOfProperty('loadedPanel') >= 0]
    assert details, context
    for detail in details:
        content = detail.property('loadedPanel')
        if content is None:
            continue
        for item in descendants(content):
            if not item.isVisible() or item.metaObject().indexOfProperty('checkable') < 0:
                continue
            pos = item.mapToItem(content, QPointF())
            assert pos.x() >= -1 and pos.x() + item.width() <= content.width() + 1, (context, item.objectName(), pos.x(), item.width(), content.width())
            assert pos.y() >= -1 and pos.y() + item.height() <= content.height() + 1, (context, item.objectName(), pos.y(), item.height(), content.height())


@pytest.mark.parametrize('kind', ['2d', 'mpr'])
def test_secondary_controls_at_supported_widths(sidebar_scene, kind):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', kind)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tools = ws.activeTab.toolController
    for locale in ['zh-CN', 'en-US']:
        app.languageController.selectLanguage(locale)
        for width in [240, 300, 420]:
            app.settingsController.setValue('layout', 'rightPanelWidth', width)
            for tool in ['window', 'scroll', 'zoom', 'mpr-layout', 'measure', 'annotate', 'rotate', 'pseudocolor',
                         'viewport-settings', 'segmentation', 'mip', 'service', 'import', 'export']:
                if not any(t['toolType'] == tool and t.get('available', True) for t in tools.tools):
                    continue
                tools.activateTool(tool)
                if tool == 'service':
                    tools.selectService('service:mtf')
                QTest.qWait(25)
                check_controls(window.contentItem(), (kind, locale, width, tool))
    assert not warnings, warnings


def test_volume_secondary_controls(volume_panel, tmp_path):
    view, controller, tools, warnings = volume_panel
    for width in [240, 300, 420]:
        view.resize(width, 720)
        for tool in ['window', 'volume-preset', 'volume-direction', 'volume-crop', 'viewport-settings', 'export']:
            tools.activateTool(tool)
            QTest.qWait(25)
            check_controls(view.rootObject(), ('3d', width, tool))
            if tool == 'volume-crop':
                items = list(descendants(view.rootObject()))
                help_button = next(i for i in items if i.objectName() == 'VolumeCropPanelHeadingHelp' and i.isVisible())
                first = next(i for i in items if i.objectName() == 'volumeCrop-inside' and i.isVisible())
                assert help_button.mapToScene(QPointF(0, help_button.height())).y() <= first.mapToScene(QPointF()).y()
            assert view.grabWindow().save(str(tmp_path / f'volume-{width}-{tool}.png'))
    assert not warnings, warnings


def test_four_d_secondary_controls(four_d_panel, tmp_path):
    view, tab, warnings = four_d_panel
    for width in [240, 300, 420]:
        view.resize(width, 720)
        for tool in ['play', 'slice-play', 'window', 'segmentation', 'mip', 'mpr-layout', 'viewport-settings']:
            tab.toolController.activateTool(tool)
            QTest.qWait(25)
            check_controls(view.rootObject(), ('4d', width, tool))
            assert view.grabWindow().save(str(tmp_path / f'four-d-{width}-{tool}.png'))
    assert not warnings, warnings


def test_pet_secondary_controls(qt_app, paired_series, tmp_path):
    from pathlib import Path
    from PySide6.QtCore import QUrl
    from PySide6.QtQuick import QQuickView
    from shiboken6 import delete
    from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
    from qt_dicom_viewer.ui.controller.language_controller import LanguageController
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    from qt_dicom_viewer.core.pet_reconstruction import PetReconstructor
    from qt_dicom_viewer.core.volume_manager import VolumeManager
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    requests = []
    workspace.renderRequested.connect(requests.append)
    workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    tab = workspace.activeTab
    tab.handleRenderResult(PetReconstructor(catalog, VolumeManager()).render(requests[-1]))
    assert tab.ready
    language = LanguageController(SettingsController(path=False), root=False)
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.engine().addImageProvider('navigation', SvgIconProvider())
    view.setInitialProperties(dict(toolController=tab.toolController, viewportController=tab.activeViewport,
                                   tabController=tab, toolVisible=True))
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    source = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/sections/RightPanel.qml'
    view.setSource(QUrl.fromLocalFile(str(source)))
    view.show()
    try:
        for locale in ['zh-CN', 'en-US']:
            language.selectLanguage(locale)
            view.engine().retranslate()
            for width in [240, 300, 420]:
                view.resize(width, 720)
                for tool in ['ct-window', 'pet-window', 'fusion-blend', 'registration', 'pseudocolor', 'viewport-settings']:
                    tab.toolController.activateTool(tool)
                    QTest.qWait(25)
                    check_controls(view.rootObject(), ('petct', locale, width, tool))
                    assert view.grabWindow().save(str(tmp_path / f'pet-{locale}-{width}-{tool}.png'))
        assert not warnings, warnings
    finally:
        view.hide()
        delete(view)
        workspace.shutdown()
