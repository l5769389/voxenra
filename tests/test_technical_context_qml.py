"""Technical frame context survives privacy/export without identifying metadata."""
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete
from test_cpr_controller import qt_app
from test_cpr_persistence import cpr_app
from test_cpr_qml import displayed_cpr_page, named_item
from test_dicom_tags import wait_until
from test_workspace_persistence import draw_length


def test_anonymous_historical_cpr_keeps_saved_technical_context(cpr_app, tmp_path):
    _, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    tab.renamePath('SECRET PATIENT PATH')
    measurement = draw_length(cross)
    source = cross.measurementController._sources[measurement]
    saved_distance = source['cpr']['distanceMm']
    source['cpr']['pathIndex'] = 'SECRET injected path index'
    tab.setPositionMm(tab.totalLength * .8)
    wait_until(lambda: tab.ready and not tab.busy)
    tab.navigate_measurement(cross, source)
    wait_until(lambda: cross.historicalPlane)
    with displayed_cpr_page(tab) as (window, _):
        window.rootObject().setProperty('anonymousExport', True)
        QTest.qWait(60)
        viewport = named_item(window.rootObject(), 'cprViewport-cross')
        overlay = named_item(viewport, 'viewportMetadataOverlay')
        assert overlay.isVisible()
        left = named_item(viewport, 'overlay-topLeft').property('text')
        right = named_item(viewport, 'overlay-topRight').property('text')
        assert 'CROSS-SECTION' in left and f's: {saved_distance:.1f} mm' in left
        assert QCoreApplication.translate('', 'cpr.statusHistoricalPlane') in right and 'Path 1' in right and 'r1' in right
        assert 'SECRET' not in left + right
        assert named_item(viewport, 'overlay-bottomLeft').property('text') == ''
        grab = viewport.grabToImage()
        wait_until(lambda: not grab.image().isNull())
        assert grab.saveToFile(str(tmp_path / 'historical-anonymous.png'))


@pytest.mark.parametrize("anonymous", [False, True])
def test_four_d_context_follows_accepted_frame_and_survives_privacy(qt_app, tmp_path, anonymous):
    from test_four_d_qml import _controller
    from test_four_d import _finish_requests
    from qt_dicom_viewer.model import MprFrame
    controller = _controller()
    requests = []
    controller.renderRequested.connect(requests.append)
    controller.init_render()
    frame = MprFrame.standard_lps((10., 20., 30.))
    _finish_requests(controller, requests, frame)
    viewport = controller.activeViewport
    assert viewport.overlayInfo['phaseNumber'] == 1
    controller.setPhaseIndex(1)
    assert viewport.overlayInfo['phaseNumber'] == 1
    _finish_requests(controller, requests, frame)
    assert viewport.overlayInfo['phaseNumber'] == 2
    view = QQuickView()
    view.resize(600, 400)
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    provider = DicomImageProvider()
    viewport.imageUpdateRequested.connect(provider.set_array)
    view.engine().addImageProvider("dicom", provider)
    view.engine().addImageProvider("navigation", SvgIconProvider())
    viewport.refresh_window_image()
    view.setInitialProperties(dict(viewportController=viewport, hasTabs=True, anonymousExport=anonymous))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/center/viewportArea/Viewport.qml')))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    try:
        QTest.qWait(60)
        right = named_item(view.rootObject(), 'overlay-topRight').property('text')
        assert right.startswith('Phase: 2 / 6')
        if anonymous:
            assert right == 'Phase: 2 / 6'
        else:
            assert '4D Example' in right
        if anonymous:
            for name in ('overlay-topLeft', 'overlay-bottomLeft', 'overlay-bottomRight'):
                assert named_item(view.rootObject(), name).property('text') == ''
        assert view.grabWindow().save(str(tmp_path / 'phase2-anonymous.png'))
    finally:
        controller.pausePlayback()
        view.hide()
        delete(view)
