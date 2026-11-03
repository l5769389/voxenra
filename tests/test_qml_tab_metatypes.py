"""Recreated QML controllers retain stable declared metaobjects after connections."""
from dataclasses import replace

import pytest
from PySide6.QtQml import QQmlEngine
from shiboken6 import delete, getCppPointer

from qt_dicom_viewer.model import TabConfig, TabType
from qt_dicom_viewer.ui.controller.tab.tab_controller import TabController
from qt_dicom_viewer.ui.controller.tab.pet_workspace_controller import PetWorkspaceController
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.tab.mpr_voi_controller import MprVoiController
from qt_dicom_viewer.ui.controller.tab.compare_tab_controller import CompareTabController
from qt_dicom_viewer.ui.controller.tab.compare_mpr_tab_controller import CompareMprTabController
from qt_dicom_viewer.ui.controller.manual_tab_controller import ManualTabController
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.viewport.controller.measure.measure_controller import MeasurementController
from test_dicom_tags import qt_app
from test_pet_fusion import paired_series
from test_viewport_controller_hierarchy import _series_meta


def _consumer(kind, series):
    if kind == 'manual':
        obj = ManualTabController(settings=SettingsController(path=False))
        return obj, obj, 'chapterId', 'isString'
    if kind == 'measurement':
        obj = MeasurementController()
        return obj, obj, 'selectedMeasurementId', 'isString'
    if kind == 'voi':
        tools = ToolController(tab_type=TabType.MPR, modality='CT')
        obj = MprVoiController(tools, tools)
        return tools, obj, 'brushDiameter', 'isNumber'
    ct = _series_meta()
    if kind in ('compare', 'compare-mpr'):
        metas = (ct, replace(ct, series_uid='series-2'))
        cls, tab_type = ((CompareTabController, TabType.COMPARE_2D) if kind == 'compare'
                         else (CompareMprTabController, TabType.COMPARE_MPR))
        owner = cls(TabConfig('compare-tab', 'Comparison', tab_type, metas))
        return owner, owner, 'activeTool', 'isString'
    if kind == 'pet':
        catalog, ct_record, pet_record = series
        metas = tuple(catalog.get_series_display_meta(record.series_instance_uid)
                      for record in (ct_record, pet_record))
        owner = PetWorkspaceController(TabConfig('pet-tab', 'PET', TabType.PETCT_FUSION, metas),
                                       ct_series=ct_record, pet_series=pet_record)
        return owner, owner, 'ready', 'isBool'
    owner = TabController(TabConfig('mpr-tab', 'MPR', TabType.MPR, (ct,)))
    if kind == 'results':
        return owner, owner.measurementResults, 'message', 'isString'
    if kind == 'layout':
        return owner, owner.mprLayout, 'layout', 'isString'
    return owner, owner, 'activeTool', 'isString'


@pytest.mark.parametrize('kind', ['measurement', 'voi', 'tab', 'layout', 'pet', 'results',
                                 'manual', 'compare', 'compare-mpr'])
def test_recreated_controllers_keep_qml_properties_and_declared_metaobject(qt_app, paired_series, kind):
    engine = QQmlEngine()
    declared_pointer = declared_count = None
    try:
        for _ in range(25):
            owner, controller, property_name, predicate = _consumer(kind, paired_series)
            try:
                if declared_pointer is None:
                    declared = type(controller).staticMetaObject
                    declared_pointer = getCppPointer(declared)
                    declared_count = declared.methodCount()
                value = engine.newQObject(controller).property(property_name)
                assert getattr(value, predicate)(), f'{kind}.{property_name} became inaccessible to QML'
                # Undeclared Python signal receivers create instance-owned
                # metadata. Its freed address can alias another QML class cache.
                meta = controller.metaObject()
                dynamic = [bytes(meta.method(i).methodSignature()).decode()
                           for i in range(declared_count, meta.methodCount())]
                assert getCppPointer(meta) == declared_pointer, dynamic
            finally:
                if kind == 'voi':
                    controller.dispose()
                elif isinstance(owner, TabController):
                    owner.dispose()
                delete(owner)
    finally:
        delete(engine)


def test_recreated_cpr_and_two_d_tabs_keep_layout_and_loading_interfaces(qt_app):
    from qt_dicom_viewer.ui.controller.tab.cpr_tab_controller import CprTabController
    from qt_dicom_viewer.ui.controller.tab.two_d_tab_controller import TwoDTabController
    from qt_dicom_viewer.ui.controller.tab_loading_controller import TabLoadingController

    engine = QQmlEngine()
    try:
        for generation in range(50):
            cpr = generation % 2 == 0
            cls, kind = (CprTabController, TabType.CPR) if cpr else (TwoDTabController, TabType.TWO_D)
            tab = cls(TabConfig('tab', 'Reading', kind, (_series_meta(),)))
            loading = TabLoadingController(tab)
            if cpr:
                tab.cprLoaded.connect(loading.finish)
            try:
                # The loading state is exposed in the workspace. Its signal
                # receiver must not create metadata that disappears with a tab.
                controllers = [tab, loading, *(view._point_click for view in tab.viewports_by_id.values())]
                for controller in controllers:
                    assert getCppPointer(controller.metaObject()) == getCppPointer(type(controller).staticMetaObject), type(controller).__name__
                opened = engine.newQObject(loading)
                assert opened.property('status').toString() == 'loading'
                exposed = engine.newQObject(tab)
                if cpr:
                    assert exposed.property('cprController').toQObject() is tab
                    tab.cprLoaded.emit()
                    assert opened.property('status').toString() == 'ready'
                else:
                    layout = exposed.property('twoDLayout')
                    assert layout.toQObject() is tab.twoDLayout
                    assert layout.property('cells').property('length').toInt() == 1
                    assert exposed.property('activeViewport').toQObject() is tab.activeViewport
            finally:
                tab.dispose()
                delete(tab)
    finally:
        delete(engine)



def test_recreated_app_tree_retains_declared_qml_interfaces(qt_app, tmp_path):
    from PySide6.QtCore import QObject
    from PySide6.QtQml import QQmlProperty
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from test_dicom_tags import wait_until
    from test_series_sidebar import phantom_series

    engine = QQmlEngine()

    def check_tree(app):
        for controller in [app, *app.findChildren(QObject)]:
            cls = type(controller)
            if cls.__module__.startswith('qt_dicom_viewer'):
                assert getCppPointer(controller.metaObject()) == getCppPointer(cls.staticMetaObject), cls.__name__

    try:
        # Applications/engines are recreated in embedded use and UI fixtures.
        # The same metadata invariant also protects ordinary per-tab lifetimes.
        for generation in range(3):
            folder = tmp_path / str(generation)
            folder.mkdir()
            app = AppController(DicomImageProvider(), settings_path=folder / 'settings.json',
                                pacs_config_path=folder / 'pacs.json')
            try:
                check_tree(app)
                record = phantom_series(folder, 1, 'SYNTHETIC', '1.2.3.1', '20260903')
                snapshot = DicomFolderScanSnapshot(folder, 3, 3, 0, [record])
                panel = app.panelController
                panel.update_series_session(snapshot)
                panel._update_series_record(snapshot)
                check_tree(app)
                assert engine.newQObject(panel).property('sidebarModel').toQObject() is panel.sidebarModel
                workspace = app.workspaceController
                for kind in ('cpr', '2d', 'cpr', '2d'):
                    workspace.createTab(record.series_instance_uid, kind, kind)
                    wait_until(lambda: workspace.activeLoadState.status == 'ready')
                    tab = workspace.activeTab
                    name = 'cprController' if kind == 'cpr' else 'twoDLayout'
                    expected = tab if kind == 'cpr' else tab.twoDLayout
                    meta = tab.metaObject()
                    index = meta.indexOfProperty(name)
                    assert index >= 0
                    assert meta.property(index).read(tab) is expected
                    assert QQmlProperty.read(tab, name) is expected
                    assert engine.newQObject(tab).property(name).toQObject() is expected
                    check_tree(app)
                    workspace.closeTab(tab.tab_config.tab_id)
            finally:
                app.shutdown()
                delete(app)
            engine.collectGarbage()
    finally:
        delete(engine)
