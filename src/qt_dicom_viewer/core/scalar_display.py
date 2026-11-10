"""Display-only scalar interpolation. Quantitative arrays are never modified."""
from dataclasses import dataclass
import numpy as np
from qt_dicom_viewer.model import WindowLevel
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.color_maps import apply_color_map


@dataclass(frozen=True, slots=True)
class ScalarDisplayFrame:
    pixels: np.ndarray
    window: WindowLevel
    inverted: bool = False
    color_map: str = 'grayscale'
    encoded: np.ndarray | None = None
    minimum: float = 0.
    span: float = 1.


def pack_scalar(pixels):
    """24-bit normalized RGB plus validity alpha; decode before interpolating.

    At a 65536 HU range quantization is under .004 HU. This is a display texture,
    never a replacement for measurement samples. Nearest texture filtering is
    required because carrying between packed bytes is not linear.
    """
    finite = np.isfinite(pixels)
    lower = float(np.min(pixels[finite])) if np.any(finite) else 0.
    upper = float(np.max(pixels[finite])) if np.any(finite) else 0.
    span = max(upper-lower, 1e-20)
    scaled = (np.where(finite,pixels,lower).astype(np.float64)-lower)/span
    codes = np.rint(np.clip(scaled,0,1)*16777215).astype(np.uint32)
    rgba = np.empty((*pixels.shape,4),dtype=np.uint8)
    rgba[...,0] = codes >> 16; rgba[...,1] = (codes >> 8) & 255; rgba[...,2] = codes & 255
    rgba[...,3] = finite.astype(np.uint8)*255
    return rgba, lower, span


def unpack_scalar(rgba, lower, span):
    codes = rgba[...,0].astype(np.uint32)*65536+rgba[...,1].astype(np.uint32)*256+rgba[...,2]
    return np.where(rgba[...,3] > 0, lower+codes.astype(np.float64)*(span/16777215),np.nan)


def resample_display(frame, width, height):
    """Pixel-center aligned bilinear sampling before VOI/LUT, in bounded strips."""
    pixels = frame.pixels
    rows, columns = pixels.shape
    x = np.clip((np.arange(width)+.5)*columns/width-.5,0,columns-1)
    y = np.clip((np.arange(height)+.5)*rows/height-.5,0,rows-1)
    x0, y0 = x.astype(int), y.astype(int)
    x1, y1 = np.minimum(x0+1,columns-1), np.minimum(y0+1,rows-1)
    wx, wy = (x-x0).astype(np.float32), (y-y0).astype(np.float32)
    out = np.empty((height,width),dtype=np.uint8)
    for start in range(0,height,64):
        end = min(start+64,height)
        a, b = y0[start:end,None], y1[start:end,None]
        wy_chunk = wy[start:end,None]
        values = np.zeros((end-start,width),dtype=np.float32)
        coverage = np.zeros_like(values)
        for sample, weight in ((pixels[a,x0],(1-wy_chunk)*(1-wx)),
                               (pixels[a,x1],(1-wy_chunk)*wx),
                               (pixels[b,x0],wy_chunk*(1-wx)),(pixels[b,x1],wy_chunk*wx)):
            valid = np.isfinite(sample)
            values += np.where(valid,sample,0)*weight
            coverage += valid*weight
        values[coverage < .99999] = np.nan
        out[start:end] = DicomLoader.apply_window(values,frame.window,frame.inverted,minimum_width=1e-9)
    return apply_color_map(out,frame.color_map)
