"""Validate local AI inputs/results without importing an inference runtime."""
from itertools import product
import json
from pathlib import Path
import numpy as np
from .nrrd_exchange import read_nrrd
from .segmentation_masks import mask_record
from .workspace_state import MAX_MASK_VOXELS
from qt_dicom_viewer.i18n import message as _msg

DEFAULT_ORGANS = ('liver', 'spleen', 'kidney_left', 'kidney_right')


def validate_input(volume, modality):
    pixels = volume.modality_pixels
    affine = volume.geometry.voxel_to_patient
    basis = affine[:3, :3]
    spacing = np.linalg.norm(basis, axis=0)
    if (modality != 'CT' or volume.pixel_value_meta.unit.upper() != 'HU'
            or pixels.ndim != 3 or min(pixels.shape) < 2
            or pixels.size > MAX_MASK_VOXELS or not np.isfinite(affine).all()
            or np.any(spacing <= 0) or not np.isfinite(pixels).all()
            or not np.allclose((basis / spacing).T @ (basis / spacing), np.eye(3), atol=1e-5, rtol=0)):
        raise ValueError(_msg('autoSeg.unsupported'))


def same_grid(shape, affine, expected_shape, expected_affine):
    if tuple(shape) != tuple(expected_shape) or np.shape(affine) != (4, 4) or not np.isfinite(affine).all():
        return False
    points = np.array([(*p, 1) for p in product(*[(0, n-1) for n in shape])]).T
    distances = np.linalg.norm(((affine - expected_affine) @ points)[:3], axis=0)
    return bool(np.max(distances) <= .001)


def read_results(root, volume, organs, *, phase=None, cancelled=lambda: False):
    root = Path(root).resolve()
    document = json.loads((root / 'result.json').read_text(encoding='utf-8'))
    if document.get('protocol') != 1 or set(document.get('outputs', {})) != set(organs):
        raise ValueError(_msg('autoSeg.invalidResult'))
    records, evaluations, empty = [], {}, []
    for organ in organs:
        if cancelled():
            raise InterruptedError()
        path = (root / document['outputs'][organ]).resolve()
        if path.parent != root or path.suffix != '.nrrd':
            raise ValueError(_msg('autoSeg.invalidResult'))
        data, affine, _ = read_nrrd(path)
        if (not same_grid(data.shape, affine, volume.modality_pixels.shape, volume.geometry.voxel_to_patient)
                or not np.isin(data, (0, 1)).all()):
            raise ValueError(_msg('results.geometryMismatch'))
        if not data.any():
            empty.append(organ)
            continue
        record, evaluation = mask_record(volume, data.astype(bool), (0, 0, 0), name=organ,
            phase=phase, automatic_segmentation={
                'engine': 'TotalSegmentator', 'version': str(document.get('version', '')),
                'model': str(document.get('model', 'total-fast-297')), 'organ': organ,
                'fast': True, 'device': str(document.get('device', '')),
                'completed_at': str(document.get('completed_at', '')), 'source_phase': phase,
                'source_fingerprint': volume.fingerprint})
        records.append(record)
        evaluations[record['id']] = evaluation
    if not records:
        raise ValueError(_msg('autoSeg.empty'))
    if sum(r['mask'].size for r in records) > MAX_MASK_VOXELS:
        raise ValueError(_msg('seg.tooLarge'))
    return records, evaluations, empty
