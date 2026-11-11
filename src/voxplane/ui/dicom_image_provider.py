import numpy as np

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class DicomImageProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)
        self._images: dict[str, QImage] = {}
        self._content_keys: dict[str, tuple] = {}
        self._scalar_frames = {}

    def set_array(
        self,
        viewport_id: str,
        pixels: np.ndarray,
        content_key: tuple | None = None,
    ) -> None:
        if content_key is not None and self._content_keys.get(viewport_id) == content_key:
            return
        pixels = np.ascontiguousarray(
            pixels,
            dtype=np.uint8,
        )

        if pixels.ndim == 2:
            height, width = pixels.shape
            image_format = QImage.Format_Grayscale8
        elif pixels.ndim == 3 and pixels.shape[2] == 3:
            height, width, _ = pixels.shape
            image_format = QImage.Format_RGB888
        elif pixels.ndim == 3 and pixels.shape[2] == 4:
            height, width, _ = pixels.shape
            image_format = QImage.Format_RGBA8888
        else:
            raise ValueError(
                "DICOM image must be grayscale, RGB, or RGBA uint8 pixels"
            )

        image = QImage(
            pixels.data,
            width,
            height,
            pixels.strides[0],
            image_format,
        )

        # 必须 copy，让 QImage 脱离 NumPy 内存生命周期
        self._images[viewport_id] = image.copy()
        if content_key is not None:
            self._content_keys[viewport_id] = content_key
        else:
            self._content_keys.pop(viewport_id, None)

    def set_image(self, image_id: str, image: QImage) -> None:
        self._images[image_id] = image.copy()
        self._content_keys.pop(image_id, None)

    def set_scalar(self, viewport_id, frame):
        from voxplane.core.scalar_display import pack_scalar
        from voxplane.core.color_maps import apply_color_map
        if frame is None:
            self._scalar_frames.pop(viewport_id, None)
            self.remove_image(viewport_id+":scalar")
            self.remove_image(viewport_id+":lut")
            return
        previous = self._scalar_frames.get(viewport_id)
        self._scalar_frames[viewport_id] = frame
        if previous is None or previous.pixels is not frame.pixels:
            encoded = frame.encoded if frame.encoded is not None else pack_scalar(frame.pixels)[0]
            self.set_array(viewport_id+":scalar", encoded)
        if previous is None or previous.color_map != frame.color_map:
            lut = apply_color_map(np.arange(256,dtype=np.uint8)[None,:],frame.color_map)
            self.set_array(viewport_id+":lut",lut)

    def remove_image(self, viewport_id: str) -> None:
        self._images.pop(viewport_id, None)
        if viewport_id in self._scalar_frames:
            self.set_scalar(viewport_id, None)
        self._content_keys.pop(viewport_id, None)

    def requestImage(
        self,
        image_id: str,
        size: QSize,
        requested_size: QSize,
    ) -> QImage:
        # image_id 形式：viewport-id/version
        viewport_id = image_id.split("/", 1)[0]

        if viewport_id.endswith(":scalar-cpu"):
            from voxplane.core.scalar_display import resample_display
            frame = self._scalar_frames.get(viewport_id[:-11])
            if frame is None:
                return QImage()
            h, w = frame.pixels.shape
            if requested_size.width() > 0 and requested_size.height() > 0:
                w, h = max(1,requested_size.width()), max(1,requested_size.height())
            pixels = resample_display(frame,w,h)
            fmt = QImage.Format_Grayscale8 if pixels.ndim == 2 else QImage.Format_RGB888
            image = QImage(pixels.data,w,h,pixels.strides[0],fmt).copy()
            if size is not None:
                size.setWidth(w); size.setHeight(h)
            return image

        image = self._images.get(
            viewport_id,
            QImage(),
        )

        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())

        if requested_size.width() > 0 and requested_size.height() > 0:
            return image.scaled(
                requested_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )

        return image
