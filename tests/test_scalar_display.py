import numpy as np
from PySide6.QtCore import QSize
from voxplane.model import WindowLevel
from voxplane.core.scalar_display import ScalarDisplayFrame, pack_scalar, unpack_scalar, resample_display


def test_scalar_interpolation_precedes_window_clipping():
    frame = ScalarDisplayFrame(np.array([[-50.,-302.],[-50.,-302.]],dtype=np.float32),WindowLevel(-30,200))
    image = resample_display(frame, 3, 3)
    assert image[1,1] == 0  # gray-first interpolation would incorrectly produce 51
    assert image[1,0] == 102
    np.testing.assert_array_equal(frame.pixels, [[-50,-302],[-50,-302]])


def test_packed_texture_precision_padding_and_byte_boundaries():
    rng = np.random.default_rng(5)
    p = rng.uniform(-1024,60000,(160,200)).astype(np.float32)
    p[0,0]=np.nan
    encoded, lower, span = pack_scalar(p)
    decoded = unpack_scalar(encoded,lower,span)
    assert np.isnan(decoded[0,0])
    np.testing.assert_allclose(decoded[1:],p[1:],atol=.004,rtol=0)
    # Grayscale mapping and LUT follow the same scalar path in software fallback.
    f=ScalarDisplayFrame(p,WindowLevel(0,350),True,'hotIron')
    result = resample_display(f,241,189)
    assert result.shape == (189,241,3)


def test_provider_uses_scalar_sampling_and_cleans_up():
    from voxplane.ui.dicom_image_provider import DicomImageProvider
    from dataclasses import replace
    p = DicomImageProvider()
    values = np.array([[-50.,-302.],[-50.,-302.]],dtype=np.float32)
    frame = ScalarDisplayFrame(values,WindowLevel(-30,200))
    p.set_array('v',np.zeros((2,2),dtype=np.uint8))
    p.set_scalar('v',frame)
    assert not p.requestImage('v/1',QSize(),QSize(0,0)).isNull()
    image = p.requestImage('v:scalar-cpu/1',QSize(),QSize(3,3))
    assert image.pixelColor(1,1).red() == 0
    assert image.pixelColor(0,1).red() == 102
    texture = p.requestImage('v:scalar/1',QSize(),QSize())
    p.set_scalar('v',replace(frame,inverted=True))
    assert p.requestImage('v:scalar/2',QSize(),QSize()).cacheKey() == texture.cacheKey()
    assert p.requestImage('v:scalar-cpu/2',QSize(),QSize(3,3)).pixelColor(1,1).red() == 255
    p.remove_image('v')
    assert not p._scalar_frames and not p._images


def test_rendered_scalar_image_matches_reference(qt_app, tmp_path):
    """Exercise the real QML component on either RHI or software, including padding/LUT."""
    from pathlib import Path
    from PySide6.QtCore import QUrl, QObject, Qt
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QImage
    from shiboken6 import delete
    from voxplane.ui.dicom_image_provider import DicomImageProvider
    component = Path('src/voxplane/qml/sections/center/viewportArea').resolve().as_uri()
    qml = tmp_path/'ScalarRender.qml'
    qml.write_text('''import QtQuick
import "'''+component+'''"
Item {
    id: root; width: 96; height: 64
    property var descriptor: ({})
    QtObject { id: data; property var scalarDisplay: root.descriptor; property string imageSource: "" }
    ScalarImage { id: image; objectName: "scalarImage"; width: 3; height: 2; scale: 32;
        transformOrigin: Item.TopLeft; controller: data; screenScaleX: 32; screenScaleY: 32 }
}''')
    requested_sizes = []
    class RecordingProvider(DicomImageProvider):
        def requestImage(self, image_id, size, requested_size):
            if ':scalar-cpu/' in image_id:
                requested_sizes.append((requested_size.width(), requested_size.height()))
            return super().requestImage(image_id, size, requested_size)
    provider = RecordingProvider()
    view = QQuickView()
    # A decorated Windows window has a minimum title-bar width (>96 px).
    # Keep this pixel comparison at the component's exact 96x64 canvas size.
    view.setFlags(Qt.Window | Qt.FramelessWindowHint)
    view.engine().addImageProvider('dicom', provider)
    view.setSource(QUrl.fromLocalFile(str(qml)))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    p = np.array([[-50.,-302.,200.],[50.,-80.,np.nan]],np.float32)
    try:
        for revision, (inverted, palette) in enumerate(((False,'grayscale'),(True,'grayscale'),(False,'hotIron'))):
            encoded, minimum, span = pack_scalar(p)
            frame=ScalarDisplayFrame(p,WindowLevel(-30,200),inverted,palette,encoded,minimum,span)
            provider.set_scalar('render',frame)
            view.rootObject().setProperty('descriptor',dict(source=f'image://dicom/render:scalar/{revision}',
                cpu=f'image://dicom/render:scalar-cpu/{revision}',lut=f'image://dicom/render:lut/{palette}',
                minimum=minimum,span=span,lower=-130,width=200,inverted=inverted))
            QTest.qWait(100)
            image=view.grabWindow().convertToFormat(QImage.Format_RGB888)
            assert not image.isNull()
            assert (image.width(), image.height()) == (round(96*view.devicePixelRatio()), round(64*view.devicePixelRatio()))
            array=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*3].reshape(image.height(),image.width(),3)
            expected=resample_display(frame,image.width(),image.height())
            if expected.ndim == 2: expected=np.repeat(expected[:,:,None],3,axis=2)
            np.testing.assert_allclose(array,expected,atol=1,rtol=0)
            root=view.rootObject().findChild(QObject,'scalarImage')
            fallback=view.rootObject().findChild(QObject,'scalarDisplayFallback')
            import os
            if os.environ.get('QSG_RHI_BACKEND') in ('metal', 'd3d11'):
                assert root.property('useShader'), 'Native RHI verification must exercise the shader'
            if root.property('useShader'):
                assert not fallback.property('source').toString()
            else:
                assert requested_sizes[-1] == (image.width(), image.height())
    finally:
        view.close(); delete(view); qt_app.processEvents()


from test_dicom_tags import qt_app
