"""Draw a synthetic curved tube and the actual CPR kernel outputs.

Requires matplotlib in the development environment; no production dependency.
Run: .venv/bin/python tests/manual/render_cpr_phantom.py /tmp/cpr-phantom.png
This is a numerical illustration, not a viewer screenshot or clinical study.
"""
import argparse
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_mpr_reslicer import _volume
from qt_dicom_viewer.core.cpr_reslicer import CprReslicer
from qt_dicom_viewer.model.cpr import CprPath, CprSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    z, y, x = np.indices((49, 97, 97), dtype=np.float32)
    x, y, z = x*.5-24, y*.5-24, z*.5-12
    theta = np.mod(np.arctan2(y, x), 2*np.pi)
    radius = 2.5 - 1.3*np.exp(-((theta-np.pi/2)/.4)**2)
    distance = np.hypot(np.hypot(x, y)-12, z)
    pixels = -900 + 1500*np.clip((radius-distance)/.5 + .5, 0, 1)
    volume = _volume(pixels, origin=(-24, -24, -12), slice_spacing=.5, row_spacing=.5, column_spacing=.5)
    angle = np.linspace(0, 1.5*np.pi, 301)
    points = np.column_stack((12*np.cos(angle), 12*np.sin(angle), np.zeros_like(angle)))
    path = CprPath("phantom", "Synthetic curved tube", points)
    reslicer = CprReslicer()
    result = reslicer.reslice(volume, path, CprSettings(step_mm=.2, width_mm=12))
    index = int(np.argmin(abs(result.centerline.distances_mm-6*np.pi)))
    cross = reslicer.cross_section(volume, result.centerline, index, width_mm=8, step_mm=.2)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), gridspec_kw={"width_ratios": [1, 1.6, 1]}, layout="constrained")
    style = dict(cmap="gray", vmin=-900, vmax=600, origin="lower", interpolation="nearest")
    axes[0].imshow(pixels[24], extent=(-24.25, 24.25, -24.25, 24.25), **style)
    axes[0].plot(points[:, 0], points[:, 1], color="#16a085", linewidth=1)
    axes[0].set(title="Source axial slice + manual path", xlabel="LPS X (mm)", ylabel="LPS Y (mm)")
    ds, du = result.centerline.spacing_mm, result.row_spacing_mm
    axes[1].imshow(result.modality_pixels, extent=(-ds/2, result.centerline.length_mm+ds/2, -6-du/2, 6+du/2), aspect="auto", **style)
    axes[1].axvline(cross.distance_mm, color="#16a085", linewidth=1)
    axes[1].set(title="Straightened CPR (thin)", xlabel="Centerline arc distance (mm)", ylabel="Local transverse offset (mm)")
    step = cross.geometry.row_spacing
    axes[2].imshow(cross.modality_pixels, extent=(-4-step/2, 4+step/2, -4-step/2, 4+step/2), **style)
    axes[2].set(title="Perpendicular cross-section", xlabel="Local U (mm)", ylabel="Local B (mm)")
    fig.suptitle("Synthetic tube with changing radius — geometry kernel only", fontsize=13)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150)
    plt.close(fig)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
