"""A deterministic, shared pixel decoder policy for viewing and export.

Never fall back to Pillow or rewrite the source transfer syntax. Compressed
pixels are decoded by the same bundled plugins on every supported platform.
"""
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pydicom.pixels import get_decoder, pixel_array, iter_pixels
from pydicom.uid import UID

from voxplane.i18n import message

# Values are pydicom decoder plugin names, not distribution names.
PLUGINS = {
    "1.2.840.10008.1.2.5": "pydicom",  # RLE
    **{f"1.2.840.10008.1.2.4.{n}": "gdcm" for n in (50, 51, 57, 70)},
    **{f"1.2.840.10008.1.2.4.{n}": "pylibjpeg" for n in (90, 91)},
    **{f"1.2.840.10008.1.2.4.{n}": "pyjpegls" for n in (80, 81)},
}


class PixelDecodeError(ValueError):
    """Safe localized diagnostics, without source paths or patient values."""


def decoder_options(header):
    uid = UID(str(getattr(getattr(header, "file_meta", None), "TransferSyntaxUID", "")))
    if not uid.is_transfer_syntax:
        raise PixelDecodeError(message("codec.unsupported", syntax=str(uid) or "unknown"))
    if not uid.is_compressed:
        return {}, uid
    plugin = PLUGINS.get(str(uid))
    if plugin is None:
        raise PixelDecodeError(message("codec.unsupported", syntax=uid.name))
    if str(uid) == "1.2.840.10008.1.2.4.51" and int(getattr(header, "BitsStored", 0)) != 8:
        raise PixelDecodeError(message("codec.precision", syntax=uid.name))
    decoder = get_decoder(uid)
    if plugin not in decoder.available_plugins:
        raise PixelDecodeError(message("codec.missing", syntax=uid.name))
    return {"decoding_plugin": plugin}, uid


def _header(source, header):
    if header is not None:
        return header
    if isinstance(source, Dataset):
        return source
    return pydicom.dcmread(Path(source), stop_before_pixels=True)


def _dataset_fallback(source, kwargs):
    # Some legacy files mix explicit and implicit VR within the same dataset.
    # The streaming pixel reader may misread their Pixel Data element, while
    # dcmread can recover it. Bound encoded memory and retain indexed decoding.
    if isinstance(source, Dataset) or Path(source).stat().st_size > 64 * 1024 * 1024:
        return None
    dataset = pydicom.dcmread(source)
    target = kwargs.get("ds_out")
    if target is not None:
        target.file_meta = dataset.file_meta
        for element in dataset:
            if element.tag not in (0x7FE00010, 0x7FE00008, 0x7FE00009):
                target.add(element)
    return dataset


def decode_pixels(source, *, header=None, **kwargs):
    options, uid = decoder_options(_header(source, header))
    try:
        try:
            return pixel_array(source, **options, **kwargs)
        except ValueError:
            dataset = _dataset_fallback(source, kwargs)
            if dataset is None:
                raise
            return pixel_array(dataset, **options, **kwargs)
    except (OSError, MemoryError):
        raise
    except Exception as exc:
        raise PixelDecodeError(message("codec.failed", syntax=uid.name)) from exc


def iter_decoded_pixels(source, *, header=None, **kwargs):
    options, uid = decoder_options(_header(source, header))
    yielded = False
    try:
        try:
            for frame in iter_pixels(source, **options, **kwargs):
                yielded = True
                yield frame
        except ValueError:
            # Never duplicate already emitted frames after a later failure.
            if yielded:
                raise
            dataset = _dataset_fallback(source, kwargs)
            if dataset is None:
                raise
            yield from iter_pixels(dataset, **options, **kwargs)
    except (OSError, MemoryError):
        raise
    except Exception as exc:
        raise PixelDecodeError(message("codec.failed", syntax=uid.name)) from exc
