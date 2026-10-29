"""Value contracts for straightened CPR; all spatial quantities use patient LPS mm."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

import numpy as np

from .dicom_core import Vector3, MprImageGeometry

ALGORITHM_VERSION = 1
MAX_AXIS_SAMPLES = 4097
MAX_OUTPUT_PIXELS = 4_194_304
MAX_SLAB_SAMPLES = 1001
MAX_SAMPLE_WORK = 100_000_000


class CprError(ValueError):
    """Invalid CPR input or a request exceeding the supported sampling budget."""


def finite_number(value, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise CprError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise CprError(f"{name} must be a finite number") from error
    if not isfinite(number):
        raise CprError(f"{name} must be a finite number")
    return number


def readonly_array(value) -> np.ndarray:
    """Own immutable result storage, independent of mutable caller buffers."""
    array = np.ascontiguousarray(value)
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def _points(value) -> np.ndarray:
    try:
        raw = np.asarray(value)
        if raw.dtype.kind not in "fiu":
            raise CprError("Control points must be real numbers")
        points = raw.astype(np.float64, copy=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise CprError("Control points must contain three finite LPS coordinates") from error
    if (points.ndim != 2 or points.shape[1] != 3
            or not 2 <= len(points) <= 4096 or not np.isfinite(points).all()):
        raise CprError("A path needs 2–4096 finite three-dimensional control points")
    return points


@dataclass(frozen=True, slots=True)
class CprPath:
    path_id: str
    name: str
    control_points: tuple[Vector3, ...]
    revision: int = 1
    algorithm_version: int = ALGORITHM_VERSION

    def __post_init__(self):
        if not isinstance(self.path_id, str) or not self.path_id.strip() or len(self.path_id) > 128:
            raise CprError("Path ID must contain 1–128 characters")
        if not isinstance(self.name, str) or len(self.name) > 256:
            raise CprError("Path name must contain at most 256 characters")
        if type(self.revision) is not int or self.revision < 1:
            raise CprError("Path revision must be a positive integer")
        if type(self.algorithm_version) is not int or self.algorithm_version != ALGORITHM_VERSION:
            raise CprError("Unsupported CPR algorithm version")
        points = _points(self.control_points)
        with np.errstate(over="ignore", invalid="ignore"):
            differences = np.diff(points, axis=0)
            lengths = np.linalg.norm(differences, axis=1)
            total = float(lengths.sum())
        if not isfinite(total) or total > 10000:
            raise CprError("Path length exceeds the 10000 mm limit")
        if np.any(lengths < 1e-4):
            index = int(np.flatnonzero(lengths < 1e-4)[0])
            raise CprError(f"Control points {index + 1} and {index + 2} are too close")
        if total < .1:
            raise CprError("Path must be at least 0.1 mm long")
        directions = differences / lengths[:, None]
        reversals = np.sum(directions[:-1] * directions[1:], axis=1) <= -1 + 1e-6
        if np.any(reversals):
            index = int(np.flatnonzero(reversals)[0]) + 2
            raise CprError(f"Path reverses direction at control point {index}")
        object.__setattr__(self, "control_points", tuple(tuple(float(v) for v in p) for p in points))


@dataclass(frozen=True, slots=True)
class CprSettings:
    step_mm: float = .5
    width_mm: float = 40.
    angle_radians: float = 0.
    up_patient: Vector3 = (0., 0., 1.)
    projection: str = "thin"
    thickness_mm: float = 0.

    def __post_init__(self):
        for name in ("step_mm", "width_mm", "angle_radians", "thickness_mm"):
            object.__setattr__(self, name, finite_number(getattr(self, name), name))
        if not .05 <= self.step_mm <= 10:
            raise CprError("Sampling step must be between 0.05 and 10 mm")
        if not 0 < self.width_mm <= 500:
            raise CprError("Field width must be between 0 and 500 mm")
        if not 0 <= self.thickness_mm <= 100:
            raise CprError("Slab thickness must be between 0 and 100 mm")
        if self.projection not in ("thin", "mip", "mean"):
            raise CprError("Projection must be thin, mip or mean")
        try:
            raw = np.asarray(self.up_patient)
            if raw.dtype.kind not in "fiu":
                raise CprError("Initial direction must contain real numbers")
            up = raw.astype(np.float64, copy=False)
        except (TypeError, ValueError, OverflowError) as error:
            raise CprError("Initial direction must be a finite nonzero LPS vector") from error
        if up.shape != (3,) or not np.isfinite(up).all() or np.max(np.abs(up)) == 0:
            raise CprError("Initial direction must be a finite nonzero LPS vector")
        # Scaling first avoids overflow for a finite but very large direction.
        up = up / np.max(np.abs(up))
        up = up / np.linalg.norm(up)
        object.__setattr__(self, "up_patient", tuple(float(v) for v in up))


@dataclass(frozen=True, slots=True)
class CprCenterline:
    path_id: str
    path_revision: int
    algorithm_version: int
    distances_mm: np.ndarray
    points_patient: np.ndarray
    tangents_patient: np.ndarray
    laterals_patient: np.ndarray
    binormals_patient: np.ndarray

    @property
    def length_mm(self) -> float:
        return float(self.distances_mm[-1])

    @property
    def spacing_mm(self) -> float:
        return self.length_mm / (len(self.distances_mm) - 1)


@dataclass(frozen=True, slots=True)
class CprResult:
    """A curved grid: columns are arc distance, rows are local lateral offsets.

    This is deliberately not an MprImageGeometry. Only the central row's
    longitudinal distances are centerline arc lengths; the grid has no global
    patient-space affine or uniform Euclidean measurement calibration.
    """
    modality_pixels: np.ndarray
    centerline: CprCenterline
    offsets_mm: np.ndarray
    settings: CprSettings
    series_uid: str
    source_fingerprint: str

    @property
    def row_spacing_mm(self) -> float:
        return float(self.offsets_mm[1] - self.offsets_mm[0])


@dataclass(frozen=True, slots=True)
class CprCrossSection:
    """A physical thin plane and the path/source identity at sampling time."""
    modality_pixels: np.ndarray
    geometry: MprImageGeometry
    path_id: str
    path_revision: int
    algorithm_version: int
    distance_mm: float
    series_uid: str
    source_fingerprint: str
