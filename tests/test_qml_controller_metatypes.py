"""Restored analysis controllers retain their interface in a live QML engine."""
import pytest
from PySide6.QtQml import QQmlEngine
from PySide6.QtTest import QSignalSpy
from shiboken6 import delete, getCppPointer

from qt_dicom_viewer.ui.controller.viewport.controller.mtf_controller import MtfController
from qt_dicom_viewer.ui.controller.viewport.controller.fwhm_controller import FwhmController
from test_dicom_tags import qt_app


@pytest.mark.parametrize('controller_type,method', [(MtfController, 'bead'), (FwhmController, 'ramp')])
def test_analysis_qml_interface_survives_controller_replacement(qt_app, controller_type, method):
    engine = QQmlEngine()
    try:
        for generation in range(100):
            controller = controller_type()
            roi = analysis = None
            try:
                # QML caches interfaces by metaobject address. Every signal
                # receiver must be declared so instances share a stable type.
                assert getCppPointer(controller.metaObject()) == getCppPointer(controller_type.staticMetaObject), generation
                # The result panel and viewport expose both the analysis and
                # its ROI. Reopening replaces these objects in the same engine.
                roi = engine.newQObject(controller.roiController)
                roi.property('measurementItems')
                analysis = engine.newQObject(controller)
                assert analysis.property('status').toString() == 'empty', generation
                assert analysis.property('measurementMethod').toString() == method
                assert analysis.property('currentResult').toVariant() == {}
                assert analysis.property('stateSnapshot').property('status').toString() == 'empty'
                assert analysis.property('stateChanged').isCallable()
                assert analysis.property('applyRoi').isCallable()

                changed = QSignalSpy(controller.stateChanged)
                assert controller.settingsController.setValue('services', 'mtfFrequencyUnit', 'lp/cm')
                assert changed.count() == 1
                assert analysis.property('frequencyUnit').toString() == 'lp/cm'
            finally:
                controller.shutdown()
                delete(controller)
                del controller, roi, analysis
    finally:
        delete(engine)
