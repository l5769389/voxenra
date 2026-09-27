"""NRRD / Slicer labelmap exchange, in patient LPS coordinates.

Supported subset: 3D scalar images and 3D/4D binary Slicer segmentations;
attached or single-file detached raw/gzip payloads. Unsupported encodings and
non-spatial axes are rejected explicitly. No image interpolation is implicit.
"""
from pathlib import Path
import gzip
import math
import os
import re
import tempfile

import numpy as np

from .segmentation_masks import mask_record
from .workspace_state import MAX_MASK_VOXELS
from qt_dicom_viewer.i18n import message as _msg

_TYPES = {name: code for names, code in [
    (("uchar", "unsigned char", "uint8", "uint8_t"), "u1"),
    (("char", "signed char", "int8", "int8_t"), "i1"),
    (("short", "short int", "signed short", "int16", "int16_t"), "i2"),
    (("ushort", "unsigned short", "uint16", "uint16_t"), "u2"),
    (("int", "signed int", "int32", "int32_t"), "i4"),
    (("uint", "unsigned int", "uint32", "uint32_t"), "u4"),
    (("float",), "f4"), (("double",), "f8")
] for name in names}


def _invalid():
    return ValueError(_msg("nrrd.invalid"))


def read_nrrd(path):
    """Return C-order (k,j,i[,layer]) data, LPS affine and header fields."""
    path = Path(path)
    with path.open("rb") as stream:
        if stream.readline(32).strip() not in [f"NRRD000{i}".encode() for i in range(1, 6)]:
            raise _invalid()
        header, total = {}, 0
        while True:
            line = stream.readline(1024 * 1024 + 1)
            total += len(line)
            if total > 1024 * 1024 or not line:
                raise _invalid()
            line = line.decode("utf-8").strip()
            if not line:
                break
            if line.startswith("#"):
                continue
            delimiter = ":=" if ":=" in line else ":"
            if delimiter not in line:
                raise _invalid()
            key, value = line.split(delimiter, 1)
            if key in header:
                raise _invalid()
            header[key] = value.strip()
        try:
            sizes = tuple(map(int, header["sizes"].split()))
            ndim = int(header["dimension"])
            if ndim not in (3, 4) or len(sizes) != ndim or min(sizes) <= 0 or math.prod(sizes) > MAX_MASK_VOXELS:
                raise _invalid()
            dtype = np.dtype(_TYPES[header["type"]])
            endian = header.get("endian", "little")
            if endian not in ("little", "big"):
                raise _invalid()
            dtype = dtype.newbyteorder("<" if endian == "little" else ">")
            if any(int(header.get(k, "0")) != 0 for k in ("byte skip", "line skip")):
                raise _invalid()
            length = math.prod(sizes) * dtype.itemsize
            if length > 1024**3:
                raise _invalid()
            detached = header.get("data file", header.get("datafile"))
            source = stream
            if detached:
                # Detached payloads must remain beside their header; never
                # interpret LIST, URL, absolute or parent-traversing paths.
                relative = Path(detached.strip('"'))
                candidate = (path.parent / relative).resolve()
                if relative.is_absolute() or not candidate.is_relative_to(path.parent.resolve()) or not candidate.is_file():
                    raise _invalid()
                source = candidate.open("rb")
            try:
                encoding = header["encoding"].lower()
                if encoding in ("gzip", "gz"):
                    with gzip.GzipFile(fileobj=source) as decoded:
                        payload = decoded.read(length + 1)
                elif encoding == "raw":
                    payload = source.read(length + 1)
                else:
                    raise _invalid()
            finally:
                if source is not stream:
                    source.close()
            if len(payload) != length:
                raise _invalid()
            tokens = re.findall(r"\([^)]*\)|none", header["space directions"], re.I)
            if len(tokens) != ndim:
                raise _invalid()
            spatial = [i for i, t in enumerate(tokens) if t.lower() != "none"]
            if len(spatial) != 3 or (ndim == 4 and (spatial != [1, 2, 3] or header.get("kinds", "").split()[0] != "list")):
                raise _invalid()
            directions = np.array([[float(v) for v in tokens[i][1:-1].split(",")] for i in spatial])
            origin = np.array([float(v) for v in header["space origin"].strip("()").split(",")])
            if directions.shape != (3, 3) or origin.shape != (3,):
                raise _invalid()
            affine = np.eye(4)
            affine[:3, :3], affine[:3, 3] = directions[::-1].T, origin
            space = header["space"].lower()
            if space in ("right-anterior-superior", "ras"):
                affine = np.diag([-1, -1, 1, 1]) @ affine
            elif space not in ("left-posterior-superior", "lps"):
                raise _invalid()
            if not np.isfinite(affine).all() or abs(np.linalg.det(affine[:3, :3])) < 1e-12:
                raise _invalid()
            if "space units" in header and re.findall(r'"([^"]+)"', header["space units"]) != ["mm"] * 3:
                raise _invalid()
            return np.frombuffer(payload, dtype).reshape(sizes[::-1]), affine, header
        except (KeyError, IndexError, TypeError, OverflowError) as error:
            raise _invalid() from error


def write_nrrd(path, pixels, affine, *, metadata=None, cancelled=lambda: False):
    pixels, affine = np.asarray(pixels), np.asarray(affine, float)
    if pixels.ndim not in (3, 4) or affine.shape != (4, 4) or not np.isfinite(affine).all():
        raise _invalid()
    dtype = np.dtype(pixels.dtype).newbyteorder("<")
    kind = {"u1": "unsigned char", "i1": "signed char", "i2": "short", "u2": "unsigned short",
            "i4": "int", "u4": "unsigned int", "f4": "float", "f8": "double"}.get(dtype.str[1:])
    if kind is None:
        raise _invalid()
    vector = lambda v: "(" + ",".join(format(float(x), ".17g") for x in v) + ")"
    directions = " ".join(vector(affine[:3, i]) for i in (2, 1, 0))
    layered = pixels.ndim == 4  # C array is k,j,i,layer; NRRD list axis first.
    lines = ["NRRD0005", f"type: {kind}", f"dimension: {pixels.ndim}",
        "space: left-posterior-superior", "sizes: " + " ".join(map(str, pixels.shape[::-1])),
        "space directions: " + ("none " if layered else "") + directions,
        "kinds: " + ("list " if layered else "") + "domain domain domain",
        "endian: little", "encoding: gzip", 'space units: "mm" "mm" "mm"',
        "space origin: " + vector(affine[:3, 3])]
    for key, value in (metadata or {}).items():
        if any(c in str(key) + str(value) for c in "\r\n"):
            raise _invalid()
        lines.append(f"{key}:={value}")
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix=".nrrd-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(("\n".join(lines) + "\n\n").encode("utf-8"))
            with gzip.GzipFile(fileobj=file, mode="wb", mtime=0) as compressed:
                for slab in pixels:
                    if cancelled():
                        raise InterruptedError()
                    compressed.write(np.asarray(slab, dtype=dtype).tobytes(order="C"))
            file.flush()
            os.fsync(file.fileno())
        if cancelled():
            raise InterruptedError()
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def write_segmentation(path, volume, records, evaluations, *, cancelled=lambda: False):
    records = [r for r in records if r["kind"] == "segmentation"]
    if not records or not any(evaluations[r["id"]].mask.any() for r in records):
        raise ValueError(_msg("results.noResults"))
    results = [evaluations[r["id"]] for r in records]
    low = np.min([r.offset for r in results], axis=0)
    high = np.max([r.offset + r.mask.shape for r in results], axis=0)
    if math.prod(high-low) * len(records) > MAX_MASK_VOXELS:
        raise ValueError(_msg("seg.tooLarge"))
    data = np.zeros((*tuple(high-low), len(records)), np.uint8)
    metadata = {"Segmentation_SourceRepresentation": "Binary labelmap",
        "Segmentation_ContainedRepresentationNames": "Binary labelmap|",
        "Segmentation_ReferenceImageExtentOffset": "0 0 0",
        "Voxenra_SourceSeriesUID": volume.series_uid}
    for n, (record, result) in enumerate(zip(records, results)):
        if cancelled():
            raise InterruptedError()
        if not np.allclose(result.geometry.voxel_to_patient, volume.geometry.voxel_to_patient, atol=1e-5, rtol=0):
            raise ValueError(_msg("results.geometryMismatch"))
        offset = result.offset-low
        data[(*[slice(int(a), int(a+b)) for a, b in zip(offset, result.mask.shape)], n)] = result.mask
        rgb = record["color"].lstrip("#")
        fields = {"ID": record["id"], "Name": record["name"], "NameAutoGenerated": "0",
            "Color": " ".join(str(int(rgb[i:i+2], 16)/255) for i in (0, 2, 4)),
            "ColorAutoGenerated": "0", "Layer": str(n), "LabelValue": "1",
            "Extent": " ".join(str(int(v)) for a,b in zip(offset[::-1], result.mask.shape[::-1]) for v in (a,a+b-1))}
        metadata.update({f"Segment{n}_{k}": v for k,v in fields.items()})
    affine = volume.geometry.voxel_to_patient.copy()
    affine[:3, 3] = (affine @ [*low, 1])[:3]
    write_nrrd(path, data, affine, metadata=metadata, cancelled=cancelled)


def read_segmentation(path, volume, *, phase=None, cancelled=lambda: False):
    data, affine, header = read_nrrd(path)
    if cancelled():
        raise InterruptedError()
    uid = header.get("Voxenra_SourceSeriesUID")
    if uid and uid != volume.series_uid:
        raise ValueError(_msg("results.geometryMismatch"))
    if header.get("Segmentation_SourceRepresentation", "Binary labelmap") != "Binary labelmap" or data.dtype.kind not in "ui":
        raise _invalid()
    transform = volume.geometry.patient_to_voxel @ affine
    steps = np.rint(transform[:3, :3]).astype(int)
    origin = np.rint(transform[:3, 3]).astype(int)
    if (not np.allclose(transform[:3, :3], steps, atol=1e-4, rtol=0)
            or not np.array_equal(steps.T @ steps, np.eye(3))
            or not np.allclose(transform[:3, 3], origin, atol=1e-3, rtol=0)):
        raise ValueError(_msg("nrrd.gridMismatch"))
    indices = sorted({int(m.group(1)) for key in header if (m := re.fullmatch(r"Segment(\d+)_ID", key))})
    if indices:
        specifications = [(n, int(header[f"Segment{n}_Layer"]), int(header[f"Segment{n}_LabelValue"])) for n in indices]
    else:
        if data.ndim != 3:
            raise _invalid()
        labels = np.unique(data)
        specifications = [(i, 0, int(v)) for i,v in enumerate(labels[labels != 0])]
    if not specifications or len(specifications) > 256:
        raise _invalid()
    records, evaluations, budget = [], {}, 0
    for n, layer, label in specifications:
        if cancelled():
            raise InterruptedError()
        if label <= 0 or layer < 0 or layer >= (data.shape[-1] if data.ndim == 4 else 1):
            raise _invalid()
        mask = (data[..., layer] if data.ndim == 4 else data) == label
        axes = np.argmax(abs(steps), axis=1)
        mask = mask.transpose(tuple(axes))
        offset = origin.copy()
        for axis, source_axis in enumerate(axes):
            if steps[axis, source_axis] < 0:
                mask = np.flip(mask, axis)
                offset[axis] -= mask.shape[axis]-1
        if np.any(offset < 0) or np.any(offset + mask.shape > volume.modality_pixels.shape):
            # Slicer may pad its labelmap. Only empty out-of-image padding may
            # be discarded; never truncate foreground outside the reference.
            lo, hi = np.maximum(0, -offset), np.minimum(mask.shape, np.array(volume.modality_pixels.shape)-offset)
            if np.any(hi <= lo):
                raise ValueError(_msg("nrrd.gridMismatch"))
            crop = mask[tuple(slice(a,b) for a,b in zip(lo,hi))]
            if crop.sum() != mask.sum():
                raise ValueError(_msg("nrrd.gridMismatch"))
            mask, offset = crop, offset+lo
        colors = np.array(list(map(float, header.get(f"Segment{n}_Color", "0.93 0.33 0.93").split())))
        if colors.shape != (3,) or not np.isfinite(colors).all() or np.any((colors<0)|(colors>1)):
            raise _invalid()
        color = "#" + "".join(f"{int(round(v*255)):02x}" for v in colors)
        record, evaluation = mask_record(volume, mask, offset,
            name=header.get(f"Segment{n}_Name", f"Label {label}"), color=color,
            phase=phase, allow_empty=True, mask_origin="nrrd")
        budget += record["mask"].size
        if budget > MAX_MASK_VOXELS:
            raise ValueError(_msg("seg.tooLarge"))
        records.append(record)
        evaluations[record["id"]] = evaluation
    return records, evaluations
