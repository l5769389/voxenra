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
