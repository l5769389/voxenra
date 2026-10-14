"""Replacing live viewports must keep their inherited interface visible to QML."""
import gc
from dataclasses import replace
from uuid import uuid4

from PySide6.QtQml import QQmlEngine, QJSValue
from shiboken6 import delete, getCppPointer

from qt_dicom_viewer.model import MprPlane, TwoDViewType
from qt_dicom_viewer.ui.controller.tab.two_d_tab_controller import PlaneViewportController
from qt_dicom_viewer.ui.controller.viewport.image_2d.stack_viewport_controller import StackViewportController
from test_compare_2d import comparison
from test_dicom_tags import qt_app
from test_two_d_layout import open_scene


def test_replaced_viewports_keep_qml_properties_and_resize_slot(comparison):
    app, records = comparison
    tab, _ = open_scene(app, records)
    template = tab.activeViewport.viewport_config
    engine = QQmlEngine()
    try:
        for index in range(100):
            plane = index % 2 == 1
            controller = PlaneViewportController if plane else StackViewportController
            kind = MprPlane.AXIAL if plane else TwoDViewType.STACK
            view = controller(replace(template, viewport_id=str(uuid4()), viewport_type=kind),
                              tab.toolController, parent=tab)
            try:
                # QML caches type interfaces by metaobject address. A per-instance
                # dynamic type can reuse a deleted type's cached interface.
                assert getCppPointer(view.metaObject()) == getCppPointer(type(view).staticMetaObject), index
                roi = engine.newQObject(view.measurementController)
                assert not roi.property('measurementItems').isUndefined(), index
                annotations = engine.newQObject(view._text_annotation_controller)
                assert not annotations.property('annotationItems').isUndefined(), index
                wrapped = engine.newQObject(view)
                assert wrapped.property('viewportType').toString() == ('axial' if plane else 'stack'), index
                resize = wrapped.property('setViewportSize')
                assert resize.isCallable(), index
                result = resize.call([QJSValue(320), QJSValue(240)])
                assert not result.isError(), result.toString()
                assert (view._state.width, view._state.height) == (320, 240)
                assert wrapped.property('viewportId').toString() == view.viewportId, index
                assert not wrapped.property('overlayInfo').isUndefined(), index
                assert not wrapped.property('settingsController').isUndefined(), index
            finally:
                view.shutdown()
                delete(view)
                del view
            del wrapped, resize, result, roi, annotations
            gc.collect()
    finally:
        delete(engine)
