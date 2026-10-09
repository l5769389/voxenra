"""Physical-space, copy-on-write edits of cropped binary labelmaps.

One stroke is a union of capsules between pointer samples, not disconnected
stamps. Slice painting uses a one-voxel-thick slab normal to the displayed
plane. Other segments are never overwritten.
"""
from collections import deque

import numpy as np

from .workspace_state import MAX_MASK_VOXELS


def brush(mask, offset, geometry, shape, start, end, diameter, *, erase=False, normal=None):
    start, end = np.asarray(start, float), np.asarray(end, float)
    if not np.isfinite([*start, *end, diameter]).all() or diameter <= 0:
        raise ValueError("Invalid brush geometry")
    radius = diameter / 2
    inverse = geometry.patient_to_voxel
    extent = radius * np.linalg.norm(inverse[:3, :3], axis=1) + 1
    centers = np.array([(inverse @ [*p, 1])[:3] for p in (start, end)])
    low = np.maximum(0, np.floor(centers.min(axis=0) - extent).astype(int))
    high = np.minimum(shape, np.ceil(centers.max(axis=0) + extent).astype(int) + 1)
    if np.any(high <= low):
        return mask, np.asarray(offset)
    offset = np.asarray(offset, int)
    if erase:
        low, high = np.maximum(low, offset), np.minimum(high, offset + mask.shape)
        if np.any(high <= low):
            return mask, offset
    lo, hi = np.minimum(low, offset), np.maximum(high, offset + mask.shape)
    if int(np.prod(hi - lo)) > MAX_MASK_VOXELS:
        raise ValueError("Segmentation exceeds the workspace size limit")
    result = None  # Allocate only when a selected voxel actually changes.
    # Evaluate in small slabs to bound temporary patient-coordinate arrays.
    vector = end - start
    length2 = float(vector @ vector)
    if normal is not None:
        normal = np.asarray(normal, float)
        normal /= np.linalg.norm(normal)
        thickness = 1 / np.linalg.norm(inverse[:3, :3] @ normal)
    for z in range(int(low[0]), int(high[0])):
        indices = np.indices((1, *(high - low)[1:]), dtype=float).reshape(3, -1).T
        indices += [z, low[1], low[2]]
        points = indices @ geometry.voxel_to_patient[:3, :3].T + geometry.voxel_to_patient[:3, 3]
        t = np.clip((points - start) @ vector / length2, 0, 1) if length2 else np.zeros(len(points))
        delta = points - start - t[:, None] * vector
        distance2 = np.einsum("ij,ij->i", delta, delta)
        if normal is None:
            selected = distance2 <= radius**2 + 1e-10
        else:
            depth = (points - end) @ normal
            selected = (distance2 - depth**2 <= radius**2 + 1e-10) & (depth >= -thickness / 2) & (depth < thickness / 2)
        if result is None:
            chosen = indices[selected].astype(int) - offset
            inside = np.all((chosen >= 0) & (chosen < mask.shape), axis=1)
            values = np.zeros(len(chosen), bool)
            values[inside] = mask[tuple(chosen[inside].T)]
            if not np.any(values != (not erase)):
                continue
            result = np.zeros(tuple(hi - lo), bool)
            result[tuple(slice(a, a + b) for a, b in zip(offset - lo, mask.shape))] = mask
        target = result[z - lo[0], low[1] - lo[1]:high[1] - lo[1], low[2] - lo[2]:high[2] - lo[2]]
        target[selected.reshape(target.shape)] = not erase
    return (mask, offset) if result is None else (result, lo)


def connected_component(mask, seed):
    """6-connected component, using runs to avoid a Python object per voxel."""
    seed = tuple(map(int, seed))
    if any(a < 0 or a >= b for a, b in zip(seed, mask.shape)) or not mask[seed]:
        raise ValueError("Click inside the selected segment")
    remaining = mask.copy()
    result = np.zeros_like(mask)
    queue = deque([seed])
    nz, ny, nx = mask.shape
    while queue:
        z, y, x = queue.popleft()
        if not remaining[z, y, x]:
            continue
        left, right = x, x + 1
        while left and remaining[z, y, left - 1]:
            left -= 1
        while right < nx and remaining[z, y, right]:
            right += 1
        remaining[z, y, left:right] = False
        result[z, y, left:right] = True
        for zz, yy in ((z-1, y), (z+1, y), (z, y-1), (z, y+1)):
            if 0 <= zz < nz and 0 <= yy < ny:
                line = remaining[zz, yy, left:right]
                starts = np.flatnonzero(line & ~np.r_[False, line[:-1]])
                queue.extend((zz, yy, left + int(a)) for a in starts)
    return result
