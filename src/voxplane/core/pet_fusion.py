"""Rigid PET→CT geometry, registration interchange and scalar compositing."""
from voxplane.i18n.messages import error_message
from voxplane.i18n import message as _msg
from dataclasses import replace, asdict
from hashlib import sha256
import json
from math import radians

import numpy as np

from voxplane.core.mpr_rotation import axis_angle_rotation_matrix


def fusion_series_error(series):
    from voxplane.core.volume_view import validate_volume_series
    from voxplane.core.volume_manager import VolumeManager
    from voxplane.core.pet import validate_pet_2d_series
    try:
        if series.modality.upper() not in ("CT", "PT"):
            raise ValueError(_msg('text.0260'))
        validate_pet_2d_series(series)
        validate_volume_series(series)
        VolumeManager._validate_instances(series.instances)
        first = series.instances[0]
        for item in series.instances:
            VolumeManager._validate_instance_geometry(item, first.rows, first.columns,
                first.pixel_spacing.row, first.pixel_spacing.column,
                np.asarray(first.image_orientation_patient))
        if len({i.frame_of_reference_uid for i in series.instances}) != 1:
            raise ValueError(_msg('text.0151'))
        return ""
    except (ValueError, RuntimeError, TypeError) as error:
        return _msg('fusion.invalidSource', detail=error_message(error))


def rigid_matrix(matrix):
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.size != 16:
        raise ValueError(_msg('text.0262'))
    matrix = matrix.reshape(4, 4)
    rotation = matrix[:3, :3]
    if (not np.isfinite(matrix).all() or
            not np.allclose(matrix[3], (0, 0, 0, 1), atol=1e-7, rtol=0) or
            not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0) or
            not np.isclose(np.linalg.det(rotation), 1, atol=1e-6, rtol=0)):
        raise ValueError(_msg('text.0263'))
    return matrix.copy()


def registration_from_parameters(translation, angles_degrees, pivot):
    values = np.asarray([*translation, *angles_degrees, *pivot], dtype=float)
    if values.shape != (9,) or not np.isfinite(values).all():
        raise ValueError(_msg('text.0264'))
    rotations = [axis_angle_rotation_matrix(tuple(np.eye(3)[i]), radians(a))
                 for i, a in enumerate(angles_degrees)]
    rotation = rotations[2] @ rotations[1] @ rotations[0]
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = np.asarray(translation) + pivot - rotation @ pivot
    return matrix


def parameters_from_registration(matrix, pivot):
    matrix = rigid_matrix(matrix)
    r = matrix[:3, :3]
    y = np.arcsin(np.clip(-r[2, 0], -1, 1))
    if abs(np.cos(y)) > 1e-7:
        x, z = np.arctan2(r[2, 1], r[2, 2]), np.arctan2(r[1, 0], r[0, 0])
    else:
        x, z = np.arctan2(-r[1, 2], r[1, 1]), 0.
    translation = matrix[:3, 3] - pivot + r @ pivot
    return translation, np.degrees((x, y, z))


def transformed_volume(volume, matrix):
    matrix = rigid_matrix(matrix)
    g = volume.geometry
    r = matrix[:3, :3]
    geometry = replace(g, origin_patient=tuple(r @ g.origin_patient + matrix[:3, 3]),
                       slice_index_direction_patient=tuple(r @ g.slice_index_direction_patient),
                       row_index_direction_patient=tuple(r @ g.row_index_direction_patient),
                       column_index_direction_patient=tuple(r @ g.column_index_direction_patient))
    return replace(volume, geometry=geometry)


def geometry_fingerprint(volume):
    return sha256(json.dumps(asdict(volume.geometry), sort_keys=True).encode()).hexdigest()


def registration_document(ct, pet, ct_for, pet_for, matrix, pivot):
    return dict(version=1, direction="PET_LPS_TO_CT_LPS", ctSeriesUID=ct.series_uid,
                petSeriesUID=pet.series_uid, ctFrameOfReferenceUID=ct_for,
                petFrameOfReferenceUID=pet_for, ctGeometry=geometry_fingerprint(ct),
                petGeometry=geometry_fingerprint(pet), matrix=rigid_matrix(matrix).tolist(),
                pivot=np.asarray(pivot, dtype=float).tolist())


def load_registration_document(document, expected):
    if not isinstance(document, dict):
        raise ValueError(_msg('text.0265'))
    for key in ("version", "direction", "ctSeriesUID", "petSeriesUID",
                "ctFrameOfReferenceUID", "petFrameOfReferenceUID", "ctGeometry", "petGeometry"):
        if document.get(key) != expected.get(key):
            raise ValueError(_msg('text.0266', value1=key))
    pivot = np.asarray(document.get("pivot"), dtype=float)
    if pivot.shape != (3,) or not np.isfinite(pivot).all():
        raise ValueError(_msg('text.0267'))
    return rigid_matrix(document.get("matrix")), pivot


def pet_rgb(gray, color_map):
    from voxplane.core.color_maps import color_lut
    return color_lut(color_map)[np.asarray(gray, dtype=np.uint8)]


def blend_pet_ct(ct_gray, pet_gray, pet_values, opacity, color_map="hotIron"):
    if not np.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError(_msg('text.0268'))
    ct = np.repeat(ct_gray[..., None], 3, axis=-1).astype(np.float32)
    rgb = pet_rgb(pet_gray, color_map).astype(np.float32)
    alpha = (opacity * (np.isfinite(pet_values) & (pet_values > 0)))[..., None]
    return np.ascontiguousarray(np.round(ct * (1-alpha) + rgb * alpha), dtype=np.uint8)
