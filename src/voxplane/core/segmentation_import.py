"""Read binary SEG into source-linked native masks, never into ordinary images."""

from pathlib import Path

import highdicom as hd
import numpy as np
import pydicom
from pydicom.uid import SegmentationStorage, UID

from voxplane.core.dicom_results import source_headers
from voxplane.core.segmentation_masks import mask_record
from voxplane.core.workspace_state import MAX_MASK_VOXELS
from voxplane.i18n import message as _msg


def _functional(group, shared, name):
    sequence = group.get(name) or shared.get(name)
    if not sequence or len(sequence) != 1:
        raise ValueError(_msg("seg.invalidGeometry"))
    return sequence[0]


def _references(group):
    return [
        source
        for derivation in group.get("DerivationImageSequence", [])
        for source in derivation.get("SourceImageSequence", [])
    ]


def _binary_frames(path, header):
    rows, cols, frames = (
        int(header.Rows),
        int(header.Columns),
        int(header.NumberOfFrames),
    )
    if header.file_meta.TransferSyntaxUID.is_compressed:
        yield from pydicom.pixels.iter_pixels(path)
        return
    # Binary frames are bit-contiguous, not byte-padded individually. Decode
    # explicit bit offsets to also handle odd-sized frames (e.g. 9 x 11).
    dataset = pydicom.dcmread(path, specific_tags=["PixelData"])
    data = dataset.PixelData
    count = rows * cols
    length = (frames * count + 7) // 8
    if len(data) not in (length, length + (length % 2)):
        raise ValueError(_msg("seg.invalidGeometry"))
    packed = np.frombuffer(data, dtype=np.uint8)
    for index in range(frames):
        start, end = index * count, (index + 1) * count
        bits = np.unpackbits(packed[start // 8 : (end + 7) // 8], bitorder="little")
        yield bits[start % 8 : start % 8 + count].reshape(rows, cols)


def read_segmentation(path, volume, instances, *, phase=None, cancelled=lambda: False):
    """Support binary SEG, sparse/permuted frames and cropped/flipped native grids.

    Non-native spacing and fractional/labelmap SEG are explicitly rejected.
    Source and temporal references are validated before any record is published.
    """

    def check():
        if cancelled():
            raise InterruptedError(_msg("results.cancelled"))

    check()
    path = Path(path)
    ds = pydicom.dcmread(path, stop_before_pixels=True)
    if (
        ds.get("SOPClassUID") != SegmentationStorage
        or ds.get("SegmentationType") != "BINARY"
    ):
        raise ValueError(_msg("seg.binaryOnly"))
    frames, rows, cols = (
        int(ds.get("NumberOfFrames", 0)),
        int(ds.get("Rows", 0)),
        int(ds.get("Columns", 0)),
    )
    if (
        min(frames, rows, cols) <= 0
        or frames * rows * cols > MAX_MASK_VOXELS
        or ds.get("BitsAllocated") != 1
    ):
        raise ValueError(_msg("seg.tooLarge"))
    if (
        ds.get("SamplesPerPixel") != 1
        or ds.get("BitsStored") != 1
        or ds.get("HighBit") != 0
        or ds.get("PixelRepresentation") != 0
        or not str(ds.get("SOPInstanceUID", ""))
        or not UID(str(ds.SOPInstanceUID)).is_valid
    ):
        raise ValueError(_msg("seg.invalidGeometry"))
    descriptions = {int(d.SegmentNumber): d for d in ds.get("SegmentSequence", [])}
    if (
        not descriptions
        or len(descriptions) != len(ds.SegmentSequence)
        or min(descriptions) < 1
    ):
        raise ValueError(_msg("seg.invalidGeometry"))
    cache = {}
    sources = source_headers(instances, cache)
    first = sources[0]
    if (
        str(ds.get("StudyInstanceUID", "")) != str(first.StudyInstanceUID)
        or not UID(str(ds.get("FrameOfReferenceUID", ""))).is_valid
        or any(
            str(ds.FrameOfReferenceUID) != str(s.get("FrameOfReferenceUID", ""))
            for s in sources
        )
        or str(ds.get("PatientID", "")) != str(first.PatientID)
        or str(ds.get("IssuerOfPatientID", ""))
        != str(first.get("IssuerOfPatientID", ""))
    ):
        raise ValueError(_msg("seg.wrongSource"))
    declared = [
        s
        for s in ds.get("ReferencedSeriesSequence", [])
        if str(s.SeriesInstanceUID) == str(first.SeriesInstanceUID)
    ]
    if not declared:
        raise ValueError(_msg("seg.wrongSource"))
    root_refs = {
        str(r.ReferencedSOPInstanceUID)
        for s in declared
        for r in s.get("ReferencedInstanceSequence", [])
    }
    source_refs = {
        (i.sop_instance_uid, None if i.frame_index is None else i.frame_index + 1): i
        for i in instances
    }
    source_uids = {r[0] for r in source_refs}
    shared_seq = ds.get("SharedFunctionalGroupsSequence", [])
    if (
        len(shared_seq) != 1
        or len(ds.get("PerFrameFunctionalGroupsSequence", [])) != frames
    ):
        raise ValueError(_msg("seg.invalidGeometry"))
    shared = shared_seq[0]
    g = volume.geometry
    inverse = g.patient_to_voxel
    shape = np.array(volume.modality_pixels.shape)
    plans = []
    seen = set()
    for group in ds.PerFrameFunctionalGroupsSequence:
        check()
        segment = int(
            _functional(
                group, shared, "SegmentIdentificationSequence"
            ).ReferencedSegmentNumber
        )
        if segment not in descriptions:
            raise ValueError(_msg("seg.invalidGeometry"))
        position = np.asarray(
            _functional(group, shared, "PlanePositionSequence").ImagePositionPatient,
            dtype=float,
        )
        orientation = np.asarray(
            _functional(
                group, shared, "PlaneOrientationSequence"
            ).ImageOrientationPatient,
            dtype=float,
        )
        spacing = np.asarray(
            _functional(group, shared, "PixelMeasuresSequence").PixelSpacing,
            dtype=float,
        )
        if (
            position.shape != (3,)
            or orientation.shape != (6,)
            or spacing.shape != (2,)
            or not np.isfinite(np.r_[position, orientation, spacing]).all()
            or min(spacing) <= 0
            or not np.allclose(
                orientation.reshape(2, 3) @ orientation.reshape(2, 3).T,
                np.eye(2),
                atol=1e-5,
            )
        ):
            raise ValueError(_msg("seg.invalidGeometry"))
        origin = (inverse @ [*position, 1])[:3]
        steps = inverse[:3, :3] @ np.column_stack(
            (orientation[:3] * spacing[1], orientation[3:] * spacing[0])
        )
        integer_steps = np.rint(steps).astype(int)
        if (
            not np.allclose(origin, np.rint(origin), atol=1e-3, rtol=0)
            or not np.allclose(steps, integer_steps, atol=1e-5, rtol=0)
            or not np.array_equal(integer_steps.T @ integer_steps, np.eye(2))
        ):
            raise ValueError(_msg("seg.invalidGeometry"))
        origin = np.rint(origin).astype(int)
        # Repeated frames for one segment would silently union contradictory
        # pixels. Multiple segments at the same position remain independent.
        key = (segment, *origin, *integer_steps.ravel())
        if key in seen:
            raise ValueError(_msg("seg.duplicateFrame"))
        seen.add(key)
        refs = _references(group) or _references(shared)
        if refs:
            for ref in refs:
                uid = str(ref.ReferencedSOPInstanceUID)
                frame_numbers = ref.get("ReferencedFrameNumber")
                numbers = (
                    list(frame_numbers)
                    if isinstance(frame_numbers, (list, pydicom.multival.MultiValue))
                    else [frame_numbers]
                )
                for number in numbers:
                    number = int(number) if number is not None else None
                    if (uid, number) not in source_refs:
                        raise ValueError(_msg("seg.wrongPhase"))
                    instance = source_refs[uid, number]
                    if str(ref.ReferencedSOPClassUID) != str(
                        cache[Path(instance.path)].SOPClassUID
                    ):
                        raise ValueError(_msg("seg.wrongSource"))
                    # For a preserved native slice, the referenced source must
                    # be on that slice, even if the SEG has a cropped origin.
                    if ref.get("SpatialLocationsPreserved") == "YES":
                        normal = np.cross(orientation[:3], orientation[3:])
                        if (
                            abs(
                                np.dot(
                                    position
                                    - np.array(instance.image_position_patient),
                                    normal,
                                )
                            )
                            > 1e-3
                        ):
                            raise ValueError(_msg("seg.wrongPhase"))
        elif (
            not root_refs
            or not root_refs <= source_uids
            or any(i.frame_index is not None for i in instances)
        ):
            raise ValueError(_msg("seg.wrongPhase"))
        plans.append((segment, origin, integer_steps))
    # Allocate bounded native crops from frame extents, then decode one plane
    # at a time. Avoid a full (frames, rows, columns, segments) array or keeping
    # every foreground voxel as three integer coordinates.
    bounds = {}
    for segment, origin, steps in plans:
        corners = origin[:, None] + steps @ np.array(
            [[0, cols - 1, 0, cols - 1], [0, 0, rows - 1, rows - 1]]
        )
        lo, hi = (
            np.maximum(corners.min(axis=1), 0),
            np.minimum(corners.max(axis=1) + 1, shape),
        )
        if np.any(hi <= lo):
            raise ValueError(_msg("seg.invalidGeometry"))
        if segment in bounds:
            lo, hi = (
                np.minimum(lo, bounds[segment][0]),
                np.maximum(hi, bounds[segment][1]),
            )
        bounds[segment] = lo, hi
    budget = sum(int(np.prod(hi - lo)) for lo, hi in bounds.values())
    if budget > MAX_MASK_VOXELS:
        raise ValueError(_msg("seg.tooLarge"))
    masks = {n: np.zeros(tuple(hi - lo), dtype=bool) for n, (lo, hi) in bounds.items()}
    decoded_frames = 0
    for index, pixels in enumerate(_binary_frames(path, ds)):
        check()
        if index >= len(plans):
            raise ValueError(_msg("seg.invalidGeometry"))
        segment, origin, steps = plans[index]
        decoded_frames += 1
        yy, xx = np.nonzero(pixels)
        native = origin[:, None] + steps[:, 0, None] * xx + steps[:, 1, None] * yy
        if np.any(native < 0) or np.any(native >= shape[:, None]):
            raise ValueError(_msg("seg.invalidGeometry"))
        masks[segment][tuple(native - bounds[segment][0][:, None])] = True
    if decoded_frames != frames:
        raise ValueError(_msg("seg.invalidGeometry"))
    records, evaluations = [], {}
    for number, description in descriptions.items():
        check()
        name = str(description.get("SegmentLabel") or f"Segment {number}")
        mask = masks.get(number)
        if mask is None or not mask.any():
            raise ValueError(_msg("results.emptySegment", name=name))
        lo = bounds[number][0]
        color = "#ed55ed"
        if "RecommendedDisplayCIELabValue" in description:
            rgb = hd.color.CIELabColor.from_dicom_value(
                description.RecommendedDisplayCIELabValue
            ).to_rgb(clip=True)
            color = "#" + "".join(f"{int(c):02x}" for c in rgb)
        tracking = str(description.get("TrackingUID", ""))
        metadata = dict(
            mask_origin="imported",
            source_seg_uid=str(ds.SOPInstanceUID),
            source_segment_number=number,
            segment_description=description.to_json_dict(),
        )
        if tracking and UID(tracking).is_valid:
            metadata["tracking_uid"] = tracking
        record, evaluation = mask_record(
            volume, mask, lo, name=name, color=color, phase=phase, **metadata
        )
        records.append(record)
        evaluations[record["id"]] = evaluation
    check()
    return records, evaluations
